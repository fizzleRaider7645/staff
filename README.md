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
staff add_source <name> <path>      # Register and auto-install an external project
staff update_source <name>          # Re-scan a registered source for upstream changes
staff remove_source <name>          # Unregister a source and uninstall what it provided
staff init <category> <name>        # Scaffold a new project
staff install <project>             # Wire it into Claude Code
staff uninstall <project>           # Remove an installed project
staff build <project>               # Build a project
staff doctor                        # Check installation health
```

Categories: `skill`, `mcp`, `agent`, `tool`, `harness`, `lib`

## Testing

```bash
./tests/run.sh                      # CLI suite (98 tests, bash + jq only)
cd harnesses/sdlc && pytest         # SDLC harness suite (154 tests)
```

Each CLI test runs against a throwaway copy of the repo with its own `$HOME`, so
running the suite never touches your real registry, `~/.claude`, or `~/.staff`.

## Layout

| Directory    | What goes here                                                                  |
| ------------ | ------------------------------------------------------------------------------- |
| `harnesses/` | AI orchestration harnesses and frameworks                                       |
| `mcps/`      | MCP server implementations                                                      |
| `skills/`    | Claude Code skill definitions (`.md` frontmatter files)                         |
| `agents/`    | Agent definitions and multi-agent workflows                                     |
| `tools/`     | Standalone CLI tools and utilities                                              |
| `lib/`       | Shared libraries used by multiple projects                                      |
| `sources/`   | Source bundles for external repos, each with a repo symlink and source metadata |
| `templates/` | Scaffolding templates for `staff init`                                          |

## Projects

| Project                   | Category | Language | Status | Description                                                                        |
| ------------------------- | -------- | -------- | ------ | ---------------------------------------------------------------------------------- |
| [`sdlc`](harnesses/sdlc/) | harness  | Python   | alpha  | AI-powered SDLC orchestration — plan, architect, implement, verify, review, refine |

### SDLC harness

The first project in the repo. A Python CLI for AI-powered development lifecycle orchestration with a hybrid engine (direct API for thinking phases, `claude` CLI for doing phases), multi-provider support (Anthropic, OpenAI, Google), composable phases, and file-based state.

```bash
cd harnesses/sdlc && pip install -e .
sdlc init --prompt "description"      # Start a cycle
sdlc plan / architect / tasks / ...   # Run individual phases
sdlc run                              # Run full sequence with approval gates
sdlc status                           # Show progress
```

## Adding external projects

You can register external repos (from organizations, communities, or your own separate projects) into `staff` to ingest them as read-only dependencies, exposing whatever skills/agents/tools live inside so they're immediately usable. The repo is never written to — `staff add_source` only ever symlinks it in and rebuilds the registry.

```bash
# Register a staff-native external repo (has its own staff.json manifests)
staff add_source sdlc-fork /path/to/external-repo/harnesses/sdlc --no-install

# Register a plain external repo — no staff.json required. staff recognizes
# each category's own native format: SKILL.md for skills (Claude Code's own
# skill convention), and agent-frontmatter .md files under agents/.
staff add_source anthropic_skills /path/to/anthropics/skills

# Review sourced projects
staff list --sourced true

# Install later if you skipped auto-install
staff install pdf

# Inspect the source bundle metadata
cat sources/anthropic_skills/source.toml
ls -l sources/anthropic_skills/repo
```

`add_source` first tries the repo's own `staff.json` manifests, if any. For anything else, it recognizes native formats per category — currently **skill** (`SKILL.md`) and **agent** (flat `<name>.md` with `name:`/`description:` frontmatter under `agents/`). For each match it synthesizes a `staff.json` under `sources/<name>/generated/`, pointing back at the real file inside the read-only `sources/<name>/repo/` symlink — the source repo itself is never modified. MCP and tool auto-discovery isn't supported yet (no single unambiguous native-format signal); a source repo that already ships real `staff.json` files for those still works via the manifest path.

Either way, `add_source` records source metadata (including git SHA when available), rebuilds the registry, and auto-installs by default so every discovered project is ready immediately.

Discovery runs at `add_source` time, so a source goes stale when the upstream repo changes. `staff doctor` compares the recorded git SHA against the repo's current HEAD and tells you when that has happened:

```bash
staff update_source anthropic_skills   # install additions, uninstall removals, re-derive manifests
staff remove_source anthropic_skills   # uninstall everything it provided, then drop the bundle
```

Build commands declared by a sourced project are refused by default: `build.command` in a `staff.json` from an external repo was written by someone else, and `staff install` would otherwise run it. Pass `--allow-build` to opt in once you trust the source.

`update_source` re-synthesizes manifests from scratch, so upstream edits to a `SKILL.md` description show up in the registry. `remove_source` only ever deletes `sources/<name>/` — the external repo behind the symlink is never touched.

## Project structure

Each project is self-contained with its own deps, build, and a `staff.json` manifest:

```
<category>/<project-name>/
  staff.json      # Metadata, build config, install config
  README.md
  src/
  package.json | pyproject.toml | go.mod | Cargo.toml
```

There is no index file. Every command walks the tree for `staff.json` manifests, which takes roughly a tenth of a second across this repo and its sources — so a manifest you add, edit or delete takes effect immediately, with nothing to regenerate and no cache that can drift from the disk.

## How install works

| Category | `staff install` action                         |
| -------- | ---------------------------------------------- |
| skill    | Symlinks into `~/.claude/skills/`              |
| mcp      | Merges config into Claude Code `settings.json` |
| agent    | Symlinks into `~/.claude/agents/`              |
| tool     | Creates wrapper script in `~/.local/bin/`      |

## Adding a new project

```bash
staff init <category> <name> [--lang ts|python|go]
```

Or manually: create the directory and add a `staff.json` and a README. It shows up on the next command.
