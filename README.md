# staff

Personal collection of AI harnesses, agent workflows, skills, tools, and MCP servers.

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

## Structure

Each project under a category is self-contained with its own dependencies, build system, and README. No workspace-level dependency hoisting.

```
<category>/
  <project-name>/
    src/
    package.json | pyproject.toml | go.mod | Cargo.toml
    README.md
```

## Adding a new project

1. Pick the category that fits
2. Create a directory: `mkdir <category>/<project-name>`
3. Add a build file for your language and a README
4. Build and test independently from the project directory
