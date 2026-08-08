#!/usr/bin/env bash

# Colors (disabled when not a terminal)
if [ -t 1 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[0;33m'
  BLUE='\033[0;34m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  DIM='\033[2m'
  RESET='\033[0m'
else
  RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' DIM='' RESET=''
fi

info()  { printf "${BLUE}info${RESET}  %s\n" "$*"; }
ok()    { printf "${GREEN}ok${RESET}    %s\n" "$*"; }
warn()  { printf "${YELLOW}warn${RESET}  %s\n" "$*" >&2; }
error() { printf "${RED}error${RESET} %s\n" "$*" >&2; }
die()   { error "$@"; exit 1; }

require_jq() {
  command -v jq >/dev/null 2>&1 || die "jq is required but not installed. Install it: brew install jq"
}

resolve_staff_root() {
  local source="${BASH_SOURCE[0]}"
  while [ -L "$source" ]; do
    local dir
    dir="$(cd -P "$(dirname "$source")" && pwd)"
    source="$(readlink "$source")"
    [[ "$source" != /* ]] && source="$dir/$source"
  done
  local script_dir
  script_dir="$(cd -P "$(dirname "$source")" && pwd)"
  # _common.sh is at lib/staff/_common.sh, so root is two levels up
  echo "$(cd "$script_dir/../.." && pwd)"
}

STAFF_ROOT="${STAFF_ROOT:-$(resolve_staff_root)}"
STAFF_STATE_DIR="${HOME}/.staff"
STAFF_INSTALLED="${STAFF_STATE_DIR}/installed.json"
STAFF_REGISTRY="${STAFF_ROOT}/registry.json"

CATEGORIES="skills mcps agents tools harnesses lib"

ensure_state_dir() {
  if [ ! -d "$STAFF_STATE_DIR" ]; then
    mkdir -p "$STAFF_STATE_DIR"
  fi
  if [ ! -f "$STAFF_INSTALLED" ]; then
    echo '{"installations":[]}' > "$STAFF_INSTALLED"
  fi
}

ensure_registry() {
  if [ ! -f "$STAFF_REGISTRY" ]; then
    warn "Registry not found. Run: staff registry rebuild"
    return 1
  fi
}

# Find a project by name in the registry
find_project() {
  local name="$1"
  require_jq
  ensure_registry || return 1
  local result
  result=$(jq -r --arg name "$name" '.projects[] | select(.name == $name)' "$STAFF_REGISTRY")
  if [ -z "$result" ]; then
    error "Project '$name' not found in registry"
    return 1
  fi
  echo "$result"
}
