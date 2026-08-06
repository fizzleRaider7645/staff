# Staff Repository

Monorepo of AI tooling: skills, MCP servers, agents, tools, and harnesses. Multi-provider (Anthropic, OpenAI, LangChain, etc.) and multi-language (TypeScript, Python, Go, Rust, shell).

## Repo layout

- `skills/` - Claude Code skills (`.md` frontmatter files, optional supporting scripts)
- `mcps/` - MCP server implementations
- `agents/` - Agent definitions (`.md` for Claude Code agents) and Agent SDK orchestration
- `tools/` - Standalone CLI tools and utilities
- `harnesses/` - AI orchestration harnesses / frameworks
- `lib/` - Shared libraries (only when common code emerges across projects)
- `templates/` - Scaffolding templates for new projects

## Conventions

- **Flat structure**: every project is a direct child of its category dir. No sub-grouping by provider or language.
- **Self-contained**: each project owns its own deps, build, and tests. No workspace-level hoisting.
- **Naming**: use kebab-case for directory names (e.g., `mcps/google-drive-server/`).
- **README per project**: every project has a README explaining what it does and how to run it.
- **Language-appropriate build files**: `package.json` (TS/JS), `pyproject.toml` (Python), `go.mod` (Go), `Cargo.toml` (Rust).

## Adding a new project

1. `mkdir <category>/<project-name>`
2. Add the language-appropriate build file and `README.md`
3. Put source code in `src/` (or the language convention)
4. Ensure it builds and tests independently: `cd <category>/<project-name> && <build command>`
