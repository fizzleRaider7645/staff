# token-count

Count Claude tokens in files, directories, or stdin, and see what share of a
model's context window they take.

```
$ token-count skills/staff lib/staff --top 6
   9,448  26.3%  lib/staff/cmd_add_source.sh
   4,285  11.9%  lib/staff/cmd_install.sh
   4,129  11.5%  lib/staff/_common.sh
   2,847   7.9%  lib/staff/cmd_init.sh
   2,783   7.7%  lib/staff/cmd_doctor.sh
   2,315   6.4%  skills/staff/SKILL.md
  10,154  28.2%  (8 more files)
  --------------
  35,961         14 files

  3.6% of claude-opus-5 input context (1,000,000 tokens)
```

## Why the API and not a local tokenizer

Token counts are model-specific, and there is no accurate offline tokenizer for
Claude. `tiktoken` is OpenAI's — it undercounts Claude by roughly 15–20% on
prose and considerably more on code. So counts come from the Anthropic API's
`count_tokens` endpoint, one call per file.

For scale: a chars/4 estimate puts the tree above at 20,939 tokens. The real
count is 35,961 — off by 72%, on shell and markdown.

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

An org-level key (one not scoped to a workspace) must name a workspace on
every request:

```bash
export ANTHROPIC_WORKSPACE_ID=wrkspc_...   # or pass --workspace <id>
```

`bin/run` executes straight from source — no install step — so a checkout is
enough to try it.

If the API rejects the credentials, the tool says so once and stops, rather
than sending a doomed request for every file.

## Usage

```
token-count [PATH ...] [options]

  PATH            files or directories; '-' or no argument reads stdin
  --model, -m     model to count against (default: claude-opus-5)
  --json          machine-readable output
  --top N         show only the N largest files
  --all           include hidden and vendor directories
  --workspace ID  workspace for an org-level key (env: ANTHROPIC_WORKSPACE_ID)
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
| 2 | no credentials, credentials rejected, or the `anthropic` package is missing |

## Tests

```bash
staff test token-count
```

Tests run from source with no install step, and stub the counter — the API
round trip itself is the one part not covered, since it needs live
credentials.
