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

# Timestamped backup of a config file about to be rewritten. Prior backups
# are kept — a single .bak was previously overwritten on every run.
backup_config() {
  local file="$1"
  [ -f "$file" ] || return 0
  cp "$file" "${file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
}

# Run a build command declared in a staff.json.
#
# These strings need shell semantics ("npm install && npm run build"), so the
# mitigation is consent rather than mechanism: for a project ingested from an
# external repo via add_source, the command was written by a third party and
# runs only when the user explicitly opts in. bash -c keeps it in its own
# process rather than eval'ing it into the caller's shell.
run_build_command() {
  local cmd="$1" dir="$2" sourced="$3" allow="$4" name="$5"

  if [ "$sourced" = "true" ] && [ "$allow" != "true" ]; then
    error "Refusing to run a build command from sourced project '$name'"
    error "  $cmd"
    error "This command comes from an external repo. Re-run with --allow-build to run it."
    return 1
  fi

  ( cd "$dir" && bash -c "$cmd" )
}

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

CATEGORIES="skills mcps agents tools harnesses lib"

ensure_state_dir() {
  if [ ! -d "$STAFF_STATE_DIR" ]; then
    mkdir -p "$STAFF_STATE_DIR"
  fi
  if [ ! -f "$STAFF_INSTALLED" ]; then
    echo '{"installations":[]}' > "$STAFF_INSTALLED"
  fi
}

# Locate every staff.json, emitting one metadata line per manifest:
#   <manifest path>\t<repo-relative project path>\t<sourced>\t<source name>
#
# There is no index file. A full walk of this repo takes single-digit
# milliseconds, and a cache would only reintroduce the question of whether it
# still agrees with the disk.
scan_manifests() {
  local cat_dir full_dir project_dir manifest rel

  for cat_dir in $CATEGORIES; do
    full_dir="$STAFF_ROOT/$cat_dir"
    [ -d "$full_dir" ] || continue
    for project_dir in "$full_dir"/*/; do
      [ -d "$project_dir" ] || continue
      project_dir="${project_dir%/}"
      manifest="$project_dir/staff.json"
      [ -f "$manifest" ] || continue
      rel="${project_dir#$STAFF_ROOT/}"
      printf '%s\t%s\t%s\t%s\n' "$manifest" "$rel" "false" ""
    done
  done

  local sources_root="$STAFF_ROOT/sources"
  [ -d "$sources_root" ] || return 0

  local source_dir source_name repo_dir generated_dir
  for source_dir in "$sources_root"/*/; do
    [ -d "$source_dir" ] || continue
    source_dir="${source_dir%/}"
    source_name="$(basename "$source_dir")"
    repo_dir="$source_dir/repo"

    if [ ! -d "$repo_dir" ]; then
      # Only a bundle that was actually registered is worth complaining about.
      # Nothing is lost by skipping it — there is no index to corrupt.
      if [ -L "$repo_dir" ] || [ -f "$source_dir/source.toml" ]; then
        warn "Source '$source_name': repo link does not resolve -> $(readlink "$repo_dir" 2>/dev/null || echo '<missing>')"
      fi
      continue
    fi

    if [ -f "$repo_dir/staff.json" ]; then
      rel="${repo_dir#$STAFF_ROOT/}"
      printf '%s\t%s\t%s\t%s\n' "$repo_dir/staff.json" "$rel" "true" "$source_name"
    fi

    for cat_dir in $CATEGORIES; do
      full_dir="$repo_dir/$cat_dir"
      [ -d "$full_dir" ] || continue
      for project_dir in "$full_dir"/*/; do
        [ -d "$project_dir" ] || continue
        project_dir="${project_dir%/}"
        manifest="$project_dir/staff.json"
        [ -f "$manifest" ] || continue
        rel="${project_dir#$STAFF_ROOT/}"
        printf '%s\t%s\t%s\t%s\n' "$manifest" "$rel" "true" "$source_name"
      done
    done

    # Manifests staff synthesized for foreign-format projects
    generated_dir="$source_dir/generated"
    [ -d "$generated_dir" ] || continue
    while IFS= read -r manifest; do
      [ -n "$manifest" ] || continue
      project_dir="${manifest%/staff.json}"
      rel="${project_dir#$STAFF_ROOT/}"
      printf '%s\t%s\t%s\t%s\n' "$manifest" "$rel" "true" "$source_name"
    done < <(find "$generated_dir" -name staff.json)
  done
}

# Every project staff knows about, as a single JSON array. Reads the disk
# every time; three jq invocations total, regardless of project count.
registry_projects() {
  require_jq

  local manifests=() metas=()
  local manifest rel sourced source_name
  while IFS=$'\t' read -r manifest rel sourced source_name; do
    [ -n "$manifest" ] || continue
    manifests+=("$manifest")
    metas+=("$(jq -n --arg p "$rel" --argjson s "$sourced" --arg sn "$source_name" \
      '{path:$p, sourced:$s, source_name:$sn}')")
  done < <(scan_manifests)

  if [ ${#manifests[@]} -eq 0 ]; then
    echo '[]'
    return 0
  fi

  local contents meta
  contents=$(jq -s '.' "${manifests[@]}") || return 1
  meta=$(printf '%s\n' "${metas[@]}" | jq -s '.')

  jq -n --argjson c "$contents" --argjson m "$meta" '
    [ range(0; $c | length) as $i
      | $c[$i] as $p
      | $m[$i] as $meta
      | {
          name: $p.name,
          category: $p.category,
          language: $p.language,
          description: $p.description,
          status: $p.status,
          path: $meta.path,
          tags: ($p.tags // []),
          version: ($p.version // "0.0.0"),
          sourced: $meta.sourced,
          synthesized: ($p.synthesized // false),
          native_format: ($p.native_format // "staff")
        }
        + (if $meta.source_name != "" then {source_name: $meta.source_name} else {} end)
    ]'
}

# Kept as a no-op guard so callers read naturally; there is no index to check.
ensure_registry() { return 0; }

# Resolve a project name to its manifest entry.
find_project() {
  local name="$1"
  require_jq

  local matches count
  matches=$(registry_projects | jq -c --arg name "$name" '[.[] | select(.name == $name)]')
  count=$(echo "$matches" | jq 'length')

  if [ "$count" -eq 0 ]; then
    error "Project '$name' not found"
    return 1
  fi

  # Two projects answering to one name would otherwise hand the caller two
  # records and let it build a path out of both.
  if [ "$count" -gt 1 ]; then
    error "Ambiguous project name '$name' — found $count projects:"
    echo "$matches" | jq -r '.[] | "  " + .path' >&2
    error "Rename one of them, or drop the source that introduced it"
    return 1
  fi

  echo "$matches" | jq -r '.[0]'
}
