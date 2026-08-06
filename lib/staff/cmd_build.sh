#!/usr/bin/env bash

cmd_build() {
  local project_name=""

  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help)
        cat <<EOF
${BOLD}staff build${RESET} — build a project

${BOLD}Usage:${RESET}
  staff build <project>

Runs the build command from the project's staff.json, or auto-detects from build files.

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

  info "Building $project_name..."
  (cd "$abs_path" && eval "$build_cmd")

  if [ $? -eq 0 ]; then
    ok "Build succeeded: $project_name"
  else
    die "Build failed: $project_name"
  fi
}
