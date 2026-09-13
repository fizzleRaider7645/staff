#!/usr/bin/env bash

cmd_list() {
  require_jq

  local filter_category="" filter_language="" filter_tag="" filter_status="" filter_sourced=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --category)  filter_category="$2";  shift 2 ;;
      --language)  filter_language="$2";  shift 2 ;;
      --tag)       filter_tag="$2";       shift 2 ;;
      --status)    filter_status="$2";    shift 2 ;;
      --sourced)   filter_sourced="$2";   shift 2 ;;
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

  if ! ensure_registry; then
    return 1
  fi

  local jq_args=()
  local jq_filter='.projects'

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
    jq_filter="$jq_filter | map(select(.tags | index(\$tag)))"
  fi
  if [ -n "$filter_status" ]; then
    jq_args+=(--arg st "$filter_status")
    jq_filter="$jq_filter | map(select(.status == \$st))"
  fi
  if [ -n "$filter_sourced" ]; then
    local sourced_bool="false"
    [ "$filter_sourced" = "true" ] && sourced_bool="true"
    jq_args+=(--argjson sourced "$sourced_bool")
    jq_filter="$jq_filter | map(select(.sourced == \$sourced))"
  fi

  local results
  results=$(jq -r "${jq_args[@]+"${jq_args[@]}"}" "$jq_filter" "$STAFF_REGISTRY")

  local count
  count=$(echo "$results" | jq 'length')

  if [ "$count" -eq 0 ]; then
    info "No projects found"
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
      
      local sourced_marker=""
      [ "$sourced" = "true" ] && sourced_marker="source" || sourced_marker="local"
      
      printf "%-24s %-10s %-12s ${status_color}%-10s${RESET} %-8s %s\n" \
        "$name" "$category" "$language" "$status" "$sourced_marker" "$description"
    done

  printf "\n${DIM}%d project(s)${RESET}\n" "$count"
}
