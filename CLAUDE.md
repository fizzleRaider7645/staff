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
- `plugins/` - Plugin snapshots written by `staff publish`; not projects, not scanned
- `.claude-plugin/marketplace.json` - Makes the repo a Claude Code plugin marketplace

## Staff CLI

The `staff` CLI manages projects in this repo. Run `./setup.sh` to install it.

```
staff list              List all projects (filterable by --category, --language, --tag, --status)
staff init <cat> <name> Scaffold a new project from a template
staff install <project> Wire up a project (link skill dir, register MCP, etc.)
staff uninstall <name>  Remove an installed project
staff build <project>   Build a project
staff test <project>    Run a project's tests (--all for every project)
staff publish <project> Export a project as a Claude Code plugin (plugins/<name> + marketplace.json)
staff doctor            Check installation health
```

## Registry

Every project has a `staff.json` manifest. There is no index file: `staff list`,
`staff install` and `staff doctor` walk the tree on every invocation, which takes
about a tenth of a second. Nothing to rebuild, and nothing that can disagree with
what is actually on disk.

Foreign-format discovery is the exception — recognizing a `SKILL.md` that has no
manifest of its own happens at `add_source` / `update_source` time and caches a
synthesized manifest under `sources/<name>/generated/`.

## Conventions

- **Flat structure**: every project is a direct child of its category dir. No sub-grouping by provider or language.
- **Self-contained**: each project owns its own deps, build, and tests. No workspace-level hoisting.
- **Naming**: use kebab-case for directory names (e.g., `mcps/google-drive-server/`).
- **Manifest**: every project has a `staff.json` with name, language, description, status, install config, and optionally `build.command` / `test.command`. No `category` field — the directory a project lives in is its category, and `install.type` says how it installs.
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

## Testing

```
./tests/run.sh              Run the CLI test suite
./tests/run.sh discovery    Run one suite (see tests/test_*.sh for names)
./tests/run.sh -v           Show output from failing commands

staff test <project>        Run one project's own tests
staff test --all            Run every project's tests
```

`staff test` reads `test.command` from a project's `staff.json`, falling back to
what its build files imply (`pyproject.toml` -> pytest, `go.mod` -> go test, and
so on). Projects with no tests are skipped by `--all`, not failed.

Zero dependencies beyond `bash` and `jq`. Every test runs against a throwaway copy
of the repo with its own `$HOME`, so nothing touches your real projects, `~/.claude`,
or `~/.staff`. Add cases to `tests/test_<area>.sh`; the runner picks up any
`tests/test_*.sh` automatically.

The SDLC harness has its own suite: `cd harnesses/sdlc && python -m pytest`.

CI runs both on every push and PR, and the CLI suite on macOS as well as Linux —
macOS still ships bash 3.2, where array and parameter-expansion behaviour differs
from bash 5.

## Adding a new project

Use the CLI: `staff init <category> <name> [--lang ts|python|go]`

Or manually:
1. `mkdir <category>/<project-name>`
2. Add `staff.json`, build file, and `README.md`
3. That's it — the project is discovered on the next command
