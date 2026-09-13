#!/usr/bin/env bash

cmd_registry() {
  case "${1:-}" in
    rebuild)
      shift
      registry_rebuild "$@"
      ;;
    -h|--help)
      cat <<EOF
${BOLD}staff registry${RESET} — manage the project registry

${BOLD}Usage:${RESET}
  staff registry rebuild    Rebuild registry.json from all staff.json files

EOF
      ;;
    *)
      error "Usage: staff registry rebuild"
      exit 1
      ;;
  esac
}

registry_rebuild() {
  require_jq

  local projects="[]"
  local count=0
  local rebuild_errors=0

  add_registry_entry() {
    local manifest="$1"
    local rel_path="$2"
    local sourced="$3"
    local source_name="${4:-}"

    local entry
    entry=$(jq \
      --arg path "$rel_path" \
      --arg sourced "$sourced" \
      --arg source_name "$source_name" \
      '{
        name: .name,
        category: .category,
        language: .language,
        description: .description,
        status: .status,
        path: $path,
        tags: (.tags // []),
        version: (.version // "0.0.0"),
        sourced: ($sourced == "true"),
        synthesized: (.synthesized // false),
        native_format: (.native_format // "staff")
      } + (if $source_name != "" then {source_name: $source_name} else {} end)' "$manifest") || {
      warn "Failed to parse $manifest — skipping"
      return
    }

    projects=$(echo "$projects" | jq --argjson entry "$entry" '. + [$entry]')
    count=$((count + 1))
  }

  scan_local_projects() {
    local cat_dir
    for cat_dir in $CATEGORIES; do
      local full_dir="$STAFF_ROOT/$cat_dir"
      [ -d "$full_dir" ] || continue

      for project_dir in "$full_dir"/*/; do
        [ -d "$project_dir" ] || continue
        local manifest="$project_dir/staff.json"
        [ -f "$manifest" ] || continue

        local rel_path="${project_dir#$STAFF_ROOT/}"
        rel_path="${rel_path%/}"
        add_registry_entry "$manifest" "$rel_path" "false"
      done
    done
  }

  scan_sourced_projects() {
    local sources_root="$STAFF_ROOT/sources"
    [ -d "$sources_root" ] || return 0

    local source_dir
    for source_dir in "$sources_root"/*/; do
      [ -d "$source_dir" ] || continue
      source_dir="${source_dir%/}"

      local source_name
      source_name="$(basename "$source_dir")"

      # A registered bundle whose repo link no longer resolves must not be
      # silently skipped: that drops every project it contributed and still
      # reports success.
      local repo_dir="$source_dir/repo"
      if [ ! -d "$repo_dir" ]; then
        if [ -L "$repo_dir" ] || [ -f "$source_dir/source.toml" ]; then
          local link_target
          link_target="$(readlink "$repo_dir" 2>/dev/null || echo "<missing>")"
          error "Source '$source_name': repo link does not resolve -> $link_target"
          rebuild_errors=$((rebuild_errors + 1))
        fi
        continue
      fi

      local root_manifest="$repo_dir/staff.json"
      if [ -f "$root_manifest" ]; then
        local root_rel_path="${repo_dir#$STAFF_ROOT/}"
        root_rel_path="${root_rel_path%/}"
        add_registry_entry "$root_manifest" "$root_rel_path" "true" "$source_name"
      fi

      local cat_dir
      for cat_dir in $CATEGORIES; do
        local full_dir="$repo_dir/$cat_dir"
        [ -d "$full_dir" ] || continue

        local project_dir
        for project_dir in "$full_dir"/*/; do
          [ -d "$project_dir" ] || continue
          local manifest="$project_dir/staff.json"
          [ -f "$manifest" ] || continue

          local rel_path="${project_dir#$STAFF_ROOT/}"
          rel_path="${rel_path%/}"
          add_registry_entry "$manifest" "$rel_path" "true" "$source_name"
        done
      done

      # Manifests staff synthesized for foreign-format projects (SKILL.md,
      # agent-frontmatter) that have no staff.json of their own — cached
      # here, never inside repo_dir (which stays a read-only symlink).
      local generated_dir="$source_dir/generated"
      [ -d "$generated_dir" ] || continue

      local generated_manifest
      while IFS= read -r generated_manifest; do
        [ -n "$generated_manifest" ] || continue
        local generated_project_dir="${generated_manifest%/staff.json}"
        local rel_path="${generated_project_dir#$STAFF_ROOT/}"
        add_registry_entry "$generated_manifest" "$rel_path" "true" "$source_name"
      done < <(find "$generated_dir" -name staff.json)
    done
  }

  scan_local_projects
  scan_sourced_projects

  if [ "$rebuild_errors" -gt 0 ]; then
    error "Registry NOT rebuilt — $rebuild_errors unresolvable source(s); existing registry.json left untouched"
    error "Restore the missing path, or drop the bundle: staff remove_source <name>"
    return 1
  fi

  # Two projects answering to one name makes `staff install <name>` ambiguous:
  # find_project returns both and the caller builds a nonsense path from them.
  local dupes
  dupes=$(echo "$projects" | jq -r '
    group_by(.name)[] | select(length > 1)
    | "  " + .[0].name + ": " + ([.[].path] | join(", "))
  ')
  if [ -n "$dupes" ]; then
    error "Registry NOT rebuilt — duplicate project name(s):"
    printf '%s\n' "$dupes" >&2
    error "Rename one of them, or drop the source that introduced it"
    return 1
  fi

  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local local_projects sourced_projects local_count sourced_count
  local_projects=$(echo "$projects" | jq '[.[] | select(.sourced == false)]')
  sourced_projects=$(echo "$projects" | jq '[.[] | select(.sourced == true)]')
  local_count=$(echo "$local_projects" | jq 'length')
  sourced_count=$(echo "$sourced_projects" | jq 'length')

  jq -n --argjson projects "$local_projects" --arg ts "$timestamp" '{
    version: 1,
    generated_at: $ts,
    projects: $projects
  }' > "$STAFF_REGISTRY"

  # Sourced projects point at absolute, machine-local paths, so their index
  # lives under the gitignored sources/ rather than in the committed registry.
  if [ -d "$STAFF_ROOT/sources" ] || [ "$sourced_count" -gt 0 ]; then
    mkdir -p "$STAFF_ROOT/sources"
    jq -n --argjson projects "$sourced_projects" --arg ts "$timestamp" '{
      version: 1,
      generated_at: $ts,
      projects: $projects
    }' > "$STAFF_SOURCE_REGISTRY"
  fi

  if [ "$sourced_count" -gt 0 ]; then
    ok "Registry rebuilt: $local_count local + $sourced_count sourced project(s) indexed"
  else
    ok "Registry rebuilt: $count project(s) indexed"
  fi
}
