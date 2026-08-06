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

      local entry
      entry=$(jq --arg path "$rel_path" '{
        name: .name,
        category: .category,
        language: .language,
        description: .description,
        status: .status,
        path: $path,
        tags: (.tags // []),
        version: (.version // "0.0.0")
      }' "$manifest") || {
        warn "Failed to parse $manifest — skipping"
        continue
      }

      projects=$(echo "$projects" | jq --argjson entry "$entry" '. + [$entry]')
      count=$((count + 1))
    done
  done

  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  jq -n --argjson projects "$projects" --arg ts "$timestamp" '{
    version: 1,
    generated_at: $ts,
    projects: $projects
  }' > "$STAFF_REGISTRY"

  ok "Registry rebuilt: $count project(s) indexed"
}
