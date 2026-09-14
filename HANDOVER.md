# Handover — 2026-09-13

`main` @ `412371f`, pushed, clean tree. CI green except shellcheck, which is
`continue-on-error` and stays red until its backlog is triaged.

## State

| | |
|---|---|
| Commands | `list, add_source, update_source, remove_source, install, uninstall, build, test, init, doctor` |
| Tests | 206 CLI (`./tests/run.sh`), 154 sdlc, 38 token-count |
| CI | CLI suite on Linux **and macOS** (macOS ships bash 3.2), plus `staff test --all` |
| Projects | `staff` (skill), `sdlc` (harness), `token-count` (tool) |
| Empty categories | `mcps/`, `agents/` |
| Sources | `anthropic_skills` -> `~/Projects/skills`, 19 skills |

There is **no registry file**. `registry_projects()` walks the tree on every
invocation (~113ms for 21 projects). `staff registry rebuild` no longer exists.
Manifests carry no `category` field — the directory is the category, and
`install.type` says how a project installs.

## What this session changed

Nine bugs, all silent, all in paths nothing had exercised:

- **Skills installed as a lone `SKILL.md`** — 14 of 19 lost every supporting file
  (`claude-api` lost 88). The whole skill directory is now symlinked.
- **Every agent symlinked to the same `~/.claude/agents/agent.md`**, so a second
  install clobbered the first and uninstalling either destroyed the survivor.
- **MCP servers written to `settings.json`**, which Claude Code does not read for
  server definitions. Now `~/.claude.json` (user) / `.mcp.json` (project).
- **`registry rebuild` reported success while emptying the index** when a source
  symlink broke.
- **YAML frontmatter parsing** stripped quotes unconditionally and left `\"`
  escapes literal, corrupting three descriptions.
- **`doctor`** mis-handled multi-scope records and counted "staff not in PATH" as
  an issue, which is why CI failed while the suite passed locally.
- **Templates** produced projects that could not build or install (`npm run build`
  without `npm install`; `init tool` defaulting to a language with no template;
  `bin/run` scaffolded non-executable).
- **`eval` on manifest `build.command`** — a sourced repo could run arbitrary code
  on `staff install`. Now `bash -c`, and a sourced project's build/test command is
  refused unless `--allow-build` / `--allow-test` is passed.

Then simplification: `cmd_registry.sh` (202 lines), both index files, the
`category` field, and `registry rebuild` all deleted.

## Next

1. **`staff publish`** — export a project as a Claude Code plugin
   (`.claude-plugin/plugin.json` + repo `marketplace.json`). Staff is the inner
   dev loop; plugins are distribution. Without an exit path staff competes with
   the plugin system instead of feeding it. `token-count` is ready to package.
2. **Five duplicated skills** — `pdf`, `docx`, `pptx`, `xlsx`, `skill-creator` are
   installed by both staff and the `anthropic-skills` plugin. Choose one source
   each; add a `doctor` check for collisions.
3. **A real MCP and a real agent** — those categories are still empty, and every
   bug above lived in an unexercised path.
4. **`staff promote`** — the repo's own "promote on reuse" principle has no command.
5. **`staff add_source <git-url>`** — a source must already be cloned today.
6. Leftovers: `CATEGORIES` includes `lib`, which is also the CLI's own
   `lib/staff/`; triage shellcheck so it can gate; SDLC harness gaps (prompt via
   argv near ARG_MAX, no retry/backoff, hardcoded `max_tokens`, OpenAI tiers a
   generation behind the Claude ones).

## Traps

- A passing suite is not evidence — fixtures inherit the code's assumptions. Every
  skill fixture was a single `SKILL.md`, exactly the installer's wrong assumption,
  so the suite proved the bug worked. Use what a change produces.
- When adding a regression test, reintroduce the bug and confirm it fails.
- `gh` is not installed — no PRs from this machine. The GitHub REST API works
  unauthenticated for reads; Actions logs need admin auth.
- `.env` holds `ANTHROPIC_API_KEY` (gitignored). It must be **workspace-scoped** —
  an org-level key needs an `anthropic-workspace-id` header. No `ant` CLI here.
- Commit straight to `main`; no feature branches.
