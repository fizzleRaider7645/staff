# `staff test` — running a project's own tests through the CLI, with the same
# trust boundary that guards build commands.

suite "staff test"

sandbox_init

# --- an explicit test.command in the manifest -------------------------------

mkdir -p "$SB/repo/tools/passing"
cat > "$SB/repo/tools/passing/staff.json" <<'JSON'
{"name":"passing","language":"shell","description":"passes","status":"draft","version":"0.1.0",
 "tags":[],"test":{"command":"exit 0"},"install":{"type":"tool","binary":"bin/run"}}
JSON
run "$STAFF" test passing
assert_ok "a passing project reports success"
assert_output_contains "names the command it ran" "exit 0"
assert_output_contains "reports the pass" "Tests passed: passing"

mkdir -p "$SB/repo/tools/failing"
cat > "$SB/repo/tools/failing/staff.json" <<'JSON'
{"name":"failing","language":"shell","description":"fails","status":"draft","version":"0.1.0",
 "tags":[],"test":{"command":"echo boom >&2; exit 1"},"install":{"type":"tool","binary":"bin/run"}}
JSON
run "$STAFF" test failing
assert_fails "a failing project exits non-zero"
assert_output_contains "reports the failure" "Tests failed: failing"

# --- auto-detection when the manifest declares nothing ----------------------

mkdir -p "$SB/repo/tools/inferred"
cat > "$SB/repo/tools/inferred/staff.json" <<'JSON'
{"name":"inferred","language":"python","description":"inferred","status":"draft",
 "version":"0.1.0","tags":[],"install":{"type":"tool","binary":"bin/run"}}
JSON
printf '[project]\nname = "inferred"\n' > "$SB/repo/tools/inferred/pyproject.toml"
run "$STAFF" test inferred
assert_output_contains "pyproject infers pytest" "python -m pytest"
rm -rf "$SB/repo/tools/inferred"

# package.json only infers when it actually declares a test script
mkdir -p "$SB/repo/tools/nojs"
cat > "$SB/repo/tools/nojs/staff.json" <<'JSON'
{"name":"nojs","language":"typescript","description":"no test script","status":"draft",
 "version":"0.1.0","tags":[],"install":{"type":"tool","binary":"bin/run"}}
JSON
printf '{"name":"nojs","scripts":{"build":"tsc"}}\n' > "$SB/repo/tools/nojs/package.json"
run "$STAFF" test nojs
assert_output_contains "a package.json without a test script is not testable" "No test command found"

# --- a project with no way to test is not a failure -------------------------

run "$STAFF" init skill untestable
run "$STAFF" test untestable
assert_eq "an untestable project exits 2, not 1" "2" "$LAST_STATUS"
assert_output_contains "says where to declare one" "Set test.command"

# --- --all -------------------------------------------------------------------

run "$STAFF" test --all
assert_fails "--all fails when any project fails"
assert_output_contains "counts the failure" "Failed: failing"
assert_output_contains "reports projects without tests separately" "with no tests"

rm -rf "$SB/repo/tools/failing"
run "$STAFF" test --all
assert_ok "--all passes once the failing project is gone"
assert_output_contains "summarises passes and skips" "passed"

run "$STAFF" test passing --all
assert_fails "a project name and --all together is rejected"
run "$STAFF" test
assert_fails "no project and no --all is rejected"
run "$STAFF" test no-such-project
assert_fails "an unknown project is rejected"

# --- sourced projects: a test command is third-party code too ---------------

CANARY="$SB/test-pwned"
EXT="$SB/hostile"
mkdir -p "$EXT/tools/evil/bin"
printf '#!/bin/sh\necho evil\n' > "$EXT/tools/evil/bin/run"
chmod +x "$EXT/tools/evil/bin/run"
cat > "$EXT/tools/evil/staff.json" <<JSON
{"name":"evil","language":"shell","description":"d","status":"draft","version":"0.1.0","tags":[],
 "build":{"command":"touch '$CANARY.build'"},
 "test":{"command":"touch '$CANARY'"},
 "install":{"type":"tool","binary":"bin/run"}}
JSON
run "$STAFF" add_source hostile "$EXT" --no-install
assert_ok "register the hostile source"

run "$STAFF" test evil
assert_fails "a sourced test command is refused by default"
assert_no_file "the test command did not execute" "$CANARY"
assert_output_contains "explains the refusal" "Refusing to run a test command"
assert_output_contains "names the right opt-in" "--allow-test"

run "$STAFF" test --all
assert_no_file "--all does not bypass the refusal" "$CANARY"

run "$STAFF" test evil --allow-test
assert_ok "--allow-test permits it"
assert_file "the test command ran once permitted" "$CANARY"

# the build gate still uses its own flag and wording
run "$STAFF" build evil
assert_fails "build is still refused separately"
assert_output_contains "build refusal still says build" "Refusing to run a build command"
assert_output_contains "build names its own flag" "--allow-build"
assert_no_file "the build command did not run" "$CANARY.build"

sandbox_cleanup
