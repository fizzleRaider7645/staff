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
templates/    Scaffolding templates for `staff init`
```

Every project is a direct child of its category directory. No sub-grouping.

## CLI reference

Run these from anywhere — the CLI resolves the repo root from its own location.

```
staff list [--category X] [--language X] [--tag X] [--status X]
staff init <category> <name> [--lang ts|python|go|shell|markdown]
staff install <project> [--scope user|project]
staff uninstall <project>
staff build <project>
staff doctor
staff registry rebuild
```

Categories for `init`: skill, mcp, agent, tool, harness, lib.

## When to use which command

- **Starting a new project**: `staff init <category> <name>` — creates the directory, `staff.json`, and starter files. Rebuilds the registry automatically.
- **Listing what exists**: `staff list` — reads from `registry.json`. Filter with `--category`, `--language`, `--tag`, `--status`.
- **Wiring a project into Claude Code**: `staff install <project>` — symlinks skills, merges MCP configs, links agents, or creates tool wrappers depending on category.
- **After changing any `staff.json`**: `staff registry rebuild` — regenerates `registry.json` from all manifests.
- **Checking health**: `staff doctor` — verifies jq, registry, and all installed projects.

## Project manifest (`staff.json`)

Every project must have one. Key fields:

```json
{
  "name": "project-name",
  "category": "mcp",
  "language": "typescript",
  "description": "What it does",
  "status": "draft|alpha|beta|stable|deprecated",
  "version": "0.1.0",
  "build": { "command": "npm run build" },
  "install": { "type": "mcp", "mcp_config": { "command": "node", "args": ["dist/index.js"] } },
  "tags": ["relevant", "tags"]
}

```

Install type must match category: skill→`skill`, mcp→`mcp`, agent→`agent`, tool→`tool`.

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
