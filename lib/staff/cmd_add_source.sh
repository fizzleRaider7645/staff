#!/usr/bin/env bash

source "$STAFF_ROOT/lib/staff/frontmatter.sh"
source "$STAFF_ROOT/lib/staff/source_recognizers.sh"

cmd_add_source() {
  require_jq

  local source_name="" source_path="" auto_install="true" install_scope="user"

  while [ $# -gt 0 ]; do
    case "$1" in
      --no-install)
        auto_install="false"
        shift
        ;;
      --scope)
        install_scope="$2"
        shift 2
        ;;
      -h|--help)
        cat <<EOF
${BOLD}staff add_source${RESET} — register an external project in sources/

${BOLD}Usage:${RESET}
  staff add_source <repo-name> <path> [options]

${BOLD}Arguments:${RESET}
  repo-name      Local source bundle name under sources/
  path           Path to an external project directory or a source repo root

${BOLD}Options:${RESET}
  --scope user|project   Install scope to use when auto-installing (default: user)
  --no-install           Register the source without installing it
  -h, --help             Show this help

${BOLD}What happens:${RESET}
  1. Discovers one or more staff projects from <path>
  2. Creates sources/<repo-name>/ with repo symlink + source.toml
  3. Rebuilds the registry
  4. Auto-installs discovered projects by default

${BOLD}Examples:${RESET}
  staff add_source github-skill /path/to/external/skills/github-skill
  staff add_source my-mcp ../other-repo/mcps/my-mcp --scope project
  staff add_source planning-agent /path/to/agent --no-install

EOF
        return 0
        ;;
      -*)
        error "Unknown option: $1"
        return 1
        ;;
      *)
        if [ -z "$source_name" ]; then
          source_name="$1"
        elif [ -z "$source_path" ]; then
          source_path="$1"
        else
          error "Too many arguments"
          return 1
        fi
        shift
        ;;
    esac
  done

  if [ -z "$source_name" ] || [ -z "$source_path" ]; then
    error "Usage: staff add_source <repo-name> <path> [--scope user|project] [--no-install]"
    return 1
  fi

  case "$install_scope" in
    user|project) ;;
    *)
      error "Invalid scope: $install_scope (must be user or project)"
      return 1
      ;;
  esac

  if [[ ! "$source_path" = /* ]]; then
    source_path="$(cd "$source_path" 2>/dev/null && pwd)" || {
      error "Cannot resolve path: $source_path"
      return 1
    }
  fi

  if [ ! -d "$source_path" ]; then
    error "Source directory not found: $source_path"
    return 1
  fi

  if ensure_registry >/dev/null 2>&1; then
    source "$STAFF_ROOT/lib/staff/cmd_registry.sh"
    registry_rebuild >/dev/null || return 1
  fi

  local source_dir="$STAFF_ROOT/sources/$source_name"
  local link_path="$source_dir/repo"
  local metadata_path="$source_dir/source.toml"

  if [ -e "$source_dir" ] || [ -L "$source_dir" ]; then
    error "Source bundle already exists: $source_dir"
    return 1
  fi

  mkdir -p "$source_dir" || {
    error "Failed to create $source_dir"
    return 1
  }

  ln -s "$source_path" "$link_path" || {
    rm -rf "$source_dir"
    error "Failed to create source symlink"
    return 1
  }

  if [ ! -e "$link_path" ]; then
    rm -rf "$source_dir"
    error "Created symlink does not resolve"
    return 1
  fi

  # Discovery runs against the read-only symlink, not the raw source path,
  # so any content_root recorded for a synthesized manifest points at the
  # stable, bundle-owned location.
  local manifest_paths=()
  while IFS= read -r manifest_path; do
    [ -n "$manifest_path" ] || continue
    manifest_paths+=("$manifest_path")
  done < <(discover_source_manifests "$link_path")

  while IFS= read -r manifest_path; do
    [ -n "$manifest_path" ] || continue
    manifest_paths+=("$manifest_path")
  done < <(discover_foreign_manifests "$link_path" "$source_name")

  if [ ${#manifest_paths[@]} -eq 0 ]; then
    rm -rf "$source_dir"
    error "No staff projects found in: $source_path"
    return 1
  fi

  local project_names=() project_categories=() project_install_types=() project_rel_paths=()
  local project_synthesized=() project_native_formats=()
  local seen_names=""
  local manifest project_name category install_type rel_manifest synthesized native_format
  for manifest in "${manifest_paths[@]}"; do
    project_name=$(jq -r '.name // empty' "$manifest") || return 1
    category=$(jq -r '.category // empty' "$manifest") || return 1
    install_type=$(jq -r '.install.type // empty' "$manifest") || return 1
    synthesized=$(jq -r '.synthesized // false' "$manifest") || return 1
    native_format=$(jq -r '.native_format // "staff"' "$manifest") || return 1

    if [ -z "$project_name" ] || [ -z "$category" ] || [ -z "$install_type" ]; then
      rm -rf "$source_dir"
      error "staff.json must define name, category, and install.type: $manifest"
      return 1
    fi

    case "$category" in
      skill|mcp|agent|tool|harness|lib) ;;
      *)
        rm -rf "$source_dir"
        error "Unsupported category in $manifest: $category"
        return 1
        ;;
    esac

    case "$install_type" in
      skill|mcp|agent|tool) ;;
      *)
        rm -rf "$source_dir"
        error "Unsupported install.type in $manifest: $install_type"
        return 1
        ;;
    esac

    if printf '%s' "$seen_names" | grep -Fxq "$project_name"; then
      rm -rf "$source_dir"
      error "Duplicate project name '$project_name' found in source repo"
      return 1
    fi

    if ensure_registry >/dev/null 2>&1; then
      local existing
      existing=$(jq -r --arg name "$project_name" '.projects[] | select(.name == $name) | .path' "$STAFF_REGISTRY")
      if [ -n "$existing" ]; then
        rm -rf "$source_dir"
        error "Project name '$project_name' already exists in registry at $existing"
        return 1
      fi
    fi

    case "$manifest" in
      "$link_path"/*)   rel_manifest="${manifest#$link_path/}" ;;
      "$STAFF_ROOT"/*)  rel_manifest="${manifest#$STAFF_ROOT/}" ;;
      *)                rel_manifest="$manifest" ;;
    esac
    project_names+=("$project_name")
    project_categories+=("$category")
    project_install_types+=("$install_type")
    project_rel_paths+=("$rel_manifest")
    project_synthesized+=("$synthesized")
    project_native_formats+=("$native_format")
    seen_names="${seen_names}${project_name}\n"
  done

  if [ ${#project_names[@]} -eq 1 ] && [ "${project_names[0]}" != "$source_name" ]; then
    info "Registering source bundle '$source_name' for project '${project_names[0]}'"
  fi

  if [ ${#project_names[@]} -gt 1 ]; then
    info "Registering source bundle '$source_name' with ${#project_names[@]} projects"
  fi

  local source_ref=""
  local source_remote=""
  if git -C "$source_path" rev-parse --git-dir >/dev/null 2>&1; then
    source_ref=$(git -C "$source_path" rev-parse HEAD 2>/dev/null || true)
    source_remote=$(git -C "$source_path" remote get-url origin 2>/dev/null || true)
  fi

  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  cat > "$metadata_path" <<EOF
source_name = "$source_name"
source_path = "$source_path"
repo_link = "repo"
added_at = "$timestamp"
git_ref = "$source_ref"
git_remote = "$source_remote"
auto_install = $auto_install
install_scope = "$install_scope"
project_count = ${#project_names[@]}
EOF

  local idx
  for idx in "${!project_names[@]}"; do
    cat >> "$metadata_path" <<EOF

[[projects]]
name = "${project_names[$idx]}"
category = "${project_categories[$idx]}"
install_type = "${project_install_types[$idx]}"
manifest = "${project_rel_paths[$idx]}"
synthesized = ${project_synthesized[$idx]}
native_format = "${project_native_formats[$idx]}"
EOF
  done

  source "$STAFF_ROOT/lib/staff/cmd_registry.sh"
  registry_rebuild || return 1

  local install_status="registered"
  if [ "$auto_install" = "true" ]; then
    for project_name in "${project_names[@]}"; do
      "$STAFF_ROOT/bin/staff" install "$project_name" --scope "$install_scope" || return 1
    done
    install_status="installed"
  fi

  add_source_update_metadata_status "$metadata_path" "$install_status"
  add_source_print_ready "$source_name" "$install_status" "$install_scope" "$auto_install" "${project_names[@]}"
}

discover_source_manifests() {
  local source_path="$1"
  local found=0

  if [ -f "$source_path/staff.json" ]; then
    printf '%s\n' "$source_path/staff.json"
    found=1
  fi

  local cat_dir
  for cat_dir in $CATEGORIES; do
    local full_dir="$source_path/$cat_dir"
    [ -d "$full_dir" ] || continue

    local project_dir
    for project_dir in "$full_dir"/*/; do
      [ -d "$project_dir" ] || continue
      project_dir="${project_dir%/}"
      if [ -f "$project_dir/staff.json" ]; then
        printf '%s\n' "$project_dir/staff.json"
        found=1
      fi
    done
  done

  return $((1 - found))
}

# Discover projects that have no staff.json but match a category's native
# foreign format (SKILL.md, Claude Code agent-frontmatter), and synthesize a
# staff.json for each under sources/<source_name>/generated/ so the rest of
# add_source (and later, cmd_install.sh) can treat them like any other
# manifest. Emits the synthesized manifest paths, one per line.
discover_foreign_manifests() {
  local link_path="$1" source_name="$2"

  local project_dir derived_name manifest_path
  while IFS= read -r project_dir; do
    [ -n "$project_dir" ] || continue
    derived_name=$(frontmatter_field "$project_dir/SKILL.md" "name")
    [ -n "$derived_name" ] || derived_name="$(basename "$project_dir")"
    manifest_path=$(synthesize_manifest "skill" "$project_dir" "$derived_name" "$source_name") || return 1
    printf '%s\n' "$manifest_path"
  done < <(recognize_skills "$link_path")

  local agent_file
  while IFS= read -r agent_file; do
    [ -n "$agent_file" ] || continue
    derived_name=$(frontmatter_field "$agent_file" "name")
    [ -n "$derived_name" ] || derived_name="$(basename "$agent_file" .md)"
    manifest_path=$(synthesize_manifest "agent" "$(dirname "$agent_file")" "$derived_name" "$source_name" "$(basename "$agent_file")") || return 1
    printf '%s\n' "$manifest_path"
  done < <(recognize_agents "$link_path")
}

add_source_update_metadata_status() {
  local metadata_path="$1" install_status="$2"
  printf 'install_status = "%s"\n' "$install_status" >> "$metadata_path"
}

add_source_print_ready() {
  local source_name="$1" install_status="$2" install_scope="$3" auto_install="$4"
  shift 4
  local project_names=("$@")

  ok "Registered source bundle '$source_name' in sources/"
  if [ "$install_status" = "installed" ]; then
    ok "Discovered and installed ${#project_names[@]} project(s)"
  else
    info "Discovered ${#project_names[@]} project(s); install was skipped"
  fi

  local project_name
  for project_name in "${project_names[@]}"; do
    if [ "$auto_install" = "true" ]; then
      info "Ready: $project_name"
    else
      info "Install with: staff install $project_name --scope $install_scope"
    fi
  done
}
