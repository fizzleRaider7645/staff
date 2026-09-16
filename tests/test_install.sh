# Installing and uninstalling each category, and the collisions that used to
# destroy state silently.

suite "install"

sandbox_init

# --- scaffolding produces installable projects -----------------------------

run "$STAFF" init skill demo-skill
assert_ok "init skill"
run "$STAFF" init agent demo-agent
assert_ok "init agent"

run "$STAFF" install demo-skill
assert_ok "install skill"
assert_symlink_resolves "the skill directory is linked" "$HOME/.claude/skills/demo-skill"
assert_skill_file_reachable "SKILL.md is reachable through it" "$HOME/.claude/skills/demo-skill" "SKILL.md"

# --- migrating an install made by the old one-file layout -------------------
# Earlier versions created a real directory holding a symlinked SKILL.md.
# Reinstalling must replace that with a link to the skill directory.

rm -rf "$HOME/.claude/skills/demo-skill"
mkdir -p "$HOME/.claude/skills/demo-skill"
ln -s "$SB/repo/skills/demo-skill/SKILL.md" "$HOME/.claude/skills/demo-skill/SKILL.md"
run "$STAFF" install demo-skill
assert_ok "reinstall over the old layout succeeds"
assert_symlink_resolves "the old directory is replaced by a link" "$HOME/.claude/skills/demo-skill"

# A directory staff did not create must never be destroyed.
run "$STAFF" uninstall demo-skill
mkdir -p "$HOME/.claude/skills/handmade"
printf 'mine\n' > "$HOME/.claude/skills/handmade/notes.md"
mkdir -p "$SB/repo/skills/handmade"
cat > "$SB/repo/skills/handmade/staff.json" <<'JSON'
{"name":"handmade","language":"markdown","description":"clashes with a real dir",
 "status":"draft","version":"0.1.0","tags":[],"install":{"type":"skill","skill_file":"SKILL.md"}}
JSON
printf -- '---\nname: handmade\ndescription: d\n---\n' > "$SB/repo/skills/handmade/SKILL.md"
run "$STAFF" install handmade
assert_fails "refuses to clobber a directory staff did not create"
assert_output_contains "says why" "staff did not create"
assert_file "the user's own file survives" "$HOME/.claude/skills/handmade/notes.md"
rm -rf "$HOME/.claude/skills/handmade" "$SB/repo/skills/handmade"

run "$STAFF" install demo-skill

# --- agents are named after the project, not after agent_file --------------
# Every agent template ships an "agent.md". Linking by source filename meant
# the second install clobbered the first and uninstalling either destroyed
# the survivor.

run "$STAFF" init agent other-agent
run "$STAFF" install demo-agent
assert_ok "install first agent"
run "$STAFF" install other-agent
assert_ok "install second agent"

assert_symlink_resolves "first agent link named after project" "$HOME/.claude/agents/demo-agent.md"
assert_symlink_resolves "second agent link named after project" "$HOME/.claude/agents/other-agent.md"
assert_no_file "no shared agent.md" "$HOME/.claude/agents/agent.md"

run "$STAFF" uninstall demo-agent
assert_ok "uninstall first agent"
assert_no_file "first agent link removed" "$HOME/.claude/agents/demo-agent.md"
assert_symlink_resolves "second agent survives the uninstall" "$HOME/.claude/agents/other-agent.md"

# --- MCP servers land where Claude Code reads them -------------------------
# settings.json only carries enable/disable toggles; definitions written
# there are ignored.

mkdir -p "$SB/repo/mcps/demo-mcp"
cat > "$SB/repo/mcps/demo-mcp/staff.json" <<'JSON'
{"name":"demo-mcp","category":"mcp","language":"typescript","description":"demo","status":"draft",
 "version":"0.1.0","tags":[],
 "install":{"type":"mcp","mcp_config":{"command":"node","args":["${PROJECT_ROOT}/dist/index.js"]}}}
JSON

run "$STAFF" install demo-mcp --scope user
assert_ok "install mcp at user scope"
assert_file "user mcp config written to ~/.claude.json" "$HOME/.claude.json"
assert_eq "mcp registered under mcpServers" "node" \
  "$(jq -r '.mcpServers["demo-mcp"].command' "$HOME/.claude.json")"
assert_no_file "settings.json is not used for mcp definitions" "$HOME/.claude/settings.json"
assert_contains "PROJECT_ROOT is substituted" "/mcps/demo-mcp/dist/index.js" \
  "$(jq -r '.mcpServers["demo-mcp"].args[0]' "$HOME/.claude.json")"

mkdir -p "$SB/proj"
( cd "$SB/proj" && "$STAFF" install demo-mcp --scope project ) >/dev/null 2>&1
assert_file "project mcp config written to .mcp.json" "$SB/proj/.mcp.json"

# --- ${PROJECT_ROOT} is resolved everywhere, not only in args --------------
# ledger launches through "command": "${PROJECT_ROOT}/bin/ledger-mcp"; the
# old args-only substitution handed Claude Code the placeholder verbatim.

mkdir -p "$SB/repo/mcps/root-mcp/bin"
printf '#!/bin/sh\necho serving\n' > "$SB/repo/mcps/root-mcp/bin/serve"
printf '#!/bin/sh\necho cli "$@"\n' > "$SB/repo/mcps/root-mcp/bin/cli"
chmod +x "$SB/repo/mcps/root-mcp/bin/serve" "$SB/repo/mcps/root-mcp/bin/cli"
cat > "$SB/repo/mcps/root-mcp/staff.json" <<'JSON'
{"name":"root-mcp","language":"shell","description":"demo","status":"draft","version":"0.1.0","tags":[],
 "install":{"type":"mcp","binary":"bin/cli",
            "mcp_config":{"command":"${PROJECT_ROOT}/bin/serve","args":[],"env":{"ROOT":"${PROJECT_ROOT}"}}}}
JSON
run "$STAFF" install root-mcp
assert_ok "install an mcp whose command carries PROJECT_ROOT"
assert_contains "command is resolved" "/mcps/root-mcp/bin/serve" "$(jq -r '.mcpServers["root-mcp"].command' "$HOME/.claude.json")"
assert_contains "env is resolved" "/mcps/root-mcp" "$(jq -r '.mcpServers["root-mcp"].env.ROOT' "$HOME/.claude.json")"
case "$(jq -c '.mcpServers["root-mcp"]' "$HOME/.claude.json")" in
  *PROJECT_ROOT*) _report_fail "no placeholder survives" "still contains PROJECT_ROOT" ;;
  *) _report_pass "no placeholder survives" ;;
esac

# An MCP project that also ships a CLI gets the same wrapper a tool gets.
assert_file "install.binary on an mcp writes a wrapper" "$HOME/.local/bin/root-mcp"
run "$HOME/.local/bin/root-mcp" hello
assert_ok "the wrapper runs"
assert_output_contains "and reaches the binary" "cli hello"

# --- desktop scope: Claude Desktop / Cowork read their own config ----------

DESKTOP_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
run "$STAFF" install root-mcp --scope desktop
assert_ok "install at desktop scope"
assert_file "claude_desktop_config.json is written" "$DESKTOP_CFG"
assert_contains "desktop entry resolved" "/mcps/root-mcp/bin/serve" "$(jq -r '.mcpServers["root-mcp"].command' "$DESKTOP_CFG")"
assert_output_contains "tells the user to relaunch" "relaunch"
assert_eq "desktop scope is its own record" "1" \
  "$(jq '[.installations[] | select(.project == "root-mcp" and .scope == "desktop")] | length' "$HOME/.staff/installed.json")"

run "$STAFF" uninstall root-mcp --scope desktop
assert_ok "uninstall the desktop scope alone"
assert_eq "desktop entry removed" "null" "$(jq -r '.mcpServers["root-mcp"]' "$DESKTOP_CFG")"
assert_eq "user entry untouched" "true" "$(jq '.mcpServers["root-mcp"] != null' "$HOME/.claude.json")"
assert_file "the wrapper survives removing the desktop scope" "$HOME/.local/bin/root-mcp"

run "$STAFF" uninstall root-mcp
assert_ok "uninstall the rest"
assert_no_file "the wrapper goes with the user scope" "$HOME/.local/bin/root-mcp"

run "$STAFF" install demo-skill --scope desktop
assert_fails "desktop scope is refused for a skill"
assert_output_contains "and says why" "MCP servers only"
run "$STAFF" install root-mcp --scope nowhere
assert_fails "an unknown scope is refused"

# --- a project installed at two scopes keeps two records -------------------
# Keying installations by name alone lost the first record and orphaned
# whatever it had written.

assert_eq "both scopes tracked" "2" \
  "$(jq '[.installations[] | select(.project == "demo-mcp")] | length' "$HOME/.staff/installed.json")"

run "$STAFF" uninstall demo-mcp
assert_ok "uninstall clears every scope"
assert_eq "user scope entry removed" "null" "$(jq -r '.mcpServers["demo-mcp"]' "$HOME/.claude.json")"
assert_eq "project scope entry removed" "null" "$(jq -r '.mcpServers["demo-mcp"]' "$SB/proj/.mcp.json")"
assert_eq "no records left" "0" \
  "$(jq '[.installations[] | select(.project == "demo-mcp")] | length' "$HOME/.staff/installed.json")"

# --- error paths ------------------------------------------------------------

run "$STAFF" install no-such-project
assert_fails "installing an unknown project fails"
run "$STAFF" uninstall demo-skill --scope project
assert_fails "uninstalling at a scope it is not installed at fails"
run "$STAFF" uninstall no-such-project
assert_fails "uninstalling an unknown project fails"

sandbox_cleanup
