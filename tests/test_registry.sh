# Registry rebuild, the two-file split, and the failure modes that used to
# report success while destroying the index.

suite "registry"

sandbox_init

run "$STAFF" init skill local-skill
assert_ok "init a local project"

# --- the split: repo projects committed, sourced projects machine-local ----

EXT="$SB/ext"
make_source_repo "$EXT" 'alpha-skill:Does alpha things.'
run "$STAFF" add_source extrepo "$EXT"
assert_ok "add a source"

assert_eq "registry.json holds only local projects" "local-skill" \
  "$(jq -r '[.projects[].name] | join(",")' "$SB/repo/registry.json")"
assert_eq "sources/registry.json holds sourced projects" "alpha-skill" \
  "$(jq -r '[.projects[].name] | join(",")' "$SB/repo/sources/registry.json")"

run "$STAFF" list
assert_output_contains "list unions both indexes (local)" "local-skill"
assert_output_contains "list unions both indexes (sourced)" "alpha-skill"

# --- a broken source symlink must not silently empty the index -------------
# This previously printed "ok ... 0 project(s) indexed" and exited 0.

cp "$SB/repo/sources/registry.json" "$SB/sources-registry.before"
mv "$EXT" "$SB/ext-moved"

run "$STAFF" registry rebuild
assert_fails "rebuild fails when a source link does not resolve"
assert_output_contains "names the broken bundle" "extrepo"
if cmp -s "$SB/repo/sources/registry.json" "$SB/sources-registry.before"; then
  _report_pass "index left untouched on failure"
else
  _report_fail "index left untouched on failure" "sources/registry.json was rewritten"
fi

run "$STAFF" doctor
assert_output_contains "doctor reports the broken link" "does not resolve"

mv "$SB/ext-moved" "$EXT"
run "$STAFF" registry rebuild
assert_ok "rebuild recovers once the path is restored"

# --- duplicate names ---------------------------------------------------------
# find_project returns every match, so two projects sharing a name make
# install build a nonsense path out of both records.

mkdir -p "$SB/repo/tools/local-skill"
cat > "$SB/repo/tools/local-skill/staff.json" <<'JSON'
{"name":"local-skill","category":"tool","language":"python","description":"clashing name",
 "status":"draft","version":"0.1.0","tags":[],"install":{"type":"tool","binary":"bin/run"}}
JSON

cp "$SB/repo/registry.json" "$SB/registry.before"
run "$STAFF" registry rebuild
assert_fails "rebuild rejects duplicate project names"
assert_output_contains "names the duplicate" "local-skill"
assert_output_contains "shows both paths" "tools/local-skill"
if cmp -s "$SB/repo/registry.json" "$SB/registry.before"; then
  _report_pass "registry left untouched on duplicate"
else
  _report_fail "registry left untouched on duplicate" "registry.json was rewritten"
fi

rm -rf "$SB/repo/tools/local-skill"
run "$STAFF" registry rebuild
assert_ok "rebuild recovers once the clash is gone"

# --- list filters ------------------------------------------------------------
# Category directories are plural, registry values singular; --category skills
# used to return nothing at all.

run "$STAFF" list --category skills
assert_ok "plural category accepted"
assert_output_contains "plural category matches" "local-skill"
run "$STAFF" list --category skill
assert_output_contains "singular category matches" "local-skill"

run "$STAFF" list --category bogus
assert_fails "unknown category rejected"
assert_output_contains "lists valid categories" "Valid categories"
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
assert_output_contains "unmatched language hints at real values" "Languages in the registry"

sandbox_cleanup
