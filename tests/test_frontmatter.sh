# YAML scalar forms the parser must handle. Getting any of these wrong
# silently corrupts registry descriptions rather than failing loudly.

suite "frontmatter"

_fm_setup() {
  FM_DIR="$(mktemp -d "${TMPDIR:-/tmp}/staff-fm.XXXXXX")"
  # shellcheck source=/dev/null
  source "$REPO_ROOT/lib/staff/frontmatter.sh"
}
_fm_teardown() { rm -rf "$FM_DIR"; }

# _fm <name> <<'EOF' ... EOF   then read back with frontmatter_field
_fm() { cat > "$FM_DIR/$1.md"; }
_desc() { frontmatter_field "$FM_DIR/$1.md" description; }

_fm_setup

_fm plain <<'EOF'
---
name: plain
description: Simple unquoted text.
---
EOF
assert_eq "plain scalar" "Simple unquoted text." "$(_desc plain)"

# Regression: the old parser stripped a trailing quote unconditionally, so a
# plain scalar ending in a quotation lost its final character.
_fm trailing_quote <<'EOF'
---
name: trailing-quote
description: Use when users say "make me a GIF for Slack."
license: MIT
---
EOF
assert_eq "plain scalar ending in a quote keeps it" \
  'Use when users say "make me a GIF for Slack."' "$(_desc trailing_quote)"

# Regression: \" escapes were left as literal backslashes in the registry.
_fm dq_escapes <<'EOF'
---
name: dq-escapes
description: "Trigger on \"deck,\" \"slides,\" or a .pptx filename."
license: MIT
---
EOF
assert_eq "double-quoted escapes resolved" \
  'Trigger on "deck," "slides," or a .pptx filename.' "$(_desc dq_escapes)"

_fm sq <<'EOF'
---
name: sq
description: 'It''s single-quoted.'
---
EOF
assert_eq "single-quoted doubling resolved" "It's single-quoted." "$(_desc sq)"

_fm block_strip <<'EOF'
---
name: block-strip
description: |-
  First line of the block.
  Second line with "quotes" and a colon: here.
license: MIT
---
EOF
assert_eq "block scalar folded, terminated by indent" \
  'First line of the block. Second line with "quotes" and a colon: here.' "$(_desc block_strip)"

_fm folded <<'EOF'
---
name: folded
description: >-
  Folded text
  across lines.
---
EOF
assert_eq "folded block scalar" "Folded text across lines." "$(_desc folded)"

_fm continuation <<'EOF'
---
name: continuation
description: Starts here
  and continues indented.
license: MIT
---
EOF
assert_eq "plain scalar continuation folded" \
  "Starts here and continues indented." "$(_desc continuation)"

_fm dq_multiline <<'EOF'
---
name: dq-multiline
description: "Opens here
  and closes on the next line."
license: MIT
---
EOF
assert_eq "multi-line double-quoted scalar" \
  "Opens here and closes on the next line." "$(_desc dq_multiline)"

_fm hashes <<'EOF'
---
name: hashes
description: Supports C# and #hashtags.
---
EOF
assert_eq "# is not treated as a comment" "Supports C# and #hashtags." "$(_desc hashes)"

_fm nested <<'EOF'
---
name: nested
install:
  description: should not be picked up
description: The real one.
---
EOF
assert_eq "nested key of the same name ignored" "The real one." "$(_desc nested)"

printf 'No frontmatter here.\n' > "$FM_DIR/none.md"
assert_eq "file without frontmatter yields empty" "" "$(_desc none)"

_fm name_only <<'EOF'
---
name: name-only
---
EOF
if frontmatter_has_name_and_description "$FM_DIR/name_only.md"; then
  _report_fail "name without description is rejected" "expected non-zero"
else
  _report_pass "name without description is rejected"
fi
if frontmatter_has_name_and_description "$FM_DIR/plain.md"; then
  _report_pass "name plus description is accepted"
else
  _report_fail "name plus description is accepted" "expected zero"
fi

_fm_teardown
