#!/usr/bin/env bash

# Best-effort YAML frontmatter field extractor. Not a YAML parser — only
# used for registry display text (name/description), never for anything
# correctness-critical.
frontmatter_field() {
  local file="$1" key="$2"

  awk -v key="$key" '
    NR == 1 && $0 == "---" { in_fm = 1; next }
    in_fm && $0 == "---" { exit }
    in_fm {
      if (capturing) {
        if ($0 ~ /^[A-Za-z0-9_-]+:/ || $0 == "---") {
          exit
        }
        line = $0
        sub(/^[[:space:]]+/, "", line)
        if (value != "") value = value " "
        value = value line
        next
      }
      if ($0 ~ "^" key ":") {
        line = $0
        sub("^" key ":[[:space:]]*", "", line)
        gsub(/^["'"'"']|["'"'"']$/, "", line)
        if (line == "" || line == ">" || line == "|" || line == ">-" || line == "|-") {
          capturing = 1
          value = ""
          next
        }
        value = line
        exit
      }
    }
    END { print value }
  ' "$file"
}

# True (exit 0) if the file has YAML frontmatter defining both name: and description:
frontmatter_has_name_and_description() {
  local file="$1"
  local name description
  name=$(frontmatter_field "$file" "name")
  description=$(frontmatter_field "$file" "description")
  [ -n "$name" ] && [ -n "$description" ]
}
