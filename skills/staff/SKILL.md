---
name: staff
description: Manage the staff monorepo — scaffold projects, query the registry, install/build projects, and follow repo conventions
---

# Staff — AI tooling monorepo management

You are working in the **staff** monorepo, which holds AI tooling: skills, MCP servers, agents, tools, and harnesses. The `staff` CLI manages projects in this repo.

## Repo layout

```
skills/       Claude Code skills (.md frontmatter + optional scripts)
mcps/         MCP server implementations
agents/       Agent definitions (.md for Claude Code agents) and Agent SDK orchestration
tools/        Standalone CLI tools and utilities
harnesses/    AI orchestration harnesses / frameworks
lib/          Shared libraries (only when common code emerges across projects)
sources/      Source bundles for external repos (repo symlink + source.toml metadata)
templates/    Scaffolding templates for `staff init`
plugins/      Plugin snapshots written by `staff publish` — not projects, never scanned
.claude-plugin/marketplace.json   Lists the published plugins; makes this repo a marketplace
```

Every local project is a direct child of its category directory. No sub-grouping.

External projects can be registered into `sources/<repo-name>/` and managed alongside local projects. They stay strictly read-only — `sources/<repo-name>/repo` is a plain symlink, never written to. If the external repo has its own `staff.json` files, those are used directly; otherwise `add_source` recognizes each category's native format (`SKILL.md` for skills, agent-frontmatter `.md` under `agents/` for agents — mcp/tool auto-discovery isn't supported yet) and synthesizes a `staff.json` under `sources/<repo-name>/generated/` so the project installs through the normal `staff install` path.

## CLI reference

Run these from anywhere — the CLI resolves the repo root from its own location.

```
staff list [--category X] [--language X] [--tag X] [--status X] [--sourced true|false]
staff add_source <repo-name> <path> [--scope user|project] [--no-install]
staff update_source <repo-name> [--no-install]
staff remove_source <repo-name> [--keep-installed]
staff init <category> <name> [--lang ts|python|go|shell|markdown]
staff install <project> [--scope user|project|desktop] [--allow-build]
staff uninstall <project> [--scope user|project|desktop]
staff build <project> [--allow-build]
staff test <project> [--allow-test]
staff test --all [--allow-test]
staff publish <project> [--out DIR] [--marketplace NAME] [--allow-build]
staff doctor
```

Categories for `init`: skill, mcp, agent, tool, harness, lib.

## When to use which command

- **Starting a new project**: `staff init <category> <name>` — creates the directory, `staff.json`, and starter files. The category argument picks the directory and the template; it is not written into the manifest.
- **Listing what exists**: `staff list` — walks the tree for `staff.json` manifests; there is no index to rebuild. Filter with `--category`, `--language`, `--tag`, `--status`, `--sourced`. Category accepts singular or plural (`skill` or `skills`); unknown categories and statuses are rejected rather than silently matching nothing.
- **Adding external projects**: `staff add_source <repo-name> <path>` — creates `sources/<repo-name>/` (read-only symlink + source metadata), discovers projects via native `staff.json` or per-category format recognition (SKILL.md, agent frontmatter), and auto-installs by default.
- **Syncing an external source**: `staff update_source <repo-name>` — re-runs discovery against the existing symlink, installs what upstream added, uninstalls what it dropped, and re-derives synthesized manifests. Foreign-format discovery runs only at `add_source`/`update_source` time — a plain `staff list` will not re-synthesize manifests — so this is the only way to pick up upstream changes. `staff doctor` flags sources whose git SHA has moved.
- **Dropping an external source**: `staff remove_source <repo-name>` — uninstalls every project it contributed, then removes `sources/<repo-name>/`. The external repo is never modified.
- **Wiring a project into Claude Code**: `staff install <project>` — links a skill's whole directory to `~/.claude/skills/<name>` (skills carry scripts and references alongside SKILL.md; linking only SKILL.md leaves those unreachable), adds MCP servers to `~/.claude.json` (user), `.mcp.json` (project) or Claude Desktop's `claude_desktop_config.json` (`--scope desktop`, MCP only; relaunch Desktop afterwards), links agents as `<project>.md`, or creates tool wrappers depending on category. An MCP project with `install.binary` gets the `~/.local/bin` wrapper too. `${PROJECT_ROOT}` is substituted throughout `mcp_config` (command, args, env).
- **After changing any `staff.json`**: nothing. Discovery is live. `staff doctor` reports duplicate project names and unresolvable source links.
- **Running tests**: `staff test <project>` — runs `test.command` from the manifest, or infers one from the project's build files. `--all` runs every project's tests and summarises; projects with no tests are skipped rather than failed.
- **Sharing a project outside this repo**: `staff publish <project>` — writes a self-contained Claude Code plugin to `plugins/<name>/` (skill → `skills/<name>/`, agent → `agents/<name>.md`, mcp → `.mcp.json` with `${CLAUDE_PLUGIN_ROOT}`, tool → the project behind its `skill/SKILL.md`) and lists it in `.claude-plugin/marketplace.json`. It is a copy, not a link: re-run after changes and bump `version` in `staff.json` to ship them. A tool should carry a `skill/SKILL.md` that says when Claude should reach for it and runs `${CLAUDE_PLUGIN_ROOT}/<binary>`; without one publish generates a thin placeholder.
- **Checking health**: `staff doctor` — verifies jq, registry, all installed projects, and that every published plugin matches its project's version.

## Project manifest (`staff.json`)

Every project must have one. Key fields:

```json
{
  "name": "project-name",
  "language": "typescript",
  "description": "What it does",
  "status": "draft|alpha|beta|stable|deprecated",
  "version": "0.1.0",
  "build": { "command": "npm run build" },
  "install": {
    "type": "mcp",
    "mcp_config": { "command": "node", "args": ["dist/index.js"] }
  },
  "tags": ["relevant", "tags"]
}
```

There is no `category` field. A project's category is the directory it lives in —
`mcps/foo` is an mcp — and `install.type` says how it wires into Claude Code. Those
are usually the same word, which is why they used to be two fields holding one value,
but they are genuinely different questions: `harnesses/sdlc` is a harness that
installs as a `tool`. A `category` left in a manifest is ignored.

## Conventions to follow

- **Kebab-case** directory names (e.g. `mcps/google-drive-server/`)
- **Self-contained**: each project owns its own deps, build, and tests. No workspace-level hoisting.
- **Flat**: no sub-directories within category dirs. `mcps/foo/` not `mcps/anthropic/foo/`.
- **README per project**: every project gets a README explaining what it does and how to run it.
- **Templates produce runnable projects**: `staff init` output should build and run immediately, not be a skeleton of TODOs.

## Design principles

- **Harnesses are compositions**: a harness is built from standalone pieces (providers, phases, tools). Don't inline functionality that could be reusable.
- **Promote on reuse**: if a second project would want the same component, move it to its own project under the right category.
- **Multi-provider by default**: support Anthropic, OpenAI, and Google where applicable. Use model tiers (strongest/mid/fast) that map to provider-specific models.
