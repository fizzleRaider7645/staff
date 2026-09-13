# Handover

## Summary

`add_source` ingests external repos as read-only dependencies and exposes their skills/agents/tools so they're immediately usable via `staff install` — without requiring the external repo to have a `staff.json`.

Implemented behavior:

- `staff add_source <name> <path>` registers external repos under `sources/<name>/`
- `sources/<name>/repo` is a plain symlink to the external repo — **never written to**
- Discovery has two tiers:
  1. **Native staff.json**: repo root or `staff.json` one level under a category dir (`skills/`, `agents/`, `mcps/`, `tools/`, `harnesses/`, `lib/`) — unchanged from the original design.
  2. **Foreign-format recognition** (new): for projects with no `staff.json`, staff recognizes each category's own native convention — `SKILL.md` for skills (repo root or `skills/*/SKILL.md`), and flat `<name>.md` files with `name:`/`description:` frontmatter under `agents/` for agents. A `staff.json` is synthesized for each and cached under `sources/<name>/generated/<category>/<derived-name>/staff.json`, with a `content_root` field pointing back into the read-only `repo/` symlink so the existing `cmd_install.sh` installers (`install_skill`, `install_agent`, `install_tool`) can find the real content file unchanged.
- mcp/tool foreign-format auto-discovery is **not implemented** — no single unambiguous native-format signal exists for those categories the way `SKILL.md`/agent-frontmatter does for skills/agents. Repos that already ship real `staff.json` for MCPs/tools still work via tier 1.
- Registry entries carry two new passthrough fields: `synthesized` (bool) and `native_format` (`"staff" | "claude-skill" | "claude-agent"`), defaulted for full backward compatibility with existing manifests.
- `staff list --sourced true` shows sourced projects (native or synthesized alike).

## Files Changed

- `lib/staff/cmd_add_source.sh` — symlink now created before discovery (so `content_root` paths are stable); discovery extended with `discover_foreign_manifests`; per-project `source.toml` blocks carry `synthesized`/`native_format`; cleanup (`rm -rf "$source_dir"`) added to every error path once the bundle directory exists.
- `lib/staff/cmd_registry.sh` — `scan_sourced_projects` also walks `sources/*/generated/**/staff.json`; `add_registry_entry` passes through `synthesized`/`native_format`.
- `lib/staff/cmd_install.sh` — `install_skill`, `install_agent`, `install_tool` resolve `content_root` from the manifest (falling back to `project_path`) before locating the real content file.
- `lib/staff/frontmatter.sh` (new) — best-effort YAML frontmatter field extractor (`frontmatter_field`, `frontmatter_has_name_and_description`); good enough for registry descriptions, not a full YAML parser.
- `lib/staff/source_recognizers.sh` (new) — `recognize_skills`, `recognize_agents`, `synthesize_manifest`.
- `README.md`, `skills/staff/SKILL.md` — docs updated to describe native-format recognition and the read-only guarantee.

## Status

Fully implemented and verified end to end against the real https://github.com/anthropics/skills repo:

- `staff add_source anthropic_skills /path/to/anthropics/skills` discovered and installed all 19 skills (no `staff.json` in that repo at all).
- `git -C /path/to/anthropics/skills status` confirmed zero writes to the source repo.
- Registry entries show `synthesized: true`, `native_format: "claude-skill"`, correct `content_root`.
- Installed symlinks (`~/.claude/skills/pdf/SKILL.md`) resolve through `sources/anthropic_skills/repo/...` to the real file.
- Re-running `staff registry rebuild` produces identical output (modulo timestamp) — the discovery/synthesis step only runs at `add_source` time, not on every rebuild.
- A synthetic agent fixture (flat `agents/<name>.md` with frontmatter) was also verified end to end through `add_source` → `install` → symlink resolution, then cleaned up.

## Possible Follow-ups (not started)

- mcp/tool foreign-format recognition, if a real use case shows up — deliberately deferred; no reliable single-file signal was found for either category.
- Surfacing `native_format`/`synthesized` in `staff list`'s table output (currently only in `registry.json`).
- A manual-override path in `source.toml` for hand-adding an mcp/tool project to an already-registered source, if that need materializes.
