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

  local source_dir="$STAFF_ROOT/sources/$source_name"
  local link_path="$source_dir/repo"
  local metadata_path="$source_dir/source.toml"

  if [ -e "$source_dir" ] || [ -L "$source_dir" ]; then
    error "Source bundle already exists: $source_dir"
    error "To re-scan it for upstream changes: staff update_source $source_name"
    error "To drop it and start over:         staff remove_source $source_name"
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

  collect_source_projects "$link_path" "$source_name" "${manifest_paths[@]}" || {
    rm -rf "$source_dir"
    return 1
  }
  local project_names=("${SRC_NAMES[@]}")
  local project_categories=("${SRC_CATEGORIES[@]}")
  local project_install_types=("${SRC_INSTALL_TYPES[@]}")
  local project_rel_paths=("${SRC_REL_PATHS[@]}")
  local project_synthesized=("${SRC_SYNTHESIZED[@]}")
  local project_native_formats=("${SRC_NATIVE_FORMATS[@]}")

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

  local install_status="registered"
  local install_failures=()
  if [ "$auto_install" = "true" ]; then
    for project_name in "${project_names[@]}"; do
      # One project failing to install must not discard the whole bundle —
      # a sourced project that declares a build command is refused by
      # default, and that is an expected outcome, not a broken ingest.
      if ! "$STAFF_ROOT/bin/staff" install "$project_name" --scope "$install_scope"; then
        warn "Could not install '$project_name' — the bundle is still registered"
        install_failures+=("$project_name")
      fi
    done
    if [ ${#install_failures[@]} -eq 0 ]; then
      install_status="installed"
    else
      install_status="partial"
    fi
  fi

  add_source_update_metadata_status "$metadata_path" "$install_status"
  add_source_print_ready "$source_name" "$install_status" "$install_scope" "$auto_install" "${project_names[@]}"

  if [ ${#install_failures[@]} -gt 0 ]; then
    warn "Not installed: ${install_failures[*]}"
    info "Retry individually, e.g. staff install ${install_failures[0]} --scope $install_scope"
    return 1
  fi
  return 0
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
  if [ "$install_status" = "partial" ]; then
    warn "Discovered ${#project_names[@]} project(s); some could not be installed"
  elif [ "$install_status" = "installed" ]; then
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

# ---------------------------------------------------------------------------
# Shared source-bundle machinery
# ---------------------------------------------------------------------------

# Validate every discovered manifest and publish the results as parallel
# arrays (bash 3.2 has no associative arrays or namerefs). Registry duplicate
# checks skip entries contributed by this same source, so re-running discovery
# over an already-registered bundle does not collide with itself.
#
# Usage: collect_source_projects <link_path> <source_name> <manifest>...
# Sets:  SRC_NAMES SRC_CATEGORIES SRC_INSTALL_TYPES SRC_REL_PATHS
#        SRC_SYNTHESIZED SRC_NATIVE_FORMATS
collect_source_projects() {
  local link_path="$1" source_name="$2"
  shift 2

  SRC_NAMES=() SRC_CATEGORIES=() SRC_INSTALL_TYPES=() SRC_REL_PATHS=()
  SRC_SYNTHESIZED=() SRC_NATIVE_FORMATS=()

  local seen_names=""
  local manifest project_name category install_type rel_manifest synthesized native_format

  for manifest in "$@"; do
    project_name=$(jq -r '.name // empty' "$manifest") || return 1
    category=$(jq -r '.category // empty' "$manifest") || return 1
    install_type=$(jq -r '.install.type // empty' "$manifest") || return 1
    synthesized=$(jq -r '.synthesized // false' "$manifest") || return 1
    native_format=$(jq -r '.native_format // "staff"' "$manifest") || return 1

    if [ -z "$project_name" ] || [ -z "$category" ] || [ -z "$install_type" ]; then
      error "staff.json must define name, category, and install.type: $manifest"
      return 1
    fi

    case "$category" in
      skill|mcp|agent|tool|harness|lib) ;;
      *) error "Unsupported category in $manifest: $category"; return 1 ;;
    esac

    case "$install_type" in
      skill|mcp|agent|tool) ;;
      *) error "Unsupported install.type in $manifest: $install_type"; return 1 ;;
    esac

    if printf '%s\n' "$seen_names" | grep -Fxq "$project_name"; then
      error "Duplicate project name '$project_name' found in source repo"
      return 1
    fi

    if ensure_registry >/dev/null 2>&1; then
      local existing
      existing=$(registry_projects | jq -r --arg name "$project_name" --arg src "$source_name" '
        .[]
        | select(.name == $name)
        | select((.source_name // "") != $src)
        | .path
      ')
      if [ -n "$existing" ]; then
        error "Project name '$project_name' already exists in registry at $existing"
        return 1
      fi
    fi

    case "$manifest" in
      "$link_path"/*)   rel_manifest="${manifest#$link_path/}" ;;
      "$STAFF_ROOT"/*)  rel_manifest="${manifest#$STAFF_ROOT/}" ;;
      *)                rel_manifest="$manifest" ;;
    esac

    SRC_NAMES+=("$project_name")
    SRC_CATEGORIES+=("$category")
    SRC_INSTALL_TYPES+=("$install_type")
    SRC_REL_PATHS+=("$rel_manifest")
    SRC_SYNTHESIZED+=("$synthesized")
    SRC_NATIVE_FORMATS+=("$native_format")
    seen_names="${seen_names}${project_name}
"
  done
}

# Run both discovery tiers against a bundle's repo symlink.
# Echoes manifest paths, one per line.
discover_all_manifests() {
  local link_path="$1" source_name="$2"
  discover_source_manifests "$link_path" || true
  discover_foreign_manifests "$link_path" "$source_name" || return 1
}

# Project names recorded in a bundle's source.toml [[projects]] blocks.
source_project_names() {
  local metadata_path="$1"
  [ -f "$metadata_path" ] || return 0
  sed -n 's/^name = "\(.*\)"$/\1/p' "$metadata_path"
}

# Value of a top-level scalar key in source.toml.
source_meta_value() {
  local metadata_path="$1" key="$2"
  [ -f "$metadata_path" ] || return 0
  sed -n "s/^${key} = \"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" "$metadata_path" | head -1
}

# True if the project has any installation record.
is_installed() {
  local name="$1"
  [ -f "$STAFF_INSTALLED" ] || return 1
  local hit
  hit=$(jq -r --arg name "$name" '[.installations[] | select(.project == $name)] | length' "$STAFF_INSTALLED")
  [ "$hit" -gt 0 ]
}

# Write the [[projects]] section of a bundle's source.toml from the SRC_* arrays.
write_source_metadata_projects() {
  local metadata_path="$1"
  local idx
  for idx in "${!SRC_NAMES[@]}"; do
    cat >> "$metadata_path" <<EOF

[[projects]]
name = "${SRC_NAMES[$idx]}"
category = "${SRC_CATEGORIES[$idx]}"
install_type = "${SRC_INSTALL_TYPES[$idx]}"
manifest = "${SRC_REL_PATHS[$idx]}"
synthesized = ${SRC_SYNTHESIZED[$idx]}
native_format = "${SRC_NATIVE_FORMATS[$idx]}"
EOF
  done
}

# ---------------------------------------------------------------------------
# staff update_source
# ---------------------------------------------------------------------------

cmd_update_source() {
  require_jq
  ensure_state_dir

  local source_name="" do_install="auto"

  while [ $# -gt 0 ]; do
    case "$1" in
      --no-install) do_install="never"; shift ;;
      -h|--help)
        cat <<EOF
${BOLD}staff update_source${RESET} — re-scan a registered source and sync it

${BOLD}Usage:${RESET}
  staff update_source <repo-name> [--no-install]

Re-runs discovery against the bundle's existing repo symlink, then:
  - installs projects the source has gained
  - uninstalls projects the source has dropped
  - re-derives synthesized manifests, picking up upstream edits
  - refreshes the recorded git ref

${BOLD}Options:${RESET}
  --no-install   Sync the registry and manifests without installing
  -h, --help     Show this help

EOF
        return 0
        ;;
      -*) error "Unknown option: $1"; return 1 ;;
      *)
        if [ -z "$source_name" ]; then source_name="$1"
        else error "Too many arguments"; return 1; fi
        shift
        ;;
    esac
  done

  if [ -z "$source_name" ]; then
    error "Usage: staff update_source <repo-name> [--no-install]"
    return 1
  fi

  local source_dir="$STAFF_ROOT/sources/$source_name"
  local link_path="$source_dir/repo"
  local metadata_path="$source_dir/source.toml"

  if [ ! -d "$source_dir" ]; then
    error "No such source bundle: $source_name"
    error "Registered sources: $(ls "$STAFF_ROOT/sources" 2>/dev/null | tr '\n' ' ')"
    return 1
  fi
  if [ ! -d "$link_path" ]; then
    error "Source '$source_name': repo link does not resolve -> $(readlink "$link_path" 2>/dev/null || echo '<missing>')"
    error "Restore the path, or drop the bundle: staff remove_source $source_name"
    return 1
  fi

  local install_scope auto_install source_path
  install_scope=$(source_meta_value "$metadata_path" "install_scope"); install_scope="${install_scope:-user}"
  auto_install=$(source_meta_value "$metadata_path" "auto_install"); auto_install="${auto_install:-true}"
  source_path=$(source_meta_value "$metadata_path" "source_path")

  local old_names
  old_names=$(source_project_names "$metadata_path")

  # Re-synthesize from scratch so upstream edits to SKILL.md / agent
  # frontmatter are picked up rather than served from the previous cache.
  rm -rf "$source_dir/generated"

  local manifest_paths=()
  while IFS= read -r manifest_path; do
    [ -n "$manifest_path" ] || continue
    manifest_paths+=("$manifest_path")
  done < <(discover_all_manifests "$link_path" "$source_name")

  if [ ${#manifest_paths[@]} -eq 0 ]; then
    error "No staff projects found in source '$source_name' any more"
    error "If the source is genuinely empty, drop it: staff remove_source $source_name"
    return 1
  fi

  collect_source_projects "$link_path" "$source_name" "${manifest_paths[@]}" || return 1

  local new_names
  new_names=$(printf '%s\n' "${SRC_NAMES[@]}")

  local added removed
  added=$(comm -13 <(printf '%s\n' $old_names | sort) <(printf '%s\n' $new_names | sort))
  removed=$(comm -23 <(printf '%s\n' $old_names | sort) <(printf '%s\n' $new_names | sort))

  # Uninstall what the source dropped, before the registry forgets it
  local name
  for name in $removed; do
    if is_installed "$name"; then
      info "Dropped upstream, uninstalling: $name"
      "$STAFF_ROOT/bin/staff" uninstall "$name" >/dev/null || warn "Could not uninstall $name"
    else
      info "Dropped upstream: $name (was not installed)"
    fi
  done

  # Rewrite source.toml
  local source_ref="" source_remote=""
  if git -C "$link_path" rev-parse --git-dir >/dev/null 2>&1; then
    source_ref=$(git -C "$link_path" rev-parse HEAD 2>/dev/null || true)
    source_remote=$(git -C "$link_path" remote get-url origin 2>/dev/null || true)
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
project_count = ${#SRC_NAMES[@]}
EOF
  write_source_metadata_projects "$metadata_path"

  # Refresh anything already installed; install additions when the bundle was
  # registered with auto-install. Projects the user never installed stay out.
  local installed_count=0 refreshed_count=0
  if [ "$do_install" != "never" ]; then
    for name in "${SRC_NAMES[@]}"; do
      if is_installed "$name"; then
        "$STAFF_ROOT/bin/staff" install "$name" --scope "$install_scope" >/dev/null \
          && refreshed_count=$((refreshed_count + 1)) \
          || warn "Could not refresh $name"
      elif [ "$auto_install" = "true" ]; then
        "$STAFF_ROOT/bin/staff" install "$name" --scope "$install_scope" >/dev/null \
          && installed_count=$((installed_count + 1)) \
          || warn "Could not install $name"
      fi
    done
  fi

  local n_added n_removed
  n_added=$(printf '%s' "$added" | grep -c . || true)
  n_removed=$(printf '%s' "$removed" | grep -c . || true)

  ok "Updated source '$source_name': ${#SRC_NAMES[@]} project(s)"
  [ "$n_added" -gt 0 ]   && info "Added:   $(echo $added | tr '\n' ' ')"
  [ "$n_removed" -gt 0 ] && info "Removed: $(echo $removed | tr '\n' ' ')"
  [ "$installed_count" -gt 0 ] && info "Installed $installed_count new project(s)"
  [ "$refreshed_count" -gt 0 ] && info "Refreshed $refreshed_count existing install(s)"
  if [ "$n_added" -eq 0 ] && [ "$n_removed" -eq 0 ]; then
    info "No projects added or removed"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# staff remove_source
# ---------------------------------------------------------------------------

cmd_remove_source() {
  require_jq
  ensure_state_dir

  local source_name="" keep_installed="false"

  while [ $# -gt 0 ]; do
    case "$1" in
      --keep-installed) keep_installed="true"; shift ;;
      -h|--help)
        cat <<EOF
${BOLD}staff remove_source${RESET} — unregister a source bundle

${BOLD}Usage:${RESET}
  staff remove_source <repo-name> [--keep-installed]

Uninstalls every project the bundle contributed, then removes
sources/<repo-name>/ and rebuilds the registry. The external repo itself
is never touched — only the symlink to it.

${BOLD}Options:${RESET}
  --keep-installed   Leave installed projects in place (their symlinks will
                     dangle once the bundle is gone)
  -h, --help         Show this help

EOF
        return 0
        ;;
      -*) error "Unknown option: $1"; return 1 ;;
      *)
        if [ -z "$source_name" ]; then source_name="$1"
        else error "Too many arguments"; return 1; fi
        shift
        ;;
    esac
  done

  if [ -z "$source_name" ]; then
    error "Usage: staff remove_source <repo-name> [--keep-installed]"
    return 1
  fi

  local source_dir="$STAFF_ROOT/sources/$source_name"
  local metadata_path="$source_dir/source.toml"

  if [ ! -d "$source_dir" ]; then
    error "No such source bundle: $source_name"
    error "Registered sources: $(ls "$STAFF_ROOT/sources" 2>/dev/null | tr '\n' ' ')"
    return 1
  fi

  local names
  names=$(source_project_names "$metadata_path")

  local name uninstalled=0
  if [ "$keep_installed" != "true" ]; then
    for name in $names; do
      if is_installed "$name"; then
        "$STAFF_ROOT/bin/staff" uninstall "$name" >/dev/null \
          && uninstalled=$((uninstalled + 1)) \
          || warn "Could not uninstall $name"
      fi
    done
  fi

  # Only ever removes the bundle directory — the symlink target is untouched.
  rm -rf "$source_dir"

  ok "Removed source bundle '$source_name'"
  [ "$uninstalled" -gt 0 ] && info "Uninstalled $uninstalled project(s)"
  [ "$keep_installed" = "true" ] && warn "Installed projects left in place — their symlinks now dangle"
  return 0
}
