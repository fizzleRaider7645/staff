#!/usr/bin/env bash

cmd_install() {
  local project_name="" scope="user" allow_build="false"

  while [ $# -gt 0 ]; do
    case "$1" in
      --scope)       scope="$2";  shift 2 ;;
      --allow-build) allow_build="true"; shift ;;
      -h|--help)
        cat <<EOF
${BOLD}staff install${RESET} — install/wire up a project

${BOLD}Usage:${RESET}
  staff install <project> [options]

${BOLD}Options:${RESET}
  --scope user|project   Where to install (default: user)
                         user: ~/.claude/ (global)
                         project: ./.claude/ (current directory)
  --allow-build          Permit running a build command declared by a sourced
                         (external) project. Refused by default.
  -h, --help             Show this help

${BOLD}What happens by category:${RESET}
  skill    Symlinks into ~/.claude/skills/ (or .claude/skills/)
  mcp      Adds an mcpServers entry to ~/.claude.json (user)
           or .mcp.json in the current directory (project)
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

  local project_path
  project_path=$(echo "$project_info" | jq -r '.path')

  # Consulted by install_mcp / install_tool before running build.command,
  # which for a sourced project was authored by a third party.
  STAFF_PROJECT_SOURCED=$(echo "$project_info" | jq -r '.sourced // false')
  STAFF_ALLOW_BUILD="$allow_build"

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

  local skills_dir
  if [ "$scope" = "user" ]; then
    skills_dir="$HOME/.claude/skills"
  else
    skills_dir="$(pwd)/.claude/skills"
  fi
  local link_path="$skills_dir/$name"

  local source_file="$project_path/$skill_file"
  if [ ! -f "$source_file" ]; then
    die "Skill file not found: $source_file"
  fi

  if [ "$skill_file" != "SKILL.md" ]; then
    warn "$name declares install.skill_file=$skill_file; Claude Code looks for SKILL.md"
  fi

  mkdir -p "$skills_dir"
  replace_install_target "$link_path" "$name" || return 1

  # Link the whole skill directory, not just SKILL.md. Most skills carry
  # scripts, references and templates alongside it, and a skill whose
  # SKILL.md says "read shared/foo.md" is silently broken without them.
  # Linking the directory also means files added upstream appear with no
  # reinstall.
  ln -s "$project_path" "$link_path"
  record_installation "$name" "skill" "$scope" "$link_path" "$link_path"
  ok "Installed skill '$name' -> $link_path"
}

# Clear the way for a new install link. Replaces a previous symlink outright;
# removes a real directory only when staff recorded installing this project
# there, so a hand-made skill directory is never silently destroyed.
replace_install_target() {
  local link_path="$1" name="$2"

  if [ -L "$link_path" ]; then
    rm -f "$link_path"
    return 0
  fi

  if [ -e "$link_path" ]; then
    local known
    known=$(jq -r --arg name "$name" --arg t "$link_path" '
      [.installations[] | select(.project == $name) | select(.target == $t or (.symlinks[]? | startswith($t + "/")))] | length
    ' "$STAFF_INSTALLED" 2>/dev/null || echo 0)

    if [ "${known:-0}" -gt 0 ]; then
      rm -rf "$link_path"
      return 0
    fi

    error "Refusing to replace $link_path — it exists and staff did not create it"
    error "Move it aside and re-run, or remove it yourself"
    return 1
  fi

  return 0
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
      run_manifest_command "$build_cmd" "$project_path" \
        "${STAFF_PROJECT_SOURCED:-false}" "${STAFF_ALLOW_BUILD:-false}" "$name" \
        "build" "--allow-build" \
        || die "Build failed"
    fi
  fi

  # Claude Code resolves MCP servers from ~/.claude.json (user scope) and
  # .mcp.json at the project root (project scope). settings.json only carries
  # enable/disable toggles, so definitions written there are ignored.
  local config_file
  if [ "$scope" = "user" ]; then
    config_file="$HOME/.claude.json"
  else
    config_file="$(pwd)/.mcp.json"
  fi

  mkdir -p "$(dirname "$config_file")"

  if [ ! -f "$config_file" ]; then
    echo '{}' > "$config_file"
  fi

  if ! jq -e . "$config_file" >/dev/null 2>&1; then
    die "Not valid JSON, refusing to modify: $config_file"
  fi

  backup_config "$config_file"

  # Build MCP config with resolved paths
  local mcp_config
  mcp_config=$(jq --arg root "$project_path" '
    .install.mcp_config |
    .args = (.args // [] | map(gsub("\\$\\{PROJECT_ROOT\\}"; $root)))
  ' "$manifest")

  jq --arg name "$name" --argjson config "$mcp_config" '
    .mcpServers[$name] = $config
  ' "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"

  record_installation "$name" "mcp" "$scope" "$config_file" "" "mcpServers.$name"
  ok "Installed MCP '$name' into $config_file"
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

  # The link is named after the project, not after agent_file. Every staff
  # agent template ships an "agent.md", so linking by source filename made
  # each install clobber the previous one.
  local link_path="$target_dir/$name.md"

  ln -sf "$source_file" "$link_path"
  record_installation "$name" "agent" "$scope" "$target_dir" "$link_path"
  ok "Installed agent '$name' -> $link_path"
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
      run_manifest_command "$build_cmd" "$project_path" \
        "${STAFF_PROJECT_SOURCED:-false}" "${STAFF_ALLOW_BUILD:-false}" "$name" \
        "build" "--allow-build" \
        || die "Build failed"
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

  # Replace any existing entry for this project *at this scope*. Keying on
  # the project alone meant a user-scope install followed by a project-scope
  # one lost the first record, orphaning whatever it had written.
  jq --arg name "$name" --arg scope "$scope" --argjson entry "$entry" '
    .installations = ([.installations[] | select(.project != $name or .scope != $scope)] + [$entry])
  ' "$STAFF_INSTALLED" > "${STAFF_INSTALLED}.tmp" && mv "${STAFF_INSTALLED}.tmp" "$STAFF_INSTALLED"
}
