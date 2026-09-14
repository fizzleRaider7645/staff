---
name: token-count
description: Count Claude tokens in files, directories, diffs, or pasted text and show what share of a model's context window they use. Use when the user asks how many tokens something is, whether files will fit in context, which files are heaviest, or wants a token budget before loading a large tree into a prompt.
---

# token-count

Counts tokens with the Anthropic `count_tokens` endpoint, so the numbers are
exact for the model you name. There is no accurate offline tokenizer for
Claude: a chars/4 estimate is off by 70% on shell and markdown, and `tiktoken`
is OpenAI's.

## Running it

The tool ships inside this plugin and runs from source:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/run PATH [PATH ...] [options]
```

If `${CLAUDE_PLUGIN_ROOT}` is not set, the project was installed with
`staff install token-count` and is on PATH as `token-count`.

Requirements: Python 3.11+ and the `anthropic` package. If the tool exits 2
saying the package is missing, run `pip install anthropic` and retry.

Credentials resolve the way the SDK resolves them: `ANTHROPIC_API_KEY` in the
environment, or an OAuth profile from `ant auth login`. Never paste a key into
the command line. If the key is org-level rather than workspace-scoped, the
tool exits 2 asking for a workspace; pass `--workspace <id>` or set
`ANTHROPIC_WORKSPACE_ID`.

## Options

| Flag | Meaning |
|---|---|
| `--model, -m` | model to count against (default `claude-opus-5`) |
| `--top N` | show only the N largest files |
| `--json` | machine-readable output |
| `--all` | include hidden and vendor directories (skipped by default) |
| `--no-budget` | skip the context-window comparison |
| `--workers N` | parallel requests (default 8) |
| `-` | read stdin |

## Typical calls

```bash
${CLAUDE_PLUGIN_ROOT}/bin/run CLAUDE.md                      # one file
${CLAUDE_PLUGIN_ROOT}/bin/run src/ --top 10                  # heaviest files in a tree
git diff | ${CLAUDE_PLUGIN_ROOT}/bin/run -                   # a diff
${CLAUDE_PLUGIN_ROOT}/bin/run . --json | jq .total_tokens    # scripted
${CLAUDE_PLUGIN_ROOT}/bin/run docs/ -m claude-haiku-4-5      # smaller window
```

## Reading the output

The table lists each file's count and share, then the total and the fraction
of the chosen model's input context it occupies. Report the total and the
percentage to the user, and name the heaviest files when the question is
about what to trim. Binary files are reported as skipped, not counted.

Each file costs one API request. For a very large tree, count a subdirectory
or use `--top` on the directories that matter rather than the whole checkout.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | counted (or nothing countable found) |
| 1 | every file failed, or no paths matched |
| 2 | no credentials, credentials rejected, workspace required, or `anthropic` missing |
