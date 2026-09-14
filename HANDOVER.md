# Handover — 2026-09-13 (evening)

`main` @ `53ae190` plus this handover commit, pushed, clean tree. CI green except
shellcheck, which is `continue-on-error` and stays red until its backlog is
triaged.

## State

| | |
|---|---|
| Commands | `list, add_source, update_source, remove_source, install, uninstall, build, test, init, publish, doctor` |
| Tests | 268 CLI (`./tests/run.sh`), 154 sdlc, 38 token-count |
| CI | CLI suite on Linux **and macOS** (bash 3.2), plus `staff test --all` |
| Projects | `staff` (skill), `sdlc` (harness), `token-count` (tool) |
| Published | `token-count` -> `plugins/token-count/`, listed in `.claude-plugin/marketplace.json` as `token-count@staff` |
| Empty categories | `mcps/`, `agents/` |
| Sources | `anthropic_skills` -> `~/Projects/skills`, 19 skills |

There is **no registry file**; `registry_projects()` walks the tree on every
invocation. Manifests carry no `category` field. `plugins/` is not a category,
so published copies are never discovered as projects.

## What this session changed

**`staff publish <project>`** — the exit path. staff is the inner loop (install
links the working copy into `~/.claude`); a plugin is distribution. publish
snapshots a project into `plugins/<name>/` in the plugin loader's layout and
upserts its entry in `.claude-plugin/marketplace.json`, which makes this repo a
Claude Code marketplace:

```
/plugin marketplace add fizzleRaider7645/staff
/plugin install token-count@staff
```

- skill -> `skills/<name>/` (whole directory); agent -> `agents/<name>.md`;
  mcp -> project + `.mcp.json` with `${PROJECT_ROOT}` rewritten to
  `${CLAUDE_PLUGIN_ROOT}`; tool -> project + `skills/<name>/` from its
  `skill/SKILL.md` (plugins have no binary component, so the skill is what makes
  Claude reach for it; publish generates a thin one if the project has none).
- Copy, not link. Symlinks dereferenced; `.git`, `node_modules`, `__pycache__`,
  `*.egg-info`, caches excluded. Staged beside the target and swapped in.
- Same `--allow-build` trust gate as install for sourced projects.
- Warns when the snapshot holds files `.gitignore` would keep out of a clone.
- Runs `claude plugin validate` when `claude` is on PATH.
- `doctor` reports a published plugin whose version differs from its project,
  or that is missing from the marketplace.
- Only the plugin's own marketplace entry is rewritten; the marketplace's name,
  description and owner are edited by hand and survive.

Verified against the real loader, not just the suite: `claude plugin validate
--strict` passes on both manifests; the plugin installs into an isolated
`CLAUDE_CONFIG_DIR`; its binary counts real files from the install cache; a
`claude -p` session with only that plugin picked the skill and reported the
same count (1,799 tokens for CLAUDE.md).

## Next

1. **Resolve the five duplicated skills** — `pdf`, `docx`, `pptx`, `xlsx`,
   `skill-creator` are installed by both staff and the `anthropic-skills`
   plugin. Choose one source each; add a `doctor` check for collisions.
2. **A real MCP and a real agent.** Both categories are empty; install and
   publish for them are fixture-tested only. An MCP will also hit the
   `.gitignore` `dist/` trap below — decide whether plugins commit build output
   or run from source.
3. **`staff promote`** — the repo's "promote on reuse" principle has no command.
4. **`staff add_source <git-url>`** — a source must already be cloned today.
5. **publish for multiple projects** — `staff publish --all`, or one plugin
   bundling several projects, once there is more than one thing to ship.
6. Leftovers: `CATEGORIES` includes `lib`, which is also the CLI's own
   `lib/staff/`; triage shellcheck so it can gate; SDLC harness gaps (prompt via
   argv near ARG_MAX, no retry/backoff, hardcoded `max_tokens`).

## Traps

- A passing suite is not evidence — fixtures inherit the code's assumptions.
  Use what a change produces. For publish that means the bundled binary below.
- When adding a regression test, reintroduce the bug and confirm it fails.
- `claude` is **not on PATH** here, but the desktop app bundles it:
  `~/Library/Application Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude`.
  Set `CLAUDE_CONFIG_DIR` to a scratch directory before `plugin marketplace add`
  / `plugin install` so experiments stay out of the real `~/.claude`.
- `.gitignore` excludes `dist/` and `build/` repo-wide. A plugin that needs
  built output will be incomplete in a marketplace clone; publish warns.
- `gh` is not installed — no PRs from this machine.
- `.env` holds `ANTHROPIC_API_KEY` (gitignored); it must be workspace-scoped.
- Commit straight to `main`; no feature branches.
