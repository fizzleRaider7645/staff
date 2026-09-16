# Handover — 2026-09-16

`main` @ the "Publish ledger as a plugin" commit, pushed, clean tree. CI: CLI
suite on Linux and macOS plus `staff test --all`; shellcheck advisory and red.

## State

| | |
|---|---|
| Commands | `list, add_source, update_source, remove_source, install, uninstall, build, test, init, publish, doctor` |
| Tests | 292 CLI (`./tests/run.sh`), 154 sdlc, 38 token-count, 118 ledger |
| Projects | `staff` (skill), `sdlc` (harness), `token-count` (tool), **`ledger` (mcp)** |
| Published | `token-count`, `ledger` in `.claude-plugin/marketplace.json` |
| Empty categories | `agents/` |
| Installed here | `ledger` at user scope (`~/.claude.json`, `~/.local/bin/ledger`) and desktop scope (`claude_desktop_config.json`, Desktop not yet relaunched) |

## ledger — what exists

`mcps/ledger`: SimpleFIN Bridge → `~/.ledger/ledger.db`; stdlib CLI (sync,
categorize, rules, report, subscriptions, insights, goals, dashboard, export,
schedule, doctor); MCP server on `mcp` v2 (`MCPServer`, stdio) with 8 read
tools, 8 write tools and a `ledger://summary` resource; `skill/SKILL.md`;
launchd daily job; opt-in Cowork export. README in the project.

Verified on the real thing, not only the suite:

- The live test claims a fresh demo token from the bridge's developer page
  (bound to that page's session cookie, and the bridge refuses urllib's
  default user agent) and synced 3 demo accounts / 469 transactions through
  the real CLI. That run surfaced the bridge's 45-day window guidance and
  that pending rows come back in every window; both are handled.
- An isolated Claude Code session (`claude -p --mcp-config … --strict-mcp-config`)
  answered spending, top category, net worth and insights through the server
  with figures matching the demo data.
- `claude plugin validate --strict` passes on the plugin and the marketplace;
  the plugin installs into a scratch `CLAUDE_CONFIG_DIR` with skill and MCP
  server recognized.

## What Doug has to do himself

1. Sign up at SimpleFIN Bridge, connect banks, create a setup token.
2. `ledger setup` (paste the token; Keychain stores the access URL), then
   `ledger sync`, then `ledger schedule install`.
3. Quit and relaunch Claude Desktop so the desktop registration loads.
4. **Cowork check** (the open question): ask a Cowork session a money question.
   If Cowork cannot reach the local server, run
   `ledger schedule install --export` so `~/Documents/Claude/ledger/summary.json`
   and the dashboard refresh daily.

## Next

1. **Cowork visibility of local MCP servers** — unverified; see above.
2. **The published plugin's server needs an interpreter with the `mcp` SDK.**
   `plugins/ledger` has no venv (excluded on purpose); `bin/ledger-mcp` falls
   back to `python3`, which lacks the SDK, so the plugin's MCP server fails
   until the user runs the build command or sets `LEDGER_PYTHON`. Options: a
   `uvx`/`pipx` launcher, vendoring, or a post-install hook.
3. **Rocket Money CSV import** (Phase 5 in the plan) once an export exists;
   the design is in the plan file.
4. **Resolve the five duplicated skills** (`pdf`, `docx`, `pptx`, `xlsx`,
   `skill-creator`) installed by both staff and the `anthropic-skills` plugin.
5. **A real agent**; `agents/` is still empty.
6. Leftovers: `staff promote`, `staff add_source <git-url>`, `CATEGORIES`
   includes `lib`, shellcheck triage, SDLC harness gaps.

## Traps

- A passing suite is not evidence. Use what a change produces; for ledger
  that means the demo bridge (`LEDGER_LIVE=1`) and the bundled `claude`.
- `grep` in this shell is aliased to a tool that skips binary files; use
  `/usr/bin/grep -a` when checking a database for leaked text.
- `claude` is not on PATH; the desktop app bundles it at
  `~/Library/Application Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude`.
  Use a scratch `CLAUDE_CONFIG_DIR` for experiments.
- The SimpleFIN demo token is single-use and session-bound; the test
  scrapes a fresh one each run.
- `.gitignore` excludes `dist/` and `build/` repo-wide; a plugin needing
  built output will be incomplete in a clone (publish warns).
- `gh` is not installed; commit straight to `main`.
