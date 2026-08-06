#!/usr/bin/env bash

cmd_list() {
  require_jq

  local filter_category="" filter_language="" filter_tag="" filter_status=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --category)  filter_category="$2";  shift 2 ;;
      --language)  filter_language="$2";  shift 2 ;;
      --tag)       filter_tag="$2";       shift 2 ;;
      --status)    filter_status="$2";    shift 2 ;;
      -h|--help)
        cat <<EOF
${BOLD}staff list${RESET} — list projects in the registry

${BOLD}Usage:${RESET}
  staff list [options]

${BOLD}Options:${RESET}
  --category CAT    Filter by category (skill, mcp, agent, tool, harness, lib)
  --language LANG   Filter by language (typescript, python, go, rust, shell, markdown)
  --tag TAG         Filter by tag
  --status STATUS   Filter by status (draft, alpha, beta, stable, deprecated)
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

  if ! ensure_registry; then
    return 1
  fi

  local jq_filter='.projects'

  if [ -n "$filter_category" ]; then
    jq_filter="$jq_filter | map(select(.category == \"$filter_category\"))"
  fi
  if [ -n "$filter_language" ]; then
    jq_filter="$jq_filter | map(select(.language == \"$filter_language\"))"
  fi
  if [ -n "$filter_tag" ]; then
    jq_filter="$jq_filter | map(select(.tags | index(\"$filter_tag\")))"
  fi
  if [ -n "$filter_status" ]; then
    jq_filter="$jq_filter | map(select(.status == \"$filter_status\"))"
  fi

  local results
  results=$(jq -r "$jq_filter" "$STAFF_REGISTRY")

  local count
  count=$(echo "$results" | jq 'length')

  if [ "$count" -eq 0 ]; then
    info "No projects found"
    return 0
  fi

  printf "${BOLD}%-24s %-10s %-12s %-10s %s${RESET}\n" "NAME" "CATEGORY" "LANGUAGE" "STATUS" "DESCRIPTION"
  printf "%s\n" "$(printf '%.0s─' {1..90})"

  echo "$results" | jq -r '.[] | [.name, .category, .language, .status, .description] | @tsv' | \
    while IFS=$'\t' read -r name category language status description; do
      local status_color="$RESET"
      case "$status" in
        stable)     status_color="$GREEN" ;;
        beta)       status_color="$YELLOW" ;;
        alpha)      status_color="$YELLOW" ;;
        draft)      status_color="$DIM" ;;
        deprecated) status_color="$RED" ;;
      esac
      printf "%-24s %-10s %-12s ${status_color}%-10s${RESET} %s\n" \
        "$name" "$category" "$language" "$status" "$description"
    done

  printf "\n${DIM}%d project(s)${RESET}\n" "$count"
}
