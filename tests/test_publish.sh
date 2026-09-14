# `staff publish` exports a project as a Claude Code plugin: a self-contained
# copy under plugins/<name>/ in the loader's layout, listed in a repo-level
# marketplace.json. The tests open what was produced rather than trusting the
# exit code — a plugin that loads without its supporting files is the same
# silent failure the installer used to have.

suite "publish"

sandbox_init

PLUGINS="$SB/repo/plugins"
MARKET="$SB/repo/.claude-plugin/marketplace.json"

# --- a skill is published whole ---------------------------------------------

run "$STAFF" init skill p-skill
mkdir -p "$SB/repo/skills/p-skill/reference"
printf 'guide\n' > "$SB/repo/skills/p-skill/reference/guide.md"

run "$STAFF" publish p-skill
assert_ok "publish a skill"
assert_file "plugin.json is written" "$PLUGINS/p-skill/.claude-plugin/plugin.json"
assert_eq "plugin.json names the plugin" "p-skill" \
  "$(jq -r '.name' "$PLUGINS/p-skill/.claude-plugin/plugin.json")"
assert_eq "plugin.json carries the project version" "0.1.0" \
  "$(jq -r '.version' "$PLUGINS/p-skill/.claude-plugin/plugin.json")"
assert_file "SKILL.md lands under skills/<name>/" "$PLUGINS/p-skill/skills/p-skill/SKILL.md"
assert_skill_file_reachable "supporting files come with it" "$PLUGINS/p-skill/skills/p-skill" "reference/guide.md"
assert_eq "nothing in the plugin is a symlink" "" "$(find "$PLUGINS/p-skill" -type l)"

assert_file "marketplace.json is created" "$MARKET"
assert_eq "marketplace named after the root directory" "repo" "$(jq -r '.name' "$MARKET")"
assert_eq "plugin listed with a relative source" "./plugins/p-skill" \
  "$(jq -r '.plugins[] | select(.name == "p-skill") | .source' "$MARKET")"

run "$STAFF" list
assert_eq "the published copy is not discovered as a second project" "1" \
  "$(printf '%s\n' "$LAST_OUTPUT" | grep -c '^p-skill')"

# --- republishing replaces the snapshot and updates one entry ---------------

printf 'stale\n' > "$PLUGINS/p-skill/skills/p-skill/old.md"
jq '(.plugins[] | select(.name == "p-skill")).category = "development"
    | .description = "edited by hand"' "$MARKET" > "$MARKET.tmp" \
  && mv "$MARKET.tmp" "$MARKET"
jq '.version = "0.2.0"' "$SB/repo/skills/p-skill/staff.json" > "$SB/repo/skills/p-skill/staff.json.tmp" \
  && mv "$SB/repo/skills/p-skill/staff.json.tmp" "$SB/repo/skills/p-skill/staff.json"

run "$STAFF" publish p-skill
assert_ok "republish"
assert_no_file "a file dropped from the project leaves the plugin" "$PLUGINS/p-skill/skills/p-skill/old.md"
assert_eq "still one marketplace entry" "1" "$(jq '[.plugins[] | select(.name == "p-skill")] | length' "$MARKET")"
assert_eq "entry version follows the project" "0.2.0" \
  "$(jq -r '.plugins[] | select(.name == "p-skill") | .version' "$MARKET")"
assert_eq "hand-added marketplace fields survive" "development" \
  "$(jq -r '.plugins[] | select(.name == "p-skill") | .category' "$MARKET")"
assert_eq "the marketplace's own description survives" "edited by hand" "$(jq -r '.description' "$MARKET")"

# --- agents are named after the project ---------------------------------------

run "$STAFF" init agent p-agent
run "$STAFF" publish p-agent
assert_ok "publish an agent"
assert_file "agent lands as agents/<name>.md" "$PLUGINS/p-agent/agents/p-agent.md"
assert_no_file "not as the template's agent.md" "$PLUGINS/p-agent/agents/agent.md"

# --- MCP config is rewritten for the plugin root ------------------------------

mkdir -p "$SB/repo/mcps/p-mcp/dist"
printf 'server\n' > "$SB/repo/mcps/p-mcp/dist/index.js"
cat > "$SB/repo/mcps/p-mcp/staff.json" <<'JSON'
{"name":"p-mcp","language":"typescript","description":"demo","status":"draft","version":"0.1.0","tags":[],
 "install":{"type":"mcp","mcp_config":{"command":"node","args":["${PROJECT_ROOT}/dist/index.js"],
                                       "env":{"ROOT":"${PROJECT_ROOT}"}}}}
JSON
run "$STAFF" publish p-mcp
assert_ok "publish an mcp"
assert_file ".mcp.json is written" "$PLUGINS/p-mcp/.mcp.json"
assert_eq "PROJECT_ROOT becomes CLAUDE_PLUGIN_ROOT in args" '${CLAUDE_PLUGIN_ROOT}/dist/index.js' \
  "$(jq -r '.mcpServers["p-mcp"].args[0]' "$PLUGINS/p-mcp/.mcp.json")"
assert_eq "and in env values" '${CLAUDE_PLUGIN_ROOT}' \
  "$(jq -r '.mcpServers["p-mcp"].env.ROOT' "$PLUGINS/p-mcp/.mcp.json")"
assert_file "the server's files ship with it" "$PLUGINS/p-mcp/dist/index.js"

# The marketplace is distributed by cloning, so whatever .gitignore hides
# from the clone is missing from the installed plugin. dist/ is the usual case.
printf 'dist/\n' > "$SB/repo/.gitignore"
git_init_commit "$SB/repo"
run "$STAFF" publish p-mcp
assert_ok "publishing into a git repo still succeeds"
assert_output_contains "warns that ignored files will not reach a clone" "ignored by .gitignore"
assert_output_contains "names the file" "plugins/p-mcp/dist/index.js"

# --- a tool ships behind its own skill ---------------------------------------

run "$STAFF" init tool p-tool
mkdir -p "$SB/repo/tools/p-tool/skill" "$SB/repo/tools/p-tool/src/__pycache__"
printf -- '---\nname: p-tool\ndescription: d\n---\nSee reference.md\n' > "$SB/repo/tools/p-tool/skill/SKILL.md"
printf 'ref\n' > "$SB/repo/tools/p-tool/skill/reference.md"
printf 'x\n' > "$SB/repo/tools/p-tool/src/__pycache__/cli.pyc"

run "$STAFF" publish p-tool
assert_ok "publish a tool"
assert_file "the project's skill lands under skills/<name>/" "$PLUGINS/p-tool/skills/p-tool/SKILL.md"
assert_skill_file_reachable "with its supporting files" "$PLUGINS/p-tool/skills/p-tool" "reference.md"
assert_no_file "and not also at skill/" "$PLUGINS/p-tool/skill"
assert_file "the binary ships" "$PLUGINS/p-tool/bin/run"
if [ -x "$PLUGINS/p-tool/bin/run" ]; then
  _report_pass "the binary is still executable"
else
  _report_fail "the binary is still executable" "bin/run lost its mode"
fi
assert_no_file "caches are left out" "$PLUGINS/p-tool/src/__pycache__"
assert_file "source ships" "$PLUGINS/p-tool/src/p_tool/cli.py"

# Without a skill of its own the tool still publishes, with a generated one.
run "$STAFF" init tool p-plain
run "$STAFF" publish p-plain
assert_ok "a tool with no skill publishes"
assert_output_contains "says a skill was generated" "generating a minimal one"
assert_contains "the generated skill runs the binary from the plugin root" '${CLAUDE_PLUGIN_ROOT}/bin/run' \
  "$(cat "$PLUGINS/p-plain/skills/p-plain/SKILL.md")"

# --- what cannot be a plugin, and what is malformed --------------------------

mkdir -p "$SB/repo/harnesses/p-harness"
cat > "$SB/repo/harnesses/p-harness/staff.json" <<'JSON'
{"name":"p-harness","language":"python","description":"d","status":"draft","version":"0.1.0","tags":[],
 "install":{"type":"harness"}}
JSON
run "$STAFF" publish p-harness
assert_fails "an install type with no plugin shape is refused"
assert_output_contains "and says so" "no plugin equivalent"
assert_no_file "nothing is written for it" "$PLUGINS/p-harness"

jq '.version = "1.0"' "$SB/repo/skills/p-skill/staff.json" > "$SB/repo/skills/p-skill/staff.json.tmp" \
  && mv "$SB/repo/skills/p-skill/staff.json.tmp" "$SB/repo/skills/p-skill/staff.json"
run "$STAFF" publish p-skill
assert_fails "a non-semver version is refused"
assert_eq "the previous snapshot is untouched" "0.2.0" \
  "$(jq -r '.version' "$PLUGINS/p-skill/.claude-plugin/plugin.json")"
assert_eq "no staging directory is left behind" "" "$(find "$PLUGINS" -maxdepth 1 -name '.p-skill.*')"

run "$STAFF" publish no-such-project
assert_fails "an unknown project fails"

# --- sourced projects: same trust gate as install ----------------------------

EXT="$SB/ext"
make_source_repo "$EXT" 'ext-skill:From outside.'
CANARY="$SB/pwned"
mkdir -p "$EXT/tools/ext-tool/bin"
printf '#!/bin/sh\necho ext\n' > "$EXT/tools/ext-tool/bin/run"
chmod +x "$EXT/tools/ext-tool/bin/run"
cat > "$EXT/tools/ext-tool/staff.json" <<JSON
{"name":"ext-tool","language":"shell","description":"d","status":"draft","version":"0.1.0","tags":[],
 "build":{"command":"touch '$CANARY'"},
 "install":{"type":"tool","binary":"bin/run","build_first":true}}
JSON
run "$STAFF" add_source ext "$EXT" --no-install

run "$STAFF" publish ext-skill
assert_ok "a sourced skill publishes"
assert_skill_file_reachable "with its supporting files" "$PLUGINS/ext-skill/skills/ext-skill" "reference/guide.md"

run "$STAFF" publish ext-tool
assert_fails "a sourced project's build command is refused"
assert_no_file "and did not run" "$CANARY"
assert_no_file "nothing is published" "$PLUGINS/ext-tool"

run "$STAFF" publish ext-tool --allow-build
assert_ok "--allow-build permits it"
assert_file "the build ran" "$CANARY"

# --- publishing into a separate marketplace ----------------------------------

run "$STAFF" publish p-agent --out "$SB/market"
assert_ok "publish with --out"
assert_file "plugin written under the other root" "$SB/market/plugins/p-agent/agents/p-agent.md"
assert_eq "marketplace named after that root" "market" "$(jq -r '.name' "$SB/market/.claude-plugin/marketplace.json")"

run "$STAFF" publish p-agent --out "$SB/market" --marketplace other-name
assert_fails "renaming an existing marketplace is refused"
assert_output_contains "explains" "already names this marketplace"

# --- doctor knows when a snapshot is behind ----------------------------------

jq '.version = "0.3.0"' "$SB/repo/skills/p-skill/staff.json" > "$SB/repo/skills/p-skill/staff.json.tmp" \
  && mv "$SB/repo/skills/p-skill/staff.json.tmp" "$SB/repo/skills/p-skill/staff.json"
run "$STAFF" doctor
assert_fails "doctor flags a published plugin behind its project"
assert_output_contains "and says how to fix it" "staff publish p-skill"

run "$STAFF" publish p-skill
run "$STAFF" doctor
assert_ok "clean once republished"
assert_output_contains "reports the match" "p-skill: v0.3.0 matches its project"

sandbox_cleanup
