# `staff init` output must build and install as-is. Both non-trivial
# templates previously scaffolded projects that could not.

suite "templates"

sandbox_init

# --- skill and agent: no build step, straight to install --------------------

run "$STAFF" init skill t-skill
assert_ok "init skill"
run "$STAFF" install t-skill
assert_ok "scaffolded skill installs"
assert_symlink_resolves "skill link resolves" "$HOME/.claude/skills/t-skill/SKILL.md"

run "$STAFF" init agent t-agent
assert_ok "init agent"
run "$STAFF" install t-agent
assert_ok "scaffolded agent installs"
assert_symlink_resolves "agent link resolves" "$HOME/.claude/agents/t-agent.md"

# --- tool: defaults to a language that has a template -----------------------
# `init tool` defaulted to ts, no tool-ts template exists, and the minimal
# fallback left install.binary empty, so install always failed.

run "$STAFF" init tool t-tool
assert_ok "init tool"
assert_output_contains "tool defaults to the python template" "Using template: tool-python"
assert_eq "install.binary is populated" "bin/run" \
  "$(jq -r '.install.binary' "$SB/repo/tools/t-tool/staff.json")"

# The wrapper is exec'd directly by install_tool, so the executable bit has
# to survive scaffolding.
if [ -x "$SB/repo/tools/t-tool/bin/run" ]; then
  _report_pass "scaffolded wrapper is executable"
else
  _report_fail "scaffolded wrapper is executable" "bin/run is not +x"
fi

run "$STAFF" install t-tool
assert_ok "scaffolded tool installs"
assert_file "tool wrapper created" "$HOME/.local/bin/t-tool"

# The whole point: the installed wrapper actually runs.
run "$HOME/.local/bin/t-tool"
if [ ! -x "$HOME/.local/bin/t-tool" ]; then
  _report_fail "installed tool wrapper executes" "wrapper missing or not executable"
elif [ "$LAST_STATUS" -eq 126 ] || [ "$LAST_STATUS" -eq 127 ] \
     || printf '%s' "$LAST_OUTPUT" | grep -q 'Permission denied'; then
  _report_fail "installed tool wrapper executes" "could not exec: $LAST_OUTPUT"
else
  _report_pass "installed tool wrapper executes"
fi

# A wrapper that runs from source must not need a build; build_first used to
# pip install into whatever Python happened to be ambient.
assert_eq "tool does not build on install" "false" \
  "$(jq -r '.install.build_first' "$SB/repo/tools/t-tool/staff.json")"

# --- mcp: build command has to install its own devDependencies --------------
# build.command was "npm run build", which skips npm install, so tsc was
# never present and both build and install failed on a fresh scaffold.

run "$STAFF" init mcp t-mcp
assert_ok "init mcp"
assert_contains "mcp build installs dependencies first" "npm install" \
  "$(jq -r '.build.command' "$SB/repo/mcps/t-mcp/staff.json")"
assert_eq "typescript is a devDependency" "true" \
  "$(jq -r 'has("devDependencies") and (.devDependencies | has("typescript"))' "$SB/repo/mcps/t-mcp/package.json")"

sandbox_cleanup
