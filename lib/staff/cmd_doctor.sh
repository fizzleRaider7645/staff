#!/usr/bin/env bash

cmd_doctor() {
  case "${1:-}" in
    -h|--help)
      cat <<EOF
${BOLD}staff doctor${RESET} — check installation health

${BOLD}Usage:${RESET}
  staff doctor

Checks CLI setup, prerequisites, registry sync, and installation integrity.

EOF
      return 0
      ;;
  esac

  local issues=0

  printf "${BOLD}Staff Doctor${RESET}\n"
  printf "%s\n\n" "$(printf '%.0s─' {1..40})"

  # CLI check
  #
  # Not counted as an issue: whether your shell can find `staff` is a
  # convenience of your own setup, not a statement about the health of this
  # repo or of anything installed from it. Counting it made doctor exit
  # non-zero anywhere staff had not been symlinked onto PATH — CI included,
  # where nothing runs setup.sh.
  printf "${BOLD}CLI${RESET}\n"
  if command -v staff >/dev/null 2>&1; then
    ok "staff is in PATH"
  else
    info "staff is not in PATH — run ./setup.sh to add it"
  fi

  # Prerequisites
  printf "\n${BOLD}Prerequisites${RESET}\n"
  for cmd in jq git; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ok "$cmd found: $(command -v "$cmd")"
    else
      error "$cmd not found"
      issues=$((issues + 1))
    fi
  done

  for cmd in node python3 go cargo; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ok "$cmd found: $($cmd --version 2>/dev/null | head -1)"
    else
      info "$cmd not found (optional)"
    fi
  done

  # Projects
  printf "\n${BOLD}Projects${RESET}\n"
  require_jq
  local all count
  all=$(registry_projects)
  count=$(echo "$all" | jq 'length')
  ok "$count project(s) discovered"

  # There is no index to fall out of sync, but two projects can still answer
  # to one name, which makes `staff install <name>` ambiguous.
  local dupes
  dupes=$(echo "$all" | jq -r '
    group_by(.name)[] | select(length > 1)
    | "  " + .[0].name + ": " + ([.[].path] | join(", "))
  ')
  if [ -n "$dupes" ]; then
    error "Duplicate project name(s):"
    printf '%s\n' "$dupes" >&2
    issues=$((issues + 1))
  fi

  # A manifest missing its identifying fields would show up as a null row
  local malformed
  malformed=$(echo "$all" | jq -r '.[] | select(.name == null or .description == null) | "  " + .path')
  if [ -n "$malformed" ]; then
    error "Manifest(s) missing name or description:"
    printf '%s\n' "$malformed" >&2
    issues=$((issues + 1))
  fi

  # Sources
  if [ -d "$STAFF_ROOT/sources" ] && [ -n "$(ls -A "$STAFF_ROOT/sources" 2>/dev/null)" ]; then
    printf "\n${BOLD}Sources${RESET}\n"
    source "$STAFF_ROOT/lib/staff/cmd_add_source.sh"
    local source_dir source_name link_path recorded_ref current_ref
    for source_dir in "$STAFF_ROOT/sources"/*/; do
      [ -d "$source_dir" ] || continue
      source_dir="${source_dir%/}"
      source_name="$(basename "$source_dir")"
      link_path="$source_dir/repo"

      if [ ! -d "$link_path" ]; then
        error "$source_name: repo link does not resolve -> $(readlink "$link_path" 2>/dev/null || echo '<missing>')"
        issues=$((issues + 1))
        continue
      fi

      recorded_ref=$(source_meta_value "$source_dir/source.toml" "git_ref")
      if [ -n "$recorded_ref" ] && git -C "$link_path" rev-parse --git-dir >/dev/null 2>&1; then
        current_ref=$(git -C "$link_path" rev-parse HEAD 2>/dev/null || true)
        if [ -n "$current_ref" ] && [ "$current_ref" != "$recorded_ref" ]; then
          warn "$source_name: upstream moved since it was added — run: staff update_source $source_name"
          issues=$((issues + 1))
          continue
        fi
      fi
      ok "$source_name: up to date"
    done
  fi

  # Published plugins
  #
  # plugins/<name> is a snapshot of a project, so it can fall behind the
  # project it came from. The version is the contract: a bump that was never
  # republished is a release that never shipped.
  if [ -d "$STAFF_ROOT/plugins" ]; then
    printf "\n${BOLD}Published plugins${RESET}\n"
    local plugin_dir pname pmanifest pver project_version
    local mk_file="$STAFF_ROOT/.claude-plugin/marketplace.json"
    for plugin_dir in "$STAFF_ROOT/plugins"/*/; do
      [ -d "$plugin_dir" ] || continue
      plugin_dir="${plugin_dir%/}"
      pname="$(basename "$plugin_dir")"
      pmanifest="$plugin_dir/.claude-plugin/plugin.json"

      if [ ! -f "$pmanifest" ]; then
        error "$pname: no .claude-plugin/plugin.json — not a plugin; run: staff publish $pname"
        issues=$((issues + 1))
        continue
      fi

      pver=$(jq -r '.version // ""' "$pmanifest")
      project_version=$(echo "$all" | jq -r --arg n "$pname" '[.[] | select(.name == $n)] | .[0].version // empty')

      if [ -z "$project_version" ]; then
        warn "$pname: published, but no project by that name exists — remove plugins/$pname or restore the project"
        issues=$((issues + 1))
      elif [ "$pver" != "$project_version" ]; then
        warn "$pname: published v$pver, project is v$project_version — run: staff publish $pname"
        issues=$((issues + 1))
      else
        ok "$pname: v$pver matches its project"
      fi

      if ! jq -e --arg n "$pname" '.plugins[]? | select(.name == $n)' "$mk_file" >/dev/null 2>&1; then
        warn "$pname: not listed in .claude-plugin/marketplace.json — run: staff publish $pname"
        issues=$((issues + 1))
      fi
    done
  fi

  # Installation audit
  printf "\n${BOLD}Installations${RESET}\n"
  ensure_state_dir
  if [ -f "$STAFF_INSTALLED" ]; then
    local install_count
    install_count=$(jq '.installations | length' "$STAFF_INSTALLED")
    if [ "$install_count" -eq 0 ]; then
      info "No projects installed"
    else
      # Iterate installation records, not project names: a project can be
      # installed at both user and project scope, and each record carries its
      # own target and symlinks. Selecting by name returned every scope's
      # record at once, which reported each link once per scope and collapsed
      # a multi-scope .target into two lines that matched no file at all.
      local entry name scope target label multi
      while IFS= read -r entry; do
        [ -n "$entry" ] || continue

        name=$(echo "$entry" | jq -r '.project')
        scope=$(echo "$entry" | jq -r '.scope // "user"')
        target=$(echo "$entry" | jq -r '.target')

        # Only qualify the label when the same project is installed twice
        multi=$(jq --arg n "$name" '[.installations[] | select(.project == $n)] | length' "$STAFF_INSTALLED")
        label="$name"
        [ "$multi" -gt 1 ] && label="$name ($scope)"

        local all_ok=true

        # Check symlinks
        local symlink link_target
        while IFS= read -r symlink; do
          [ -n "$symlink" ] || continue
          if [ -L "$symlink" ]; then
            link_target=$(readlink "$symlink")
            if [ -e "$symlink" ]; then
              ok "$label: symlink OK ($symlink)"
            else
              error "$label: broken symlink ($symlink -> $link_target)"
              all_ok=false
            fi
          elif [ ! -e "$symlink" ]; then
            error "$label: missing symlink ($symlink)"
            all_ok=false
          fi
        done < <(echo "$entry" | jq -r '.symlinks[]? // empty')

        # Check config keys
        local config_key key_name
        while IFS= read -r config_key; do
          [ -n "$config_key" ] || continue
          if [ -f "$target" ]; then
            key_name="${config_key#mcpServers.}"
            if jq -e --arg key "$key_name" '.mcpServers[$key]' "$target" >/dev/null 2>&1; then
              ok "$label: config key OK ($config_key)"
            else
              error "$label: missing config key ($config_key in $target)"
              all_ok=false
            fi
          else
            error "$label: config file missing ($target)"
            all_ok=false
          fi
        done < <(echo "$entry" | jq -r '.config_keys[]? // empty')

        if [ "$all_ok" = false ]; then
          issues=$((issues + 1))
        fi
      done < <(jq -c '.installations[]' "$STAFF_INSTALLED")
    fi
  fi

  # Summary
  printf "\n%s\n" "$(printf '%.0s─' {1..40})"
  if [ "$issues" -eq 0 ]; then
    ok "All checks passed"
    return 0
  fi
  warn "$issues issue(s) found"
  return 1
}
