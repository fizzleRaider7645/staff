# Project discovery. There is no index file: every command walks the tree,
# so the whole "the registry disagrees with the disk" failure class is gone
# by construction rather than guarded against.

suite "discovery"

sandbox_init

run "$STAFF" init skill local-skill
assert_ok "init a local project"

EXT="$SB/ext"
make_source_repo "$EXT" 'alpha-skill:Does alpha things.'
run "$STAFF" add_source extrepo "$EXT"
assert_ok "add a source"

# --- discovery is live -------------------------------------------------------

run "$STAFF" list
assert_ok "list works with no index file"
assert_output_contains "finds the local project" "local-skill"
assert_output_contains "finds the sourced project" "alpha-skill"

assert_no_file "no registry.json is written" "$SB/repo/registry.json"
assert_no_file "no sourced index is written" "$SB/repo/sources/registry.json"

run "$STAFF" registry rebuild
assert_fails "the registry subcommand is gone"

# A manifest dropped in by hand is visible immediately, with nothing to run.
mkdir -p "$SB/repo/tools/hand-made"
cat > "$SB/repo/tools/hand-made/staff.json" <<'JSON'
{"name":"hand-made","category":"tool","language":"shell","description":"added by hand",
 "status":"draft","version":"0.1.0","tags":[],"install":{"type":"tool","binary":"bin/run"}}
JSON
run "$STAFF" list
assert_output_contains "a new manifest needs no rebuild step" "hand-made"

# Equally, deleting one takes effect at once.
rm -rf "$SB/repo/tools/hand-made"
run "$STAFF" list
case "$LAST_OUTPUT" in
  *hand-made*) _report_fail "a removed manifest disappears at once" "still listed" ;;
  *) _report_pass "a removed manifest disappears at once" ;;
esac

# --- a broken source warns, but does not take everything else down ----------
# There is no index to empty, so skipping is safe as long as it is loud.

mv "$EXT" "$SB/ext-moved"
run "$STAFF" list
assert_ok "list still works with an unresolvable source"
assert_output_contains "warns about the broken bundle" "does not resolve"
assert_output_contains "unrelated projects still listed" "local-skill"

run "$STAFF" doctor
assert_fails "doctor reports the broken source"

mv "$SB/ext-moved" "$EXT"
run "$STAFF" list
assert_output_contains "recovers when the path returns" "alpha-skill"

# --- duplicate names are caught where they matter ---------------------------
# Two projects answering to one name make `staff install <name>` ambiguous.

mkdir -p "$SB/repo/tools/local-skill"
cat > "$SB/repo/tools/local-skill/staff.json" <<'JSON'
{"name":"local-skill","category":"tool","language":"python","description":"clashing name",
 "status":"draft","version":"0.1.0","tags":[],"install":{"type":"tool","binary":"bin/run"}}
JSON

run "$STAFF" install local-skill
assert_fails "installing an ambiguous name fails"
assert_output_contains "says it is ambiguous" "Ambiguous project name"
assert_output_contains "shows the first path" "skills/local-skill"
assert_output_contains "shows the second path" "tools/local-skill"

run "$STAFF" doctor
assert_fails "doctor flags the duplicate"
assert_output_contains "doctor names it" "Duplicate project name"

rm -rf "$SB/repo/tools/local-skill"
run "$STAFF" install local-skill
assert_ok "installs again once the clash is gone"

# --- list filters ------------------------------------------------------------

run "$STAFF" list --category skills
assert_ok "plural category accepted"
assert_output_contains "plural category matches" "local-skill"
run "$STAFF" list --category skill
assert_output_contains "singular category matches" "local-skill"

run "$STAFF" list --category bogus
assert_fails "unknown category rejected"
run "$STAFF" list --status bogus
assert_fails "unknown status rejected"
run "$STAFF" list --sourced yes
assert_fails "non-boolean --sourced rejected"
run "$STAFF" list --category
assert_fails "option without a value rejected"

run "$STAFF" list --sourced true
assert_output_contains "--sourced true selects sourced projects" "alpha-skill"
run "$STAFF" list --sourced false
assert_output_contains "--sourced false selects local projects" "local-skill"

run "$STAFF" list --language nope
assert_ok "unmatched language is not an error"
assert_output_contains "unmatched language hints at real values" "Languages"

sandbox_cleanup
