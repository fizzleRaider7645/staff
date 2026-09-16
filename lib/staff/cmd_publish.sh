#!/usr/bin/env bash

# staff publish — export a project as a Claude Code plugin.
#
# staff is the inner loop: a project lives in its category directory and
# `staff install` wires the working copy straight into ~/.claude, so edits show
# up live. A plugin is the exit path: a self-contained snapshot in the layout
# Claude Code's plugin loader expects, listed in a marketplace.json so anyone
# can `/plugin marketplace add` this repo and install from it.
#
# The snapshot is a copy, not a link. The plugin installer copies the plugin
# directory out of a marketplace clone, so anything that points outside the
# directory breaks there. Symlinks are dereferenced for the same reason.

PLUGIN_SCHEMA_URL="https://anthropic.com/claude-code/marketplace.schema.json"

# What a plugin should never carry: VCS metadata, dependency trees, caches and
# state that a fresh checkout regenerates. Matched at any depth.
PUBLISH_EXCLUDES=".git node_modules __pycache__ .pytest_cache .mypy_cache .ruff_cache .venv venv *.egg-info .sdlc .DS_Store"

cmd_publish() {
  local project_name="" out_dir="" marketplace_name="" allow_build="false"

  while [ $# -gt 0 ]; do
    case "$1" in
      --out)         [ -n "${2:-}" ] || { error "Option --out requires a value"; return 1; }
                     out_dir="$2"; shift 2 ;;
      --marketplace) [ -n "${2:-}" ] || { error "Option --marketplace requires a value"; return 1; }
                     marketplace_name="$2"; shift 2 ;;
      --allow-build) allow_build="true"; shift ;;
      -h|--help)
        cat <<HELP
${BOLD}staff publish${RESET} — export a project as a Claude Code plugin

${BOLD}Usage:${RESET}
  staff publish <project> [options]

Writes a self-contained plugin to plugins/<project>/ and lists it in
.claude-plugin/marketplace.json, so the repo doubles as a plugin marketplace:

  claude plugin marketplace add <repo path or GitHub owner/repo>
  claude plugin install <project>@<marketplace>

${BOLD}Options:${RESET}
  --out DIR           Marketplace root to publish into (default: this repo)
  --marketplace NAME  Marketplace name when creating marketplace.json
                      (default: the root directory's name)
  --allow-build       Permit running a build command declared by a sourced
                      (external) project. Refused by default.
  -h, --help          Show this help

${BOLD}What each install type becomes:${RESET}
  skill    plugins/<name>/skills/<name>/          the whole skill directory
  agent    plugins/<name>/agents/<name>.md
  mcp      plugins/<name>/.mcp.json + the project  \${PROJECT_ROOT} becomes
                                                  \${CLAUDE_PLUGIN_ROOT}
  tool     plugins/<name>/ + skills/<name>/       the project, behind a skill
                                                  from its skill/SKILL.md

Re-running replaces the previous snapshot. The plugin's version is the
project's staff.json version, so bump that to ship a change. Only the plugin's
own entry in marketplace.json is rewritten; the marketplace's name, description
and owner are yours to edit in place.

HELP
        return 0
        ;;
      -*)
        error "Unknown option: $1"
        return 1
        ;;
      *)
        if [ -n "$project_name" ]; then
          error "Unexpected argument: $1"
          return 1
        fi
        project_name="$1"
        shift
        ;;
    esac
  done

  if [ -z "$project_name" ]; then
    error "Usage: staff publish <project> [--out DIR] [--marketplace NAME]"
    return 1
  fi

  require_jq
  command -v tar >/dev/null 2>&1 || die "tar is required to publish"

  local project_info
  project_info=$(find_project "$project_name") || return 1

  local project_path sourced
  project_path=$(echo "$project_info" | jq -r '.path')
  sourced=$(echo "$project_info" | jq -r '.sourced // false')

  local abs_project_path="$STAFF_ROOT/$project_path"
  local manifest="$abs_project_path/staff.json"
  [ -f "$manifest" ] || die "No staff.json found at $manifest"

  local name version description install_type content_root
  name=$(jq -r '.name' "$manifest")
  version=$(jq -r '.version // "0.1.0"' "$manifest")
  description=$(jq -r '.description // ""' "$manifest")
  install_type=$(jq -r '.install.type // ""' "$manifest")
  content_root=$(jq -r '.content_root // empty' "$manifest")
  local src_root="${content_root:-$abs_project_path}"

  # The plugin loader is strict about both of these, and a plugin it refuses
  # to load is worse than no plugin.
  if ! printf '%s' "$name" | grep -qE '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'; then
    die "'$name' is not a valid plugin name — use kebab-case (lowercase letters, digits, hyphens)"
  fi
  if ! printf '%s' "$version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$'; then
    die "version '$version' in $manifest is not semantic (MAJOR.MINOR.PATCH)"
  fi
  if [ -z "$description" ]; then
    warn "$name has no description — the marketplace listing will be blank"
  fi

  case "$install_type" in
    skill|agent|mcp|tool) ;;
    "") die "$manifest has no install.type" ;;
    *)  die "install.type '$install_type' has no plugin equivalent — plugins carry skills, agents, commands, hooks and MCP servers" ;;
  esac

  # Resolve the marketplace root
  out_dir="${out_dir:-$STAFF_ROOT}"
  mkdir -p "$out_dir" || die "Cannot create $out_dir"
  out_dir="$(cd "$out_dir" && pwd)"

  if [ -z "$marketplace_name" ]; then
    marketplace_name="$(basename "$out_dir")"
  fi
  if ! printf '%s' "$marketplace_name" | grep -qE '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'; then
    die "'$marketplace_name' is not a valid marketplace name — pass --marketplace <kebab-case-name>"
  fi

  local plugins_root="$out_dir/plugins"
  local plugin_dir="$plugins_root/$name"
  mkdir -p "$plugins_root"

  # Assemble in a staging directory beside the target, then swap, so a failed
  # publish never leaves a half-written plugin where the loader will find it.
  local stage
  stage=$(mktemp -d "$plugins_root/.$name.XXXXXX") || die "Cannot create staging directory in $plugins_root"

  if ! publish_stage "$install_type" "$src_root" "$stage" "$name" "$manifest" "$sourced" "$allow_build"; then
    rm -rf "$stage"
    return 1
  fi

  publish_write_plugin_manifest "$stage" "$manifest" "$name" "$version" "$description" "$project_path" "$sourced"

  # Nothing may point outside the plugin; the installer copies the directory
  # elsewhere and a link would dangle there.
  local stray
  stray=$(find "$stage" -type l | head -1)
  if [ -n "$stray" ]; then
    rm -rf "$stage"
    die "Refusing to publish a symlink: ${stray#$stage/}"
  fi

  chmod 755 "$stage"
  rm -rf "$plugin_dir"
  mv "$stage" "$plugin_dir"

  if ! publish_update_marketplace "$out_dir" "$marketplace_name" "$plugin_dir/.claude-plugin/plugin.json"; then
    return 1
  fi

  ok "Published $name v$version -> ${plugin_dir#$out_dir/}"
  ok "Listed as $name@$marketplace_name in ${out_dir}/.claude-plugin/marketplace.json"

  publish_warn_ignored "$out_dir" "$plugin_dir"

  local status=0
  publish_validate "$plugin_dir" || status=1

  local repo_url
  repo_url=$(publish_repo_url "$out_dir")
  printf '\n'
  info "Install locally:  claude plugin marketplace add $out_dir && claude plugin install $name@$marketplace_name"
  if [ -n "$repo_url" ]; then
    info "From GitHub:      /plugin marketplace add ${repo_url#https://github.com/}   (after pushing)"
  fi

  return $status
}

# ---------------------------------------------------------------------------
# Staging: lay the project out the way the plugin loader expects
# ---------------------------------------------------------------------------

publish_stage() {
  local install_type="$1" src="$2" stage="$3" name="$4" manifest="$5" sourced="$6" allow_build="$7"
  case "$install_type" in
    skill) publish_stage_skill "$src" "$stage" "$name" "$manifest" ;;
    agent) publish_stage_agent "$src" "$stage" "$name" "$manifest" ;;
    mcp)   publish_stage_mcp   "$src" "$stage" "$name" "$manifest" "$sourced" "$allow_build" ;;
    tool)  publish_stage_tool  "$src" "$stage" "$name" "$manifest" "$sourced" "$allow_build" ;;
  esac
}

# Copy a project tree into place, following symlinks and leaving out
# PUBLISH_EXCLUDES. tar rather than cp: the excludes are applied on the way
# in, so a node_modules tree is never copied only to be deleted.
publish_copy_tree() {
  local src="$1" dst="$2"
  local excludes=() pat
  for pat in $PUBLISH_EXCLUDES; do
    excludes+=("--exclude=$pat")
  done
  mkdir -p "$dst" || return 1
  if ! tar -C "$src" --dereference "${excludes[@]}" -cf - . | tar -C "$dst" -xf -; then
    error "Failed to copy $src"
    return 1
  fi
}

publish_stage_skill() {
  local src="$1" stage="$2" name="$3" manifest="$4"

  local skill_file
  skill_file=$(jq -r '.install.skill_file // "SKILL.md"' "$manifest")

  if [ ! -f "$src/$skill_file" ]; then
    error "Skill file not found: $src/$skill_file"
    return 1
  fi
  if [ "$skill_file" != "SKILL.md" ]; then
    error "$name declares install.skill_file=$skill_file, but a plugin skill must be named SKILL.md"
    return 1
  fi

  # The whole directory: a skill's SKILL.md routinely says "read
  # reference/foo.md", and a skill published without its references is
  # silently broken.
  publish_copy_tree "$src" "$stage/skills/$name"
}

publish_stage_agent() {
  local src="$1" stage="$2" name="$3" manifest="$4"

  local agent_file
  agent_file=$(jq -r '.install.agent_file // "agent.md"' "$manifest")

  if [ ! -f "$src/$agent_file" ]; then
    error "Agent file not found: $src/$agent_file"
    return 1
  fi

  # Named after the project, as install does: every agent template ships an
  # agent.md, and two plugins each exporting agents/agent.md would collide.
  mkdir -p "$stage/agents" || return 1
  cp "$src/$agent_file" "$stage/agents/$name.md" || return 1
  [ -f "$src/README.md" ] && cp "$src/README.md" "$stage/README.md"
  return 0
}

publish_stage_mcp() {
  local src="$1" stage="$2" name="$3" manifest="$4" sourced="$5" allow_build="$6"

  if ! jq -e '.install.mcp_config | type == "object"' "$manifest" >/dev/null 2>&1; then
    error "$name has no install.mcp_config to publish"
    return 1
  fi

  publish_build_first "$src" "$manifest" "$name" "$sourced" "$allow_build" || return 1
  publish_copy_tree "$src" "$stage" || return 1

  # ${PROJECT_ROOT} is where staff install substitutes the checkout path;
  # inside a plugin the loader provides ${CLAUDE_PLUGIN_ROOT} instead.
  local cfg
  cfg=$(mcp_config_resolved "$manifest" '${CLAUDE_PLUGIN_ROOT}') || return 1
  jq -n --arg name "$name" --argjson cfg "$cfg" '{ mcpServers: { ($name): $cfg } }' > "$stage/.mcp.json" || return 1

  # A server may ship a skill that teaches Claude when to reach for its tools.
  publish_move_skill_dir "$stage" "$name" || true
  return 0
}

# A project's skill/SKILL.md becomes skills/<name>/ in the plugin. Returns 1
# when the project has none, so callers can fall back or carry on.
publish_move_skill_dir() {
  local stage="$1" name="$2"
  if [ -f "$stage/skill/SKILL.md" ]; then
    mkdir -p "$stage/skills" && mv "$stage/skill" "$stage/skills/$name"
    return $?
  fi
  if [ -f "$stage/SKILL.md" ]; then
    mkdir -p "$stage/skills/$name" && mv "$stage/SKILL.md" "$stage/skills/$name/SKILL.md"
    return $?
  fi
  return 1
}

publish_stage_tool() {
  local src="$1" stage="$2" name="$3" manifest="$4" sourced="$5" allow_build="$6"

  local binary
  binary=$(jq -r '.install.binary // ""' "$manifest")
  if [ -z "$binary" ]; then
    error "No binary specified in staff.json install.binary"
    return 1
  fi
  if [ ! -f "$src/$binary" ]; then
    error "Binary not found: $src/$binary"
    return 1
  fi

  publish_build_first "$src" "$manifest" "$name" "$sourced" "$allow_build" || return 1
  publish_copy_tree "$src" "$stage" || return 1

  if [ ! -x "$stage/$binary" ]; then
    warn "$binary is not executable — the published skill's invocation will fail. chmod +x it and republish."
  fi

  # A tool is a CLI, and plugins have no such component. It ships behind a
  # skill that tells Claude when to reach for it and how to run it from
  # ${CLAUDE_PLUGIN_ROOT}. The project owns that skill (skill/SKILL.md);
  # publish only falls back to a generated one.
  if ! publish_move_skill_dir "$stage" "$name"; then
    warn "$name has no skill/SKILL.md — generating a minimal one. Write skill/SKILL.md in the project to control when Claude uses the tool."
    publish_generate_tool_skill "$stage/skills/$name" "$name" "$binary" "$manifest" || return 1
  fi
}

publish_generate_tool_skill() {
  local skill_dir="$1" name="$2" binary="$3" manifest="$4"
  local description
  description=$(jq -r '.description // ""' "$manifest")
  [ -n "$description" ] || description="Runs the $name command-line tool."

  mkdir -p "$skill_dir" || return 1
  cat > "$skill_dir/SKILL.md" <<SKILL
---
name: $name
description: $description Use when the user asks for $name or for what it does.
---

# $name

$description

Run it from the plugin directory:

\`\`\`bash
\${CLAUDE_PLUGIN_ROOT}/$binary --help
\`\`\`

Read the README in the plugin root before the first use.
SKILL
}

# Same trust gate as install: a sourced project's build command was written
# by a third party and runs only on explicit opt-in.
publish_build_first() {
  local src="$1" manifest="$2" name="$3" sourced="$4" allow_build="$5"

  local build_first
  build_first=$(jq -r '.install.build_first // false' "$manifest")
  [ "$build_first" = "true" ] || return 0

  local build_cmd
  build_cmd=$(jq -r '.build.command // ""' "$manifest")
  [ -n "$build_cmd" ] || return 0

  info "Building $name before publishing..."
  run_manifest_command "$build_cmd" "$src" "$sourced" "$allow_build" "$name" "build" "--allow-build" \
    || { error "Build failed"; return 1; }
}

# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

# The project's page on GitHub, when the repo's origin lives there. Anything
# else yields nothing and the field is left out.
publish_repo_url() {
  local root="$1"
  local url
  url=$(git -C "$root" remote get-url origin 2>/dev/null) || return 0
  case "$url" in
    git@github.com:*)      url="https://github.com/${url#git@github.com:}" ;;
    ssh://git@github.com/*) url="https://github.com/${url#ssh://git@github.com/}" ;;
    https://github.com/*)   ;;
    *) return 0 ;;
  esac
  url="${url%/}"
  url="${url%.git}"
  printf '%s\n' "$url"
}

publish_write_plugin_manifest() {
  local stage="$1" manifest="$2" name="$3" version="$4" description="$5" project_path="$6" sourced="$7"

  # Fields the project sets in staff.json win over anything derived here.
  local author_json
  author_json=$(jq -c '.author // empty' "$manifest")
  if [ -z "$author_json" ]; then
    local git_name
    git_name=$(git config user.name 2>/dev/null || true)
    [ -n "$git_name" ] && author_json=$(jq -n --arg n "$git_name" '{name: $n}')
  fi

  local repo_url="" homepage=""
  repo_url=$(jq -r '.repository // ""' "$manifest")
  homepage=$(jq -r '.homepage // ""' "$manifest")
  if [ -z "$repo_url" ]; then
    repo_url=$(publish_repo_url "$STAFF_ROOT")
  fi
  # A sourced project's path runs through sources/, which is not in this repo.
  if [ -z "$homepage" ] && [ -n "$repo_url" ] && [ "$sourced" != "true" ]; then
    local branch
    branch=$(git -C "$STAFF_ROOT" symbolic-ref --short HEAD 2>/dev/null || echo main)
    homepage="$repo_url/tree/$branch/$project_path"
  fi

  mkdir -p "$stage/.claude-plugin"
  jq -n \
    --arg name "$name" \
    --arg version "$version" \
    --arg desc "$description" \
    --argjson author "${author_json:-null}" \
    --arg homepage "$homepage" \
    --arg repo "$repo_url" \
    --arg license "$(jq -r '.license // ""' "$manifest")" \
    --argjson keywords "$(jq -c '.tags // []' "$manifest")" '
    { name: $name, version: $version, description: $desc }
    + (if $author != null then { author: $author } else {} end)
    + (if $homepage != "" then { homepage: $homepage } else {} end)
    + (if $repo != "" then { repository: $repo } else {} end)
    + (if $license != "" then { license: $license } else {} end)
    + (if ($keywords | length) > 0 then { keywords: $keywords } else {} end)
  ' > "$stage/.claude-plugin/plugin.json"
}

# Create or update <out>/.claude-plugin/marketplace.json. An existing entry
# for the plugin is updated in place and keeps any fields added by hand
# (category, tags); a new one is appended.
publish_update_marketplace() {
  local out_dir="$1" marketplace_name="$2" plugin_manifest="$3"

  local mk_dir="$out_dir/.claude-plugin"
  local mk_file="$mk_dir/marketplace.json"
  mkdir -p "$mk_dir"

  if [ ! -f "$mk_file" ]; then
    local owner
    owner=$(git config user.name 2>/dev/null || true)
    [ -n "$owner" ] || owner="$(id -un)"
    # Top-level fields are written once and never touched again, so the
    # description and owner can be edited by hand and survive every publish.
    jq -n --arg schema "$PLUGIN_SCHEMA_URL" --arg name "$marketplace_name" --arg owner "$owner" \
      --arg desc "Plugins published from the $marketplace_name repository with staff publish" '
      { "$schema": $schema, name: $name, description: $desc, owner: { name: $owner }, plugins: [] }
    ' > "$mk_file"
    info "Created marketplace '$marketplace_name' at $mk_file — edit its description and owner there"
  elif ! jq -e . "$mk_file" >/dev/null 2>&1; then
    error "Not valid JSON, refusing to modify: $mk_file"
    return 1
  else
    local existing_name
    existing_name=$(jq -r '.name // ""' "$mk_file")
    if [ -n "$existing_name" ] && [ "$existing_name" != "$marketplace_name" ]; then
      # Renaming a marketplace strands everyone who installed from it under
      # the old name, so that is never done as a side effect.
      error "$mk_file already names this marketplace '$existing_name' (you passed '$marketplace_name')"
      error "Drop --marketplace to keep the existing name"
      return 1
    fi
  fi

  local entry
  entry=$(jq -c '
    { name, description, version, source: ("./plugins/" + .name) }
    + (if .author   then { author }   else {} end)
    + (if .homepage then { homepage } else {} end)
    + (if .keywords then { keywords } else {} end)
  ' "$plugin_manifest")

  jq --argjson entry "$entry" '
    .plugins = (.plugins // [])
    | if any(.plugins[]; .name == $entry.name)
      then .plugins |= map(if .name == $entry.name then . + $entry else . end)
      else .plugins += [$entry]
      end
  ' "$mk_file" > "$mk_file.tmp" && mv "$mk_file.tmp" "$mk_file"
}

# ---------------------------------------------------------------------------
# Checks on the artifact
# ---------------------------------------------------------------------------

# A plugin is distributed by cloning the marketplace repo. Anything under it
# that .gitignore hides never reaches the clone — dist/ is the classic case.
publish_warn_ignored() {
  local out_dir="$1" plugin_dir="$2"
  git -C "$out_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

  local ignored count
  ignored=$(git -C "$out_dir" ls-files --others --ignored --exclude-standard -- "$plugin_dir" 2>/dev/null)
  [ -n "$ignored" ] || return 0
  count=$(printf '%s\n' "$ignored" | wc -l | tr -d ' ')

  warn "$count file(s) in ${plugin_dir#$out_dir/} are ignored by .gitignore and will be missing from a clone of this marketplace:"
  printf '%s\n' "$ignored" | head -5 | sed 's/^/        /' >&2
  [ "$count" -gt 5 ] && printf '        ...\n' >&2
  warn "Add a negating rule (e.g. '!plugins/**/dist/') or change what the plugin needs at runtime"
  return 0
}

# Run the loader's own validator when it is available. It is the authority on
# what loads; everything above is a best effort at producing what it accepts.
publish_validate() {
  local plugin_dir="$1"

  if ! command -v claude >/dev/null 2>&1; then
    info "claude CLI not on PATH — skipped 'claude plugin validate'"
    return 0
  fi

  local report
  if report=$(claude plugin validate "$plugin_dir" 2>&1); then
    ok "claude plugin validate: passed"
    return 0
  fi
  error "claude plugin validate found problems:"
  printf '%s\n' "$report" | sed 's/^/        /' >&2
  return 1
}
