<p align="center">
  <img src="logo.png" alt="staff" width="400" />
</p>

<h3 align="center">AI tooling monorepo</h3>

<p align="center">
  A personal collection of harnesses, MCP servers, skills, agents, and tools<br/>
  for building with LLMs across providers and languages.
</p>

---

## Quick start

```bash
git clone <repo-url>
cd staff
./setup.sh
```

`setup.sh` links the `staff` CLI into `~/.local/bin`, creates state at `~/.staff/`, and builds the project registry. Requires `jq` and `git`.

## CLI

```bash
staff list                          # List all projects
staff init <category> <name>        # Scaffold a new project
staff install <project>             # Wire it into Claude Code
staff uninstall <project>           # Remove an installed project
staff build <project>               # Build a project
staff doctor                        # Check installation health
staff registry rebuild              # Regenerate registry.json
```

Categories: `skill`, `mcp`, `agent`, `tool`, `harness`, `lib`

## Layout

| Directory | What goes here |
|-----------|----------------|
| `harnesses/` | AI orchestration harnesses and frameworks |
| `mcps/` | MCP server implementations |
| `skills/` | Claude Code skill definitions (`.md` frontmatter files) |
| `agents/` | Agent definitions and multi-agent workflows |
| `tools/` | Standalone CLI tools and utilities |
| `lib/` | Shared libraries used by multiple projects |
| `templates/` | Scaffolding templates for `staff init` |

## Projects

| Project | Category | Language | Status | Description |
|---------|----------|----------|--------|-------------|
| [`sdlc`](harnesses/sdlc/) | harness | Python | alpha | AI-powered SDLC orchestration — plan, architect, implement, verify, review, refine |

### SDLC harness

The first project in the repo. A Python CLI for AI-powered development lifecycle orchestration with a hybrid engine (direct API for thinking phases, `claude` CLI for doing phases), multi-provider support (Anthropic, OpenAI, Google), composable phases, and file-based state.

```bash
cd harnesses/sdlc && pip install -e .
sdlc init --prompt "description"      # Start a cycle
sdlc plan / architect / tasks / ...   # Run individual phases
sdlc run                              # Run full sequence with approval gates
sdlc status                           # Show progress
```

## Project structure

Each project is self-contained with its own deps, build, and a `staff.json` manifest:

```
<category>/<project-name>/
  staff.json      # Metadata, build config, install config
  README.md
  src/
  package.json | pyproject.toml | go.mod | Cargo.toml
```

The combined index lives at `registry.json` in the repo root. Run `staff registry rebuild` to regenerate it.

## How install works

| Category | `staff install` action |
|----------|----------------------|
| skill | Symlinks into `~/.claude/skills/` |
| mcp | Merges config into Claude Code `settings.json` |
| agent | Symlinks into `~/.claude/agents/` |
| tool | Creates wrapper script in `~/.local/bin/` |

## Adding a new project

```bash
staff init <category> <name> [--lang ts|python|go]
```

Or manually: create the directory, add `staff.json` and a README, then run `staff registry rebuild`.
