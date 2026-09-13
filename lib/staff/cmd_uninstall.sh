#!/usr/bin/env bash

cmd_uninstall() {
  local project_name="" scope=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --scope) scope="$2"; shift 2 ;;
      -h|--help)
        cat <<EOF
${BOLD}staff uninstall${RESET} — remove an installed project

${BOLD}Usage:${RESET}
  staff uninstall <project> [--scope user|project]

Reverses the installation by removing symlinks, config entries, or wrapper
scripts. Without --scope, every scope the project is installed at is removed.

EOF
        return 0
        ;;
      -*)
        error "Unknown option: $1"
        return 1
        ;;
      *)
        project_name="$1"
        shift
        ;;
    esac
  done

  if [ -z "$project_name" ]; then
    error "Usage: staff uninstall <project> [--scope user|project]"
    return 1
  fi

  if [ -n "$scope" ]; then
    case "$scope" in
      user|project) ;;
      *) error "Invalid scope: $scope (must be user or project)"; return 1 ;;
    esac
  fi

  require_jq
  ensure_state_dir

  # A project may be installed at more than one scope; each is its own record.
  local entries
  entries=$(jq -c --arg name "$project_name" --arg scope "$scope" '
    .installations[]
    | select(.project == $name)
    | select($scope == "" or .scope == $scope)
  ' "$STAFF_INSTALLED")

  if [ -z "$entries" ]; then
    if [ -n "$scope" ]; then
      die "Project '$project_name' is not installed at $scope scope"
    fi
    die "Project '$project_name' is not installed"
  fi

  local entry
  while IFS= read -r entry; do
    [ -n "$entry" ] || continue
    uninstall_entry "$entry"
  done <<< "$entries"

  # Drop the records we just acted on
  jq --arg name "$project_name" --arg scope "$scope" '
    .installations = [
      .installations[]
      | select((.project != $name) or ($scope != "" and .scope != $scope))
    ]
  ' "$STAFF_INSTALLED" > "${STAFF_INSTALLED}.tmp" && mv "${STAFF_INSTALLED}.tmp" "$STAFF_INSTALLED"

  ok "Uninstalled '$project_name'"
}

# Reverse a single installation record.
uninstall_entry() {
  local entry="$1"

  local category target
  category=$(echo "$entry" | jq -r '.category')
  target=$(echo "$entry" | jq -r '.target')

  # Remove symlinks
  local symlink
  while IFS= read -r symlink; do
    [ -n "$symlink" ] || continue
    if [ -L "$symlink" ] || [ -f "$symlink" ]; then
      rm -f "$symlink"
      info "Removed: $symlink"
    fi
  done < <(echo "$entry" | jq -r '.symlinks[]? // empty')

  # Remove the containing directory only if nothing else lives there.
  # A skill installs as a symlink to its own directory, so there is nothing
  # left to tidy once that link is gone — this is for the shared agents dir.
  if [ "$category" = "skill" ] || [ "$category" = "agent" ]; then
    if [ -d "$target" ] && [ ! -L "$target" ] && [ -z "$(ls -A "$target" 2>/dev/null)" ]; then
      rmdir "$target"
      info "Removed empty directory: $target"
    fi
  fi

  # Remove config keys (MCP servers)
  local config_key
  while IFS= read -r config_key; do
    [ -n "$config_key" ] || continue
    if [ -f "$target" ]; then
      backup_config "$target"
      local key_name="${config_key#mcpServers.}"
      jq --arg key "$key_name" 'del(.mcpServers[$key])' "$target" > "${target}.tmp" \
        && mv "${target}.tmp" "$target"
      info "Removed config key: $config_key from $target"
    fi
  done < <(echo "$entry" | jq -r '.config_keys[]? // empty')
}
