#!/usr/bin/env bash
#
# Test runner for the staff CLI.
#
# Zero dependencies beyond what the CLI itself needs (bash + jq). Every test
# runs against a throwaway copy of the repo with its own $HOME, so nothing
# touches the developer's real registry, ~/.claude, or ~/.staff.
#
# Usage:
#   ./tests/run.sh                 run everything
#   ./tests/run.sh install         run only test_install.sh
#   ./tests/run.sh -v              show output from failing commands

set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/.." && pwd)"

VERBOSE=0
FILTERS=()
for arg in "$@"; do
  case "$arg" in
    -v|--verbose) VERBOSE=1 ;;
    *) FILTERS+=("$arg") ;;
  esac
done

if [ -t 1 ]; then
  T_RED=$'\033[0;31m'; T_GREEN=$'\033[0;32m'; T_DIM=$'\033[2m'; T_BOLD=$'\033[1m'; T_RESET=$'\033[0m'
else
  T_RED=''; T_GREEN=''; T_DIM=''; T_BOLD=''; T_RESET=''
fi

ORIG_HOME="$HOME"
PASS=0
FAIL=0
FAILED_NAMES=()
CURRENT_SUITE=""

# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

# Build an isolated repo copy with an empty $HOME. Sets, for the caller:
#   SB       sandbox root
#   STAFF    path to the CLI under test
#   HOME     redirected into the sandbox
# The copy carries the real bin/lib/templates but no projects and no sources,
# so each test starts from a known-empty registry.
sandbox_init() {
  SB="$(mktemp -d "${TMPDIR:-/tmp}/staff-test.XXXXXX")"
  mkdir -p "$SB/repo" "$SB/home"
  cp -R "$REPO_ROOT/bin" "$REPO_ROOT/lib" "$REPO_ROOT/templates" "$SB/repo/"
  mkdir -p "$SB/repo"/{skills,mcps,agents,tools,harnesses,sources}
  export HOME="$SB/home"
  STAFF="$SB/repo/bin/staff"
  "$STAFF" registry rebuild >/dev/null 2>&1
}

sandbox_cleanup() {
  [ -n "${SB:-}" ] && [ -d "$SB" ] && rm -rf "$SB"
  SB=""
  export HOME="$ORIG_HOME"
}

# Never leave a sandbox behind, even if a suite aborts part-way.
trap sandbox_cleanup EXIT INT TERM

# Create an external repo of Claude-format skills.
#   make_source_repo <dir> <name>:<description> ...
make_source_repo() {
  local dir="$1"; shift
  mkdir -p "$dir/skills"
  local spec name desc
  for spec in "$@"; do
    name="${spec%%:*}"
    desc="${spec#*:}"
    mkdir -p "$dir/skills/$name"
    printf -- '---\nname: %s\ndescription: %s\n---\n\n# %s\n' "$name" "$desc" "$name" \
      > "$dir/skills/$name/SKILL.md"
  done
}

git_init_commit() {
  local dir="$1" msg="${2:-init}"
  git -C "$dir" init -q 2>/dev/null
  git -C "$dir" add -A 2>/dev/null
  git -C "$dir" -c user.email=test@example.com -c user.name=test commit -qm "$msg" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

LAST_OUTPUT=""
LAST_STATUS=0

# Run a command, capturing combined output and exit status without tripping
# the runner's own error handling.
run() {
  LAST_OUTPUT="$("$@" 2>&1)"
  LAST_STATUS=$?
  return 0
}

_report_pass() { PASS=$((PASS + 1)); printf "  ${T_GREEN}ok${T_RESET}   %s\n" "$1"; }

_report_fail() {
  FAIL=$((FAIL + 1))
  FAILED_NAMES+=("$CURRENT_SUITE: $1")
  printf "  ${T_RED}FAIL${T_RESET} %s\n" "$1"
  [ -n "${2:-}" ] && printf "       %s\n" "$2"
  if [ "$VERBOSE" = "1" ] && [ -n "$LAST_OUTPUT" ]; then
    printf "${T_DIM}%s${T_RESET}\n" "$LAST_OUTPUT" | sed 's/^/       | /'
  fi
  return 0
}

assert_ok() {
  local msg="$1"
  if [ "$LAST_STATUS" -eq 0 ]; then _report_pass "$msg"
  else _report_fail "$msg" "expected exit 0, got $LAST_STATUS"; fi
}

assert_fails() {
  local msg="$1"
  if [ "$LAST_STATUS" -ne 0 ]; then _report_pass "$msg"
  else _report_fail "$msg" "expected non-zero exit, got 0"; fi
}

assert_eq() {
  local msg="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then _report_pass "$msg"
  else _report_fail "$msg" "want: [$expected]
       got : [$actual]"; fi
}

assert_contains() {
  local msg="$1" needle="$2" haystack="$3"
  case "$haystack" in
    *"$needle"*) _report_pass "$msg" ;;
    *) _report_fail "$msg" "expected to contain: $needle
       got: $haystack" ;;
  esac
}

assert_output_contains() { assert_contains "$1" "$2" "$LAST_OUTPUT"; }

assert_file() {
  local msg="$1" path="$2"
  if [ -f "$path" ]; then _report_pass "$msg"; else _report_fail "$msg" "no such file: $path"; fi
}

assert_no_file() {
  local msg="$1" path="$2"
  if [ ! -e "$path" ]; then _report_pass "$msg"; else _report_fail "$msg" "should not exist: $path"; fi
}

assert_symlink_resolves() {
  local msg="$1" path="$2"
  if [ -L "$path" ] && [ -e "$path" ]; then _report_pass "$msg"
  else _report_fail "$msg" "not a resolving symlink: $path -> $(readlink "$path" 2>/dev/null || echo '?')"; fi
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

suite() {
  CURRENT_SUITE="$1"
  printf "\n${T_BOLD}%s${T_RESET}\n" "$1"
}

command -v jq >/dev/null 2>&1 || { echo "jq is required to run the tests" >&2; exit 1; }

printf "${T_BOLD}staff test suite${T_RESET}\n"

shopt -s nullglob
for suite_file in "$TESTS_DIR"/test_*.sh; do
  base="$(basename "$suite_file" .sh)"; base="${base#test_}"
  if [ ${#FILTERS[@]} -gt 0 ]; then
    match=0
    for f in "${FILTERS[@]}"; do [ "$f" = "$base" ] && match=1; done
    [ "$match" = "1" ] || continue
  fi
  # shellcheck source=/dev/null
  source "$suite_file"
done

printf "\n%s\n" "────────────────────────────────────────"
if [ "$FAIL" -eq 0 ]; then
  printf "${T_GREEN}%d passed${T_RESET}\n" "$PASS"
  exit 0
fi
printf "${T_RED}%d passed, %d failed${T_RESET}\n" "$PASS" "$FAIL"
for n in "${FAILED_NAMES[@]}"; do printf "  ${T_RED}·${T_RESET} %s\n" "$n"; done
exit 1
