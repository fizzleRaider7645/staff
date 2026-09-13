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
