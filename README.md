# staff

Personal collection of AI harnesses, agent workflows, skills, tools, and MCP servers.

## Quick start

```bash
git clone <repo-url>
cd staff
./setup.sh
```

## CLI

```bash
staff list                          # List all projects
staff init mcp my-server --lang ts  # Scaffold a new MCP server
staff install my-server             # Wire it into Claude Code
staff build my-server               # Build it
staff doctor                        # Check health
```

## Layout

| Directory | Description |
|-----------|-------------|
| `skills/` | Claude Code skill definitions (`.md` frontmatter files) |
| `mcps/` | MCP server implementations (any language) |
| `agents/` | Agent definitions and multi-agent workflows |
| `tools/` | Standalone CLI tools and utilities |
| `harnesses/` | AI orchestration harnesses and frameworks |
| `lib/` | Shared libraries used by multiple projects |
| `templates/` | Scaffolding templates for bootstrapping new projects |
| `bin/` | The `staff` CLI |

## Project structure

Each project is self-contained with its own dependencies, build system, and a `staff.json` manifest:

```
<category>/<project-name>/
  staff.json      # Project metadata and install config
  src/
  package.json | pyproject.toml | go.mod | Cargo.toml
  README.md
```

## Adding a new project

```bash
staff init <category> <name> [--lang ts|python|go]
```

Categories: `skill`, `mcp`, `agent`, `tool`, `harness`, `lib`

## How install works

| Category | `staff install` action |
|----------|----------------------|
| skill | Symlinks into `~/.claude/skills/` |
| mcp | Merges config into Claude Code `settings.json` |
| agent | Symlinks into `~/.claude/agents/` |
| tool | Creates wrapper script in `~/.local/bin/` |
