#!/usr/bin/env bash

cmd_init() {
  local category="" name="" lang=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --lang)  lang="$2"; shift 2 ;;
      -h|--help)
        cat <<EOF
${BOLD}staff init${RESET} — scaffold a new project from a template

${BOLD}Usage:${RESET}
  staff init <category> <name> [--lang ts|python|go|shell|markdown]

${BOLD}Categories:${RESET}
  skill      Claude Code skill (language defaults to markdown)
  mcp        MCP server (language defaults to ts)
  agent      Agent definition (language defaults to markdown)
  tool       Standalone tool (language defaults to ts)
  harness    Orchestration harness (language defaults to ts)
  lib        Shared library (language defaults to ts)

${BOLD}Examples:${RESET}
  staff init skill code-review
  staff init mcp google-drive --lang ts
  staff init tool token-counter --lang python

EOF
        return 0
        ;;
      -*)
        error "Unknown option: $1"
        return 1
        ;;
      *)
        if [ -z "$category" ]; then
          category="$1"
        elif [ -z "$name" ]; then
          name="$1"
        else
          error "Unexpected argument: $1"
          return 1
        fi
        shift
        ;;
    esac
  done

  if [ -z "$category" ] || [ -z "$name" ]; then
    error "Usage: staff init <category> <name> [--lang LANG]"
    return 1
  fi

  if ! echo "$name" | grep -qE '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'; then
    die "Invalid project name: '$name'. Use kebab-case (e.g., my-project)"
  fi

  # Validate category
  local category_dir
  case "$category" in
    skill)   category_dir="skills" ;;
    mcp)     category_dir="mcps" ;;
    agent)   category_dir="agents" ;;
    tool)    category_dir="tools" ;;
    harness) category_dir="harnesses" ;;
    lib)     category_dir="lib" ;;
    *)       die "Unknown category: $category. Use: skill, mcp, agent, tool, harness, lib" ;;
  esac

  # Default language by category
  # Default to a language that actually has a template for the category,
  # otherwise init silently produces a project that cannot be installed.
  if [ -z "$lang" ]; then
    case "$category" in
      skill|agent) lang="markdown" ;;
      tool)        lang="python" ;;
      *)           lang="ts" ;;
    esac
  fi

  # Normalize language aliases
  case "$lang" in
    ts|typescript) lang="typescript" ;;
    py|python)     lang="python" ;;
    go|golang)     lang="go" ;;
    sh|bash|shell) lang="shell" ;;
    md|markdown)   lang="markdown" ;;
    rs|rust)       lang="rust" ;;
    *)             die "Unknown language: $lang" ;;
  esac

  local project_dir="$STAFF_ROOT/$category_dir/$name"

  if [ -d "$project_dir" ]; then
    die "Directory already exists: $project_dir"
  fi

  # Determine template
  local template_name
  case "$category" in
    skill)  template_name="skill" ;;
    agent)  template_name="agent" ;;
    *)
      case "$lang" in
        typescript) template_name="${category}-ts" ;;
        python)     template_name="${category}-python" ;;
        go)         template_name="${category}-go" ;;
        *)          template_name="${category}-${lang}" ;;
      esac
      ;;
  esac

  local template_dir="$STAFF_ROOT/templates/$template_name"

  if [ -d "$template_dir" ]; then
    info "Using template: $template_name"
    scaffold_from_template "$template_dir" "$project_dir" "$name" "$category" "$lang"
  else
    info "No template '$template_name' found — creating minimal project"
    scaffold_minimal "$project_dir" "$name" "$category" "$lang"
  fi

  ok "Created $category '$name' at $category_dir/$name"
  info "Next: cd $category_dir/$name && edit staff.json"
}

scaffold_from_template() {
  local template_dir="$1" project_dir="$2" name="$3" category="$4" lang="$5"

  mkdir -p "$project_dir"

  local author
  author=$(git config user.name 2>/dev/null || echo "")
  local date_str
  date_str=$(date +%Y-%m-%d)
  local name_under="${name//-/_}"

  find "$template_dir" -type f -name "*.tmpl" | while read -r tmpl; do
    local rel="${tmpl#$template_dir/}"
    rel="${rel%.tmpl}"
    # Replace __name__ in paths with the underscored project name
    local dest="$project_dir/${rel//__name__/$name_under}"
    mkdir -p "$(dirname "$dest")"

    sed -e "s|{{NAME}}|$name|g" \
        -e "s|{{NAME_UNDER}}|$name_under|g" \
        -e "s|{{CATEGORY}}|$category|g" \
        -e "s|{{LANGUAGE}}|$lang|g" \
        -e "s|{{DATE}}|$date_str|g" \
        -e "s|{{AUTHOR}}|$author|g" \
        "$tmpl" > "$dest"
    # Carry the executable bit across; a template's bin/ wrapper is useless
    # without it, and install_tool exec's it directly.
    if [ -x "$tmpl" ]; then chmod +x "$dest"; fi
  done

  # Copy non-template files as-is
  find "$template_dir" -type f ! -name "*.tmpl" | while read -r file; do
    local rel="${file#$template_dir/}"
    local dest="$project_dir/${rel//__name__/$name_under}"
    mkdir -p "$(dirname "$dest")"
    cp -p "$file" "$dest"
  done
}

scaffold_minimal() {
  local project_dir="$1" name="$2" category="$3" lang="$4"

  mkdir -p "$project_dir"

  local author
  author=$(git config user.name 2>/dev/null || echo "")
  local date_str
  date_str=$(date +%Y-%m-%d)

  # Create staff.json
  local install_block
  case "$category" in
    skill) install_block='{"type":"skill","skill_file":"SKILL.md"}' ;;
    agent) install_block='{"type":"agent","agent_file":"agent.md"}' ;;
    mcp)   install_block='{"type":"mcp","mcp_config":{"command":"","args":[]}}' ;;
    tool)  install_block='{"type":"tool","binary":"","build_first":true}' ;;
    *)     install_block='{}' ;;
  esac

  jq -n \
    --arg name "$name" \
    --arg lang "$lang" \
    --argjson install "$install_block" \
    '{
      name: $name,
      language: $lang,
      description: "",
      status: "draft",
      version: "0.1.0",
      build: {},
      install: $install,
      tags: []
    }' > "$project_dir/staff.json"

  # Create README
  cat > "$project_dir/README.md" <<EOF
# $name

> TODO: Add description

## Setup

TODO: Add setup instructions

## Usage

TODO: Add usage instructions
EOF

  # Create category-specific starter files
  case "$category" in
    skill)
      cat > "$project_dir/SKILL.md" <<EOF
---
name: $name
description: TODO
---

TODO: Add skill instructions
EOF
      ;;
    agent)
      cat > "$project_dir/agent.md" <<EOF
---
name: $name
description: TODO
---

TODO: Add agent instructions
EOF
      ;;
    mcp|tool|harness|lib)
      mkdir -p "$project_dir/src"
      ;;
  esac
}
