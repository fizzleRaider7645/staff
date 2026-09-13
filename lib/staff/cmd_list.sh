#!/usr/bin/env bash

# Category directories are plural (skills/, mcps/) but manifests and the
# registry store the singular. Accept either, so `--category skills` does not
# silently return nothing.
normalize_category() {
  case "$1" in
    skills)    echo "skill" ;;
    mcps)      echo "mcp" ;;
    agents)    echo "agent" ;;
    tools)     echo "tool" ;;
    harnesses) echo "harness" ;;
    libs)      echo "lib" ;;
    *)         echo "$1" ;;
  esac
}

cmd_list() {
  require_jq

  local filter_category="" filter_language="" filter_tag="" filter_status="" filter_sourced=""

  # Reject a trailing option with no value rather than tripping over set -u
  need_value() {
    if [ $# -lt 2 ] || [ -z "${2:-}" ]; then
      error "Option $1 requires a value"
      return 1
    fi
  }

  while [ $# -gt 0 ]; do
    case "$1" in
      --category)  need_value "$@" || return 1; filter_category="$2";  shift 2 ;;
      --language)  need_value "$@" || return 1; filter_language="$2";  shift 2 ;;
      --tag)       need_value "$@" || return 1; filter_tag="$2";       shift 2 ;;
      --status)    need_value "$@" || return 1; filter_status="$2";    shift 2 ;;
      --sourced)   need_value "$@" || return 1; filter_sourced="$2";   shift 2 ;;
      -h|--help)
        cat <<EOF
${BOLD}staff list${RESET} — list projects in the registry

${BOLD}Usage:${RESET}
  staff list [options]

${BOLD}Options:${RESET}
  --category CAT    Filter by category (skill, mcp, agent, tool, harness, lib;
                    the plural directory names are accepted too)
  --language LANG   Filter by language (typescript, python, go, rust, shell, markdown)
  --tag TAG         Filter by tag
  --status STATUS   Filter by status (draft, alpha, beta, stable, deprecated)
  --sourced true|false   Filter by sourced status (external repos)
  -h, --help        Show this help

EOF
        return 0
        ;;
      *)
        error "Unknown option: $1"
        return 1
        ;;
    esac
  done

  if [ -n "$filter_category" ]; then
    filter_category=$(normalize_category "$filter_category")
    case "$filter_category" in
      skill|mcp|agent|tool|harness|lib) ;;
      *)
        error "Unknown category: $filter_category"
        error "Valid categories: skill mcp agent tool harness lib"
        return 1
        ;;
    esac
  fi

  if [ -n "$filter_status" ]; then
    case "$filter_status" in
      draft|alpha|beta|stable|deprecated) ;;
      *)
        error "Unknown status: $filter_status"
        error "Valid statuses: draft alpha beta stable deprecated"
        return 1
        ;;
    esac
  fi

  if [ -n "$filter_sourced" ]; then
    case "$filter_sourced" in
      true|false) ;;
      *)
        error "Invalid --sourced value: $filter_sourced (must be true or false)"
        return 1
        ;;
    esac
  fi

  if ! ensure_registry; then
    return 1
  fi

  local all_projects
  all_projects=$(registry_projects)

  local jq_args=()
  local jq_filter='.'

  if [ -n "$filter_category" ]; then
    jq_args+=(--arg cat "$filter_category")
    jq_filter="$jq_filter | map(select(.category == \$cat))"
  fi
  if [ -n "$filter_language" ]; then
    jq_args+=(--arg lang "$filter_language")
    jq_filter="$jq_filter | map(select(.language == \$lang))"
  fi
  if [ -n "$filter_tag" ]; then
    jq_args+=(--arg tag "$filter_tag")
    jq_filter="$jq_filter | map(select((.tags // []) | index(\$tag)))"
  fi
  if [ -n "$filter_status" ]; then
    jq_args+=(--arg st "$filter_status")
    jq_filter="$jq_filter | map(select(.status == \$st))"
  fi
  if [ -n "$filter_sourced" ]; then
    jq_args+=(--argjson sourced "$filter_sourced")
    jq_filter="$jq_filter | map(select((.sourced // false) == \$sourced))"
  fi

  local results
  results=$(echo "$all_projects" | jq -r "${jq_args[@]+"${jq_args[@]}"}" "$jq_filter")

  local count
  count=$(echo "$results" | jq 'length')

  if [ "$count" -eq 0 ]; then
    info "No projects found"
    # An open-ended filter that matched nothing is usually a typo — show what
    # values actually exist rather than leaving the user guessing.
    if [ -n "$filter_language" ]; then
      info "Languages in the registry: $(echo "$all_projects" | jq -r '[.[].language] | unique | join(" ")')"
    fi
    if [ -n "$filter_tag" ]; then
      info "Tags in the registry: $(echo "$all_projects" | jq -r '[.[].tags // [] | .[]] | unique | join(" ")')"
    fi
    return 0
  fi

  printf "${BOLD}%-24s %-10s %-12s %-10s %-8s %s${RESET}\n" "NAME" "CATEGORY" "LANGUAGE" "STATUS" "SOURCE" "DESCRIPTION"
  printf "%s\n" "$(printf '%.0s─' {1..100})"

  echo "$results" | jq -r '.[] | [.name, .category, .language, .status, (.sourced // false | tostring), .description] | @tsv' | \
    while IFS=$'\t' read -r name category language status sourced description; do
      local status_color="$RESET"
      case "$status" in
        stable)     status_color="$GREEN" ;;
        beta)       status_color="$YELLOW" ;;
        alpha)      status_color="$YELLOW" ;;
        draft)      status_color="$DIM" ;;
        deprecated) status_color="$RED" ;;
      esac

      local sourced_marker="local"
      [ "$sourced" = "true" ] && sourced_marker="source"

      printf "%-24s %-10s %-12s ${status_color}%-10s${RESET} %-8s %s\n" \
        "$name" "$category" "$language" "$status" "$sourced_marker" "$description"
    done

  printf "\n${DIM}%d project(s)${RESET}\n" "$count"
}
