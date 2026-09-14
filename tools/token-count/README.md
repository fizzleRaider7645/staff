# token-count

Count Claude tokens in files, directories, or stdin, and see what share of a
model's context window they take.

```
$ token-count skills/staff lib/staff --top 6
   5,473  26.1%  lib/staff/cmd_add_source.sh
   2,454  11.7%  lib/staff/cmd_install.sh
   2,266  10.8%  lib/staff/_common.sh
   1,625   7.8%  lib/staff/cmd_doctor.sh
   1,620   7.7%  skills/staff/SKILL.md
   1,612   7.7%  lib/staff/cmd_init.sh
   5,889  28.1%  (8 more files)
  --------------
  20,939         14 files

  2.1% of claude-opus-5 input context (1,000,000 tokens)
```

## Why the API and not a local tokenizer

Token counts are model-specific, and there is no accurate offline tokenizer for
Claude. `tiktoken` is OpenAI's — it undercounts Claude by roughly 15–20% on
prose and considerably more on code. So counts come from the Anthropic API's
`count_tokens` endpoint, one call per file.

That means the tool needs credentials, and that counting a large tree costs a
request per file. Files that are empty or whitespace-only skip the round trip.

## Setup

```bash
staff install token-count          # wrapper onto ~/.local/bin
```

Credentials resolve the way the SDK resolves them:

```bash
export ANTHROPIC_API_KEY=...       # an API key
ant auth login                     # or an OAuth profile the SDK reads itself
```

`bin/run` executes straight from source — no install step — so a checkout is
enough to try it.

## Usage

```
token-count [PATH ...] [options]

  PATH            files or directories; '-' or no argument reads stdin
  --model, -m     model to count against (default: claude-opus-5)
  --json          machine-readable output
  --top N         show only the N largest files
  --all           include hidden and vendor directories
  --workers N     parallel requests (default: 8)
  --no-budget     skip the context-window comparison
```

Examples:

```bash
token-count CLAUDE.md                      # one file
token-count src/ --top 10                  # the ten heaviest files in a tree
git diff | token-count -                   # a diff, from stdin
token-count . --json | jq .total_tokens    # scripted
token-count docs/ -m claude-haiku-4-5      # against a smaller context window
```

Directories skip `.git`, `node_modules`, `__pycache__`, build output and other
hidden directories by default, since dependency trees dwarf the source beside
them. `--all` includes them. Binary files are detected and reported as skipped
rather than counted.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | counted successfully (or nothing countable was found) |
| 1 | every file failed, or no paths matched |
| 2 | no credentials, or the `anthropic` package is missing |

## Tests

```bash
staff test token-count
```

Tests run from source with no install step, and stub the counter — the API
round trip itself is the one part not covered, since it needs live
credentials.
