#!/usr/bin/env bash

cmd_test() {
  local project_name="" allow_test="false" run_all="false"

  while [ $# -gt 0 ]; do
    case "$1" in
      --all)        run_all="true"; shift ;;
      --allow-test) allow_test="true"; shift ;;
      -h|--help)
        cat <<EOF
${BOLD}staff test${RESET} — run a project's tests

${BOLD}Usage:${RESET}
  staff test <project> [--allow-test]
  staff test --all [--allow-test]

Runs the test command from the project's staff.json, or auto-detects one from
the project's build files. Projects with no test command are skipped by --all
rather than treated as failures.

${BOLD}Options:${RESET}
  --all          Test every project that has tests, and report a summary
  --allow-test   Permit running a test command declared by a sourced
                 (external) project. Refused by default.
  -h, --help     Show this help

${BOLD}Auto-detected by:${RESET}
  pyproject.toml   python -m pytest
  package.json     npm test        (only when it declares a test script)
  go.mod           go test ./...
  Cargo.toml       cargo test

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

  require_jq

  if [ "$run_all" = "true" ]; then
    [ -n "$project_name" ] && { error "Pass a project or --all, not both"; return 1; }
    test_all "$allow_test"
    return $?
  fi

  if [ -z "$project_name" ]; then
    error "Usage: staff test <project> [--allow-test]   (or: staff test --all)"
    return 1
  fi

  local project_info
  project_info=$(find_project "$project_name") || return 1

  test_one "$project_info" "$allow_test" "verbose"
}

# Resolve a project's test command: explicit in the manifest, else inferred
# from whatever build system the project uses. Echoes nothing when there is
# no way to test it.
resolve_test_command() {
  local abs_path="$1" manifest="$2"

  local cmd=""
  if [ -f "$manifest" ]; then
    cmd=$(jq -r '.test.command // ""' "$manifest")
  fi
  if [ -n "$cmd" ]; then
    printf '%s\n' "$cmd"
    return 0
  fi

  if [ -f "$abs_path/pyproject.toml" ]; then
    printf '%s\n' "python -m pytest"
  elif [ -f "$abs_path/package.json" ] \
       && jq -e '.scripts.test // empty' "$abs_path/package.json" >/dev/null 2>&1; then
    printf '%s\n' "npm test"
  elif [ -f "$abs_path/go.mod" ]; then
    printf '%s\n' "go test ./..."
  elif [ -f "$abs_path/Cargo.toml" ]; then
    printf '%s\n' "cargo test"
  fi
}

# Run one project's tests. Returns 0 pass, 1 fail, 2 nothing to run.
test_one() {
  local project_info="$1" allow_test="$2" verbose="${3:-}"

  local name project_path sourced
  name=$(echo "$project_info" | jq -r '.name')
  project_path=$(echo "$project_info" | jq -r '.path')
  sourced=$(echo "$project_info" | jq -r '.sourced // false')

  local abs_path="$STAFF_ROOT/$project_path"
  local manifest="$abs_path/staff.json"

  local test_cmd
  test_cmd=$(resolve_test_command "$abs_path" "$manifest")

  if [ -z "$test_cmd" ]; then
    if [ -n "$verbose" ]; then
      error "No test command found for '$name'"
      error "Set test.command in $project_path/staff.json, or add a recognized project file"
    fi
    return 2
  fi

  info "Testing $name: $test_cmd"
  if run_manifest_command "$test_cmd" "$abs_path" "$sourced" "$allow_test" \
       "$name" "test" "--allow-test"; then
    ok "Tests passed: $name"
    return 0
  fi
  error "Tests failed: $name"
  return 1
}

test_all() {
  local allow_test="$1"

  local projects
  projects=$(registry_projects)

  local passed=0 failed=0 skipped=0
  local failed_names=""
  local entry name status

  while IFS= read -r entry; do
    [ -n "$entry" ] || continue
    name=$(echo "$entry" | jq -r '.name')

    # test_one returns 1 for a failure and 2 for "nothing to run"; a bare
    # call would abort the loop under set -e.
    status=0
    test_one "$entry" "$allow_test" || status=$?

    case "$status" in
      0) passed=$((passed + 1)) ;;
      1) failed=$((failed + 1)); failed_names="${failed_names} ${name}" ;;
      *) skipped=$((skipped + 1)) ;;
    esac
  done < <(echo "$projects" | jq -c '.[]')

  printf "\n%s\n" "$(printf '%.0s─' {1..40})"
  if [ "$failed" -eq 0 ]; then
    ok "$passed passed, $skipped project(s) with no tests"
    return 0
  fi
  error "$passed passed, $failed failed, $skipped with no tests"
  error "Failed:${failed_names}"
  return 1
}
