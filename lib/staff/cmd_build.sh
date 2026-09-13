#!/usr/bin/env bash

cmd_build() {
  local project_name="" allow_build="false"

  while [ $# -gt 0 ]; do
    case "$1" in
      --allow-build) allow_build="true"; shift ;;
      -h|--help)
        cat <<EOF
${BOLD}staff build${RESET} — build a project

${BOLD}Usage:${RESET}
  staff build <project> [--allow-build]

Runs the build command from the project's staff.json, or auto-detects from build files.

${BOLD}Options:${RESET}
  --allow-build   Permit running a build command declared by a sourced
                  (external) project. Refused by default.

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
    error "Usage: staff build <project>"
    return 1
  fi

  require_jq

  local project_info
  project_info=$(find_project "$project_name") || return 1

  local project_path
  project_path=$(echo "$project_info" | jq -r '.path')
  local abs_path="$STAFF_ROOT/$project_path"
  local manifest="$abs_path/staff.json"

  local build_cmd=""
  if [ -f "$manifest" ]; then
    build_cmd=$(jq -r '.build.command // ""' "$manifest")
  fi

  # Auto-detect if no build command specified
  if [ -z "$build_cmd" ]; then
    if [ -f "$abs_path/package.json" ]; then
      build_cmd="npm install && npm run build"
    elif [ -f "$abs_path/pyproject.toml" ]; then
      build_cmd="pip install -e ."
    elif [ -f "$abs_path/go.mod" ]; then
      build_cmd="go build ./..."
    elif [ -f "$abs_path/Cargo.toml" ]; then
      build_cmd="cargo build --release"
    else
      die "No build command found — set it in staff.json or add a recognized build file"
    fi
    info "Auto-detected build command: $build_cmd"
  fi

  local sourced
  sourced=$(echo "$project_info" | jq -r '.sourced // false')

  info "Building $project_name..."
  if run_build_command "$build_cmd" "$abs_path" "$sourced" "$allow_build" "$project_name"; then
    ok "Build succeeded: $project_name"
  else
    die "Build failed: $project_name"
  fi
}
