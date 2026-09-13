#!/usr/bin/env bash

cmd_install() {
  local project_name="" scope="user"

  while [ $# -gt 0 ]; do
    case "$1" in
      --scope)   scope="$2";  shift 2 ;;
      -h|--help)
        cat <<EOF
${BOLD}staff install${RESET} — install/wire up a project

${BOLD}Usage:${RESET}
  staff install <project> [options]

${BOLD}Options:${RESET}
  --scope user|project   Where to install (default: user)
                         user: ~/.claude/ (global)
                         project: ./.claude/ (current directory)
  -h, --help             Show this help

${BOLD}What happens by category:${RESET}
  skill    Symlinks into ~/.claude/skills/ (or .claude/skills/)
  mcp      Merges config into Claude Code settings.json mcpServers
  agent    Symlinks into ~/.claude/agents/ (or .claude/agents/)
  tool     Creates a wrapper script in ~/.local/bin/

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
    error "Usage: staff install <project> [--scope user|project]"
    return 1
  fi

  require_jq
  ensure_state_dir

  local project_info
  project_info=$(find_project "$project_name") || return 1

  local project_path category
  project_path=$(echo "$project_info" | jq -r '.path')
  category=$(echo "$project_info" | jq -r '.category')

  local abs_project_path="$STAFF_ROOT/$project_path"
  local manifest="$abs_project_path/staff.json"

  if [ ! -f "$manifest" ]; then
    die "No staff.json found at $manifest"
  fi

  local install_type
  install_type=$(jq -r '.install.type' "$manifest")

  case "$install_type" in
    skill)  install_skill  "$project_name" "$abs_project_path" "$manifest" "$scope" ;;
    mcp)    install_mcp    "$project_name" "$abs_project_path" "$manifest" "$scope" ;;
    agent)  install_agent  "$project_name" "$abs_project_path" "$manifest" "$scope" ;;
    tool)   install_tool   "$project_name" "$abs_project_path" "$manifest" ;;
    *)      die "Unknown install type: $install_type" ;;
  esac
}

install_skill() {
  local name="$1" project_path="$2" manifest="$3" scope="$4"

  local skill_file
  skill_file=$(jq -r '.install.skill_file // "SKILL.md"' "$manifest")

  local content_root
  content_root=$(jq -r '.content_root // empty' "$manifest")
  project_path="${content_root:-$project_path}"

  local target_dir
  if [ "$scope" = "user" ]; then
    target_dir="$HOME/.claude/skills/$name"
  else
    target_dir="$(pwd)/.claude/skills/$name"
  fi

  mkdir -p "$target_dir"

  local source_file="$project_path/$skill_file"
  if [ ! -f "$source_file" ]; then
    die "Skill file not found: $source_file"
  fi

  ln -sf "$source_file" "$target_dir/$skill_file"
  record_installation "$name" "skill" "$scope" "$target_dir" "$target_dir/$skill_file"
  ok "Installed skill '$name' -> $target_dir"
}

install_mcp() {
  local name="$1" project_path="$2" manifest="$3" scope="$4"

  local build_first
  build_first=$(jq -r '.install.build_first // false' "$manifest")

  if [ "$build_first" = "true" ]; then
    info "Building $name before install..."
    local build_cmd
    build_cmd=$(jq -r '.build.command // ""' "$manifest")
    if [ -n "$build_cmd" ]; then
      (cd "$project_path" && eval "$build_cmd") || die "Build failed"
    fi
  fi

  local settings_file
  if [ "$scope" = "user" ]; then
    settings_file="$HOME/.claude/settings.json"
  else
    settings_file="$(pwd)/.claude/settings.json"
  fi

  mkdir -p "$(dirname "$settings_file")"

  if [ ! -f "$settings_file" ]; then
    echo '{}' > "$settings_file"
  fi

  # Back up settings
  cp "$settings_file" "${settings_file}.bak"

  # Build MCP config with resolved paths
  local mcp_config
  mcp_config=$(jq --arg root "$project_path" '
    .install.mcp_config |
    .args = (.args // [] | map(gsub("\\$\\{PROJECT_ROOT\\}"; $root)))
  ' "$manifest")

  # Merge into settings
  jq --arg name "$name" --argjson config "$mcp_config" '
    .mcpServers[$name] = $config
  ' "$settings_file" > "${settings_file}.tmp" && mv "${settings_file}.tmp" "$settings_file"

  record_installation "$name" "mcp" "$scope" "$settings_file" "" "mcpServers.$name"
  ok "Installed MCP '$name' into $settings_file"
}

install_agent() {
  local name="$1" project_path="$2" manifest="$3" scope="$4"

  local agent_file
  agent_file=$(jq -r '.install.agent_file // "agent.md"' "$manifest")

  local content_root
  content_root=$(jq -r '.content_root // empty' "$manifest")
  project_path="${content_root:-$project_path}"

  local target_dir
  if [ "$scope" = "user" ]; then
    target_dir="$HOME/.claude/agents"
  else
    target_dir="$(pwd)/.claude/agents"
  fi

  mkdir -p "$target_dir"

  local source_file="$project_path/$agent_file"
  if [ ! -f "$source_file" ]; then
    die "Agent file not found: $source_file"
  fi

  ln -sf "$source_file" "$target_dir/$agent_file"
  record_installation "$name" "agent" "$scope" "$target_dir" "$target_dir/$agent_file"
  ok "Installed agent '$name' -> $target_dir/$agent_file"
}

install_tool() {
  local name="$1" project_path="$2" manifest="$3"

  local content_root
  content_root=$(jq -r '.content_root // empty' "$manifest")
  project_path="${content_root:-$project_path}"

  local build_first
  build_first=$(jq -r '.install.build_first // false' "$manifest")

  if [ "$build_first" = "true" ]; then
    info "Building $name before install..."
    local build_cmd
    build_cmd=$(jq -r '.build.command // ""' "$manifest")
    if [ -n "$build_cmd" ]; then
      (cd "$project_path" && eval "$build_cmd") || die "Build failed"
    fi
  fi

  local binary
  binary=$(jq -r '.install.binary // ""' "$manifest")

  if [ -z "$binary" ]; then
    die "No binary specified in staff.json install.binary"
  fi

  local bin_dir="$HOME/.local/bin"
  mkdir -p "$bin_dir"

  local wrapper="$bin_dir/$name"
  cat > "$wrapper" <<WRAPPER
#!/bin/sh
exec "$project_path/$binary" "\$@"
WRAPPER
  chmod +x "$wrapper"

  record_installation "$name" "tool" "user" "$bin_dir" "$wrapper"
  ok "Installed tool '$name' -> $wrapper"
}

record_installation() {
  local name="$1" category="$2" scope="$3" target="$4" symlink="${5:-}" config_key="${6:-}"
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local entry
  entry=$(jq -n \
    --arg name "$name" \
    --arg category "$category" \
    --arg scope "$scope" \
    --arg target "$target" \
    --arg symlink "$symlink" \
    --arg config_key "$config_key" \
    --arg ts "$timestamp" \
    '{
      project: $name,
      category: $category,
      scope: $scope,
      target: $target,
      installed_at: $ts,
      symlinks: (if $symlink != "" then [$symlink] else [] end),
      config_keys: (if $config_key != "" then [$config_key] else [] end)
    }')

  # Remove any existing entry for this project, then add new one
  jq --arg name "$name" --argjson entry "$entry" '
    .installations = ([.installations[] | select(.project != $name)] + [$entry])
  ' "$STAFF_INSTALLED" > "${STAFF_INSTALLED}.tmp" && mv "${STAFF_INSTALLED}.tmp" "$STAFF_INSTALLED"
}
