#!/usr/bin/env bash

cmd_uninstall() {
  local project_name=""

  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help)
        cat <<EOF
${BOLD}staff uninstall${RESET} — remove an installed project

${BOLD}Usage:${RESET}
  staff uninstall <project>

Reverses the installation by removing symlinks, config entries, or wrapper scripts.

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
    error "Usage: staff uninstall <project>"
    return 1
  fi

  require_jq
  ensure_state_dir

  local entry
  entry=$(jq -r --arg name "$project_name" '
    .installations[] | select(.project == $name)
  ' "$STAFF_INSTALLED")

  if [ -z "$entry" ]; then
    die "Project '$project_name' is not installed"
  fi

  local category
  category=$(echo "$entry" | jq -r '.category')

  # Remove symlinks
  echo "$entry" | jq -r '.symlinks[]? // empty' | while read -r symlink; do
    if [ -L "$symlink" ] || [ -f "$symlink" ]; then
      rm -f "$symlink"
      info "Removed: $symlink"
    fi
  done

  # Remove parent directory if empty (for skills/agents)
  if [ "$category" = "skill" ] || [ "$category" = "agent" ]; then
    local target
    target=$(echo "$entry" | jq -r '.target')
    if [ -d "$target" ] && [ -z "$(ls -A "$target" 2>/dev/null)" ]; then
      rmdir "$target"
      info "Removed empty directory: $target"
    fi
  fi

  # Remove config keys (for MCPs)
  echo "$entry" | jq -r '.config_keys[]? // empty' | while read -r config_key; do
    local settings_target
    settings_target=$(echo "$entry" | jq -r '.target')
    if [ -f "$settings_target" ]; then
      backup_config "$settings_target"
      local key_name="${config_key#mcpServers.}"
      jq --arg key "$key_name" 'del(.mcpServers[$key])' "$settings_target" > "${settings_target}.tmp" \
        && mv "${settings_target}.tmp" "$settings_target"
      info "Removed config key: $config_key from $settings_target"
    fi
  done

  # Remove from tracking
  jq --arg name "$project_name" '
    .installations = [.installations[] | select(.project != $name)]
  ' "$STAFF_INSTALLED" > "${STAFF_INSTALLED}.tmp" && mv "${STAFF_INSTALLED}.tmp" "$STAFF_INSTALLED"

  ok "Uninstalled '$project_name'"
}
