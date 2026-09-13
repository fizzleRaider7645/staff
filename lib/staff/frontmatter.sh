#!/usr/bin/env bash

# Extract a scalar field from a file's YAML frontmatter.
#
# Not a general YAML parser — it reads one top-level scalar out of the leading
# --- block, which is all the registry needs (name, description). It does
# handle the four scalar forms that appear in real skill and agent files,
# because getting them wrong silently corrupts registry text:
#
#   key: plain text          plain, folded across more-indented continuations
#   key: "text with \"q\""   double-quoted, escapes resolved
#   key: 'it''s here'        single-quoted, '' resolved to '
#   key: |- / >- / | / >     block scalar, terminated by indentation
#
# Multi-line values are folded to a single space-joined line: these feed a
# one-line registry description, not a document.
frontmatter_field() {
  local file="$1" key="$2"

  awk -v key="$key" '
    function ltrim(s) { sub(/^[ \t]+/, "", s); return s }
    function rtrim(s) { sub(/[ \t]+$/, "", s); return s }
    function trim(s)  { return rtrim(ltrim(s)) }

    function indent_of(s,   i) {
      i = 0
      while (i < length(s)) {
        c = substr(s, i + 1, 1)
        if (c != " " && c != "\t") break
        i++
      }
      return i
    }

    # First unescaped double quote, or 0.
    function find_close_dq(s,   i, c, n) {
      n = length(s); i = 1
      while (i <= n) {
        c = substr(s, i, 1)
        if (c == "\\") { i += 2; continue }
        if (c == DQ) return i
        i++
      }
      return 0
    }

    # First single quote not doubled, or 0.
    function find_close_sq(s,   i, c, n) {
      n = length(s); i = 1
      while (i <= n) {
        c = substr(s, i, 1)
        if (c == SQ) {
          if (i < n && substr(s, i + 1, 1) == SQ) { i += 2; continue }
          return i
        }
        i++
      }
      return 0
    }

    function unescape_dq(s,   out, i, c, n) {
      out = ""; n = length(s); i = 1
      while (i <= n) {
        c = substr(s, i, 1)
        if (c == "\\" && i < n) {
          i++
          c = substr(s, i, 1)
          if (c == "n")      out = out " "
          else if (c == "t") out = out " "
          else if (c == "r") out = out ""
          else               out = out c
        } else {
          out = out c
        }
        i++
      }
      return out
    }

    function unescape_sq(s,   out, i, c, n) {
      out = ""; n = length(s); i = 1
      while (i <= n) {
        c = substr(s, i, 1)
        if (c == SQ && i < n && substr(s, i + 1, 1) == SQ) { out = out SQ; i += 2; continue }
        out = out c; i++
      }
      return out
    }

    BEGIN {
      SQ = sprintf("%c", 39)
      DQ = sprintf("%c", 34)
      state = "seek"; value = ""; got = 0; block_indent = -1
    }

    NR == 1 {
      if ($0 != "---") exit
      in_fm = 1
      next
    }

    {
      if (!in_fm) exit

      if (state == "seek") {
        if ($0 == "---" || $0 == "...") exit
        if (indent_of($0) != 0) next
        if ($0 !~ "^" key ":") next

        rest = ltrim(substr($0, length(key) + 2))

        if (rest == "" || rest ~ /^[|>][-+]?[0-9]*$/) {
          state = "block"
          next
        }
        if (substr(rest, 1, 1) == DQ) {
          body = substr(rest, 2)
          p = find_close_dq(body)
          if (p > 0) { value = unescape_dq(substr(body, 1, p - 1)); got = 1; exit }
          value = body; state = "dq"; next
        }
        if (substr(rest, 1, 1) == SQ) {
          body = substr(rest, 2)
          p = find_close_sq(body)
          if (p > 0) { value = unescape_sq(substr(body, 1, p - 1)); got = 1; exit }
          value = body; state = "sq"; next
        }
        value = rest; state = "plain"; next
      }

      if (state == "plain") {
        if ($0 == "---" || $0 == "..." || trim($0) == "" || indent_of($0) == 0) { got = 1; exit }
        value = value " " trim($0)
        next
      }

      if (state == "block") {
        if ($0 == "---" || $0 == "...") { got = 1; exit }
        if (trim($0) == "") next
        ind = indent_of($0)
        if (ind == 0) { got = 1; exit }
        if (block_indent < 0) block_indent = ind
        line = trim(substr($0, block_indent + 1))
        if (value != "") value = value " "
        value = value line
        next
      }

      if (state == "dq") {
        p = find_close_dq($0)
        if (p > 0) {
          value = unescape_dq(value " " trim(substr($0, 1, p - 1)))
          got = 1; exit
        }
        value = value " " trim($0)
        next
      }

      if (state == "sq") {
        p = find_close_sq($0)
        if (p > 0) {
          value = unescape_sq(value " " trim(substr($0, 1, p - 1)))
          got = 1; exit
        }
        value = value " " trim($0)
        next
      }
    }

    END {
      if (got || value != "") print trim(value)
    }
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
