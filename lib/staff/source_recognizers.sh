#!/usr/bin/env bash

# Recognize Claude Code skills (SKILL.md) in a foreign repo that has no
# staff.json. Emits one absolute project directory per line.
recognize_skills() {
  local dir="$1"

  if [ -f "$dir/SKILL.md" ] && [ ! -f "$dir/staff.json" ]; then
    printf '%s\n' "$dir"
  fi

  local project_dir
  for project_dir in "$dir"/skills/*/; do
    [ -d "$project_dir" ] || continue
    project_dir="${project_dir%/}"
    if [ -f "$project_dir/SKILL.md" ] && [ ! -f "$project_dir/staff.json" ]; then
      printf '%s\n' "$project_dir"
    fi
  done
}

# Recognize Claude Code subagents: flat <name>.md files directly under
# agents/, with frontmatter defining both name: and description:.
# Distinct from staff's own agents/<name>/agent.md + staff.json convention,
# which is a directory (not a file) and is handled by the staff.json walk.
recognize_agents() {
  local dir="$1"

  local agent_file
  for agent_file in "$dir"/agents/*.md; do
    [ -f "$agent_file" ] || continue
    if frontmatter_has_name_and_description "$agent_file"; then
      printf '%s\n' "$agent_file"
    fi
  done
}

# Write a synthesized staff.json for a recognized foreign project.
# Echoes the absolute path of the manifest it wrote.
synthesize_manifest() {
  local category="$1" content_root="$2" derived_name="$3" source_name="$4" agent_file="${5:-}"

  local native_format install_json
  case "$category" in
    skill)
      native_format="claude-skill"
      install_json='{"type":"skill"}'
      ;;
    agent)
      native_format="claude-agent"
      install_json=$(jq -n --arg f "$agent_file" '{type:"agent", agent_file:$f}')
      ;;
    *)
      error "synthesize_manifest: unsupported category: $category"
      return 1
      ;;
  esac

  local description
  case "$category" in
    skill) description=$(frontmatter_field "$content_root/SKILL.md" "description") ;;
    agent) description=$(frontmatter_field "$content_root/$agent_file" "description") ;;
  esac

  local manifest_dir="$STAFF_ROOT/sources/$source_name/generated/$category/$derived_name"
  local manifest_path="$manifest_dir/staff.json"

  mkdir -p "$manifest_dir" || {
    error "Failed to create $manifest_dir"
    return 1
  }

  jq -n \
    --arg name "$derived_name" \
    --arg description "$description" \
    --arg content_root "$content_root" \
    --arg native_format "$native_format" \
    --argjson install "$install_json" \
    '{
      name: $name,
      language: "markdown",
      description: $description,
      status: "alpha",
      version: "0.0.0",
      tags: ["sourced", $native_format],
      synthesized: true,
      native_format: $native_format,
      content_root: $content_root,
      install: $install
    }' > "$manifest_path" || {
    error "Failed to write synthesized manifest: $manifest_path"
    return 1
  }

  printf '%s\n' "$manifest_path"
}
