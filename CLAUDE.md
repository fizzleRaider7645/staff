# Staff Repository

Monorepo of AI tooling: skills, MCP servers, agents, tools, and harnesses. Multi-provider (Anthropic, OpenAI, LangChain, etc.) and multi-language (TypeScript, Python, Go, Rust, shell).

## Repo layout

- `skills/` - Claude Code skills (`.md` frontmatter files, optional supporting scripts)
- `mcps/` - MCP server implementations
- `agents/` - Agent definitions (`.md` for Claude Code agents) and Agent SDK orchestration
- `tools/` - Standalone CLI tools and utilities
- `harnesses/` - AI orchestration harnesses / frameworks
- `lib/` - Shared libraries (only when common code emerges across projects)
- `lib/staff/` - Internal CLI command modules (not a user project)
- `bin/staff` - The staff CLI entry point
- `templates/` - Scaffolding templates for new projects

## Staff CLI

The `staff` CLI manages projects in this repo. Run `./setup.sh` to install it.

```
staff list              List all projects (filterable by --category, --language, --tag, --status)
staff init <cat> <name> Scaffold a new project from a template
staff install <project> Wire up a project (symlink skill, register MCP, etc.)
staff uninstall <name>  Remove an installed project
staff build <project>   Build a project
staff doctor            Check installation health
staff registry rebuild  Regenerate registry.json from staff.json files
```

## Registry

Every project has a `staff.json` manifest. The combined index is at `registry.json` in the repo root.
Run `staff list` to query it. Run `staff registry rebuild` to regenerate it.

## Conventions

- **Flat structure**: every project is a direct child of its category dir. No sub-grouping by provider or language.
- **Self-contained**: each project owns its own deps, build, and tests. No workspace-level hoisting.
- **Naming**: use kebab-case for directory names (e.g., `mcps/google-drive-server/`).
- **Manifest**: every project has a `staff.json` with name, category, language, description, status, install config.
- **README per project**: every project has a README explaining what it does and how to run it.

## SDLC Harness

The first project in the repo. Lives at `harnesses/sdlc/`. Python CLI (`sdlc`) for AI-powered development lifecycle orchestration.

```
cd harnesses/sdlc && pip install -e .    # Install
sdlc init --prompt "description"          # Start a cycle in any project
sdlc plan / architect / tasks / ...       # Run individual phases
sdlc run                                  # Run full sequence with approval gates
sdlc status                               # Show progress
```

Architecture: hybrid engine (direct API for thinking phases, `claude` CLI for doing phases), 3 providers (Anthropic/OpenAI/Google), composable phases, file-based state in `.sdlc/`.

## Adding a new project

Use the CLI: `staff init <category> <name> [--lang ts|python|go]`

Or manually:
1. `mkdir <category>/<project-name>`
2. Add `staff.json`, build file, and `README.md`
3. Run `staff registry rebuild`
