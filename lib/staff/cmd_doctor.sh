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
  printf "${BOLD}CLI${RESET}\n"
  if command -v staff >/dev/null 2>&1; then
    ok "staff is in PATH"
  else
    warn "staff is not in PATH — run ./setup.sh"
    issues=$((issues + 1))
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

  # Registry check
  printf "\n${BOLD}Registry${RESET}\n"
  if [ -f "$STAFF_REGISTRY" ]; then
    require_jq
    local count
    count=$(jq '.projects | length' "$STAFF_REGISTRY")
    local gen_at
    gen_at=$(jq -r '.generated_at' "$STAFF_REGISTRY")
    ok "registry.json exists: $count project(s), generated $gen_at"

    # Check if any staff.json is newer than registry
    local registry_mtime
    registry_mtime=$(stat -f %m "$STAFF_REGISTRY" 2>/dev/null || stat -c %Y "$STAFF_REGISTRY" 2>/dev/null)
    local stale=false
    local cat_dir
    for cat_dir in $CATEGORIES; do
      for manifest in "$STAFF_ROOT/$cat_dir"/*/staff.json; do
        [ -f "$manifest" ] || continue
        local manifest_mtime
        manifest_mtime=$(stat -f %m "$manifest" 2>/dev/null || stat -c %Y "$manifest" 2>/dev/null)
        if [ "$manifest_mtime" -gt "$registry_mtime" ] 2>/dev/null; then
          stale=true
          break 2
        fi
      done
    done
    if [ "$stale" = true ]; then
      warn "Registry may be stale — run: staff registry rebuild"
      issues=$((issues + 1))
    fi
  else
    warn "registry.json not found — run: staff registry rebuild"
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

  # Installation audit
  printf "\n${BOLD}Installations${RESET}\n"
  ensure_state_dir
  if [ -f "$STAFF_INSTALLED" ]; then
    local install_count
    install_count=$(jq '.installations | length' "$STAFF_INSTALLED")
    if [ "$install_count" -eq 0 ]; then
      info "No projects installed"
    else
      while read -r name; do
        local entry
        entry=$(jq -r --arg name "$name" '.installations[] | select(.project == $name)' "$STAFF_INSTALLED")

        local all_ok=true

        # Check symlinks
        while read -r symlink; do
          if [ -L "$symlink" ]; then
            local target
            target=$(readlink "$symlink")
            if [ -e "$target" ]; then
              ok "$name: symlink OK ($symlink)"
            else
              error "$name: broken symlink ($symlink -> $target)"
              all_ok=false
            fi
          elif [ ! -e "$symlink" ]; then
            error "$name: missing symlink ($symlink)"
            all_ok=false
          fi
        done < <(echo "$entry" | jq -r '.symlinks[]? // empty')

        # Check config keys
        while read -r config_key; do
          local settings_target
          settings_target=$(echo "$entry" | jq -r '.target')
          if [ -f "$settings_target" ]; then
            local key_name="${config_key#mcpServers.}"
            if jq -e --arg key "$key_name" '.mcpServers[$key]' "$settings_target" >/dev/null 2>&1; then
              ok "$name: config key OK ($config_key)"
            else
              error "$name: missing config key ($config_key in $settings_target)"
              all_ok=false
            fi
          fi
        done < <(echo "$entry" | jq -r '.config_keys[]? // empty')

        if [ "$all_ok" = false ]; then
          issues=$((issues + 1))
        fi
      done < <(jq -r '.installations[] | .project' "$STAFF_INSTALLED")
    fi
  fi

  # Summary
  printf "\n%s\n" "$(printf '%.0s─' {1..40})"
  if [ "$issues" -eq 0 ]; then
    ok "All checks passed"
  else
    warn "$issues issue(s) found"
  fi
}
