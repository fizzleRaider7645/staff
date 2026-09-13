# doctor's installation audit. Installations are keyed by (project, scope),
# so the audit has to walk records rather than project names.

suite "doctor"

sandbox_init

run "$STAFF" doctor
assert_ok "doctor exits 0 on a clean install"
assert_output_contains "reports a clean bill" "All checks passed"

# --- a healthy skill ---------------------------------------------------------

run "$STAFF" init skill solo-skill
run "$STAFF" install solo-skill
run "$STAFF" doctor
assert_ok "still clean with one skill installed"
assert_output_contains "reports the skill" "solo-skill: symlink OK"

# --- a broken symlink must be caught and must fail the exit code ------------

rm -f "$HOME/.claude/skills/solo-skill/SKILL.md"
ln -s /nonexistent/target "$HOME/.claude/skills/solo-skill/SKILL.md"
run "$STAFF" doctor
assert_fails "doctor exits non-zero when it finds issues"
assert_output_contains "reports the broken link" "broken symlink"
assert_output_contains "counts the issue" "1 issue(s) found"

run "$STAFF" uninstall solo-skill
run "$STAFF" install solo-skill
run "$STAFF" doctor
assert_ok "clean again after reinstall"

# --- the same project at two scopes -----------------------------------------
# Each scope is its own record. Selecting by project name returned both at
# once, which double-reported every link.

mkdir -p "$SB/proj"
( cd "$SB/proj" && "$STAFF" install solo-skill --scope project ) >/dev/null 2>&1
assert_eq "two records tracked" "2" \
  "$(jq '[.installations[] | select(.project == "solo-skill")] | length' "$HOME/.staff/installed.json")"

run "$STAFF" doctor
assert_ok "doctor clean with the project installed twice"
assert_eq "each scope reported exactly once" "2" \
  "$(printf '%s\n' "$LAST_OUTPUT" | grep -c 'solo-skill.*symlink OK')"
assert_output_contains "scope disambiguates the label" "solo-skill (user)"
assert_output_contains "project scope labelled too" "solo-skill (project)"

# Breaking only the project-scope copy must be attributed to that scope.
rm -f "$SB/proj/.claude/skills/solo-skill/SKILL.md"
ln -s /nonexistent/target "$SB/proj/.claude/skills/solo-skill/SKILL.md"
run "$STAFF" doctor
assert_fails "broken link at one scope fails doctor"
assert_eq "exactly one broken link reported" "1" \
  "$(printf '%s\n' "$LAST_OUTPUT" | grep -c 'broken symlink')"
assert_output_contains "attributed to the project scope" "solo-skill (project): broken symlink"

run "$STAFF" uninstall solo-skill
assert_ok "uninstall clears both scopes"

# --- MCP config keys are actually checked ------------------------------------
# With two scope records, .target collapsed to two lines, so the config-key
# check silently matched no file and doctor reported nothing at all.

mkdir -p "$SB/repo/mcps/audit-mcp"
cat > "$SB/repo/mcps/audit-mcp/staff.json" <<'JSON'
{"name":"audit-mcp","category":"mcp","language":"typescript","description":"d","status":"draft",
 "version":"0.1.0","tags":[],
 "install":{"type":"mcp","mcp_config":{"command":"node","args":["${PROJECT_ROOT}/dist/i.js"]}}}
JSON
run "$STAFF" install audit-mcp --scope user
( cd "$SB/proj" && "$STAFF" install audit-mcp --scope project ) >/dev/null 2>&1

run "$STAFF" doctor
assert_ok "doctor clean with an mcp at two scopes"
assert_eq "both mcp config keys checked" "2" \
  "$(printf '%s\n' "$LAST_OUTPUT" | grep -c 'audit-mcp.*config key OK')"

# Removing the key behind doctor's back must be caught, not skipped.
jq 'del(.mcpServers["audit-mcp"])' "$HOME/.claude.json" > "$HOME/.claude.json.tmp"
mv "$HOME/.claude.json.tmp" "$HOME/.claude.json"
run "$STAFF" doctor
assert_fails "missing mcp config key fails doctor"
assert_output_contains "names the missing key" "missing config key"

sandbox_cleanup
