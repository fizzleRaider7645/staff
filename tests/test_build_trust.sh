# build.command comes out of a staff.json. For a project ingested from an
# external repo, that file was written by someone else, so running it must
# be an explicit choice rather than a side effect of `staff install`.

suite "build-trust"

sandbox_init

CANARY="$SB/pwned"

# --- a local project builds without ceremony --------------------------------
# The user wrote it; requiring a flag here would just be noise.

mkdir -p "$SB/repo/tools/local-tool/bin"
printf '#!/bin/sh\necho local-tool\n' > "$SB/repo/tools/local-tool/bin/run"
chmod +x "$SB/repo/tools/local-tool/bin/run"
cat > "$SB/repo/tools/local-tool/staff.json" <<JSON
{"name":"local-tool","category":"tool","language":"shell","description":"d","status":"draft",
 "version":"0.1.0","tags":[],
 "build":{"command":"echo built > '$SB/local-built'"},
 "install":{"type":"tool","binary":"bin/run","build_first":true}}
JSON
run "$STAFF" registry rebuild
run "$STAFF" install local-tool
assert_ok "local project installs and builds"
assert_file "local build command ran" "$SB/local-built"

# --- a sourced project's build command is refused by default ----------------

EXT="$SB/hostile"
mkdir -p "$EXT/tools/evil-tool/bin"
printf '#!/bin/sh\necho evil\n' > "$EXT/tools/evil-tool/bin/run"
chmod +x "$EXT/tools/evil-tool/bin/run"
cat > "$EXT/tools/evil-tool/staff.json" <<JSON
{"name":"evil-tool","category":"tool","language":"shell","description":"d","status":"draft",
 "version":"0.1.0","tags":[],
 "build":{"command":"touch '$CANARY'"},
 "install":{"type":"tool","binary":"bin/run","build_first":true}}
JSON

run "$STAFF" add_source hostile "$EXT" --no-install
assert_ok "hostile source registers without installing"
assert_no_file "add_source --no-install runs no build" "$CANARY"

run "$STAFF" install evil-tool
assert_fails "installing a sourced project refuses its build command"
assert_no_file "the build command did not execute" "$CANARY"
assert_output_contains "explains the refusal" "Refusing to run a build command"
assert_output_contains "shows the exact command it refused" "$CANARY"
assert_output_contains "names the opt-in" "--allow-build"

run "$STAFF" build evil-tool
assert_fails "staff build refuses it too"
assert_no_file "still did not execute" "$CANARY"

# --- explicit consent lets it through ---------------------------------------

run "$STAFF" install evil-tool --allow-build
assert_ok "--allow-build permits the build"
assert_file "build ran once permitted" "$CANARY"

# --- auto-install on add_source must not be a bypass ------------------------
# add_source installs by default, which would otherwise run a third party's
# build command with no prompt at all.

rm -f "$CANARY"
run "$STAFF" remove_source hostile
assert_ok "drop the source"

run "$STAFF" add_source hostile2 "$EXT"
assert_no_file "auto-install does not run a sourced build command" "$CANARY"

# The refusal must not discard the bundle: a source with one build-requiring
# project should still register everything it discovered.
assert_file "the bundle is still registered" "$SB/repo/sources/hostile2/source.toml"
assert_output_contains "the skipped project is named" "Not installed: evil-tool"
assert_output_contains "tells the user how to retry" "staff install evil-tool"

run "$STAFF" list --sourced true
assert_output_contains "the project is still in the registry" "evil-tool"

run "$STAFF" install evil-tool --allow-build
assert_ok "it can be installed afterwards with consent"
assert_file "build ran on the explicit retry" "$CANARY"

sandbox_cleanup
