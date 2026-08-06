# sdlc

AI-powered development lifecycle orchestration. Breaks a natural-language spec into structured phases — plan, architect, tasks, implement, verify, review, refine — each driven by an LLM, with approval gates between steps.

## How it works

```
spec → plan → architect → tasks → implement → verify → review → refine
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^
       "thinking" phases              "doing" phases     "thinking" phases
       (direct API calls)             (claude CLI)       (direct API calls)
```

**Thinking phases** (plan, architect, tasks, review, refine) call LLM APIs directly via Python SDKs. They produce markdown documents and structured JSON.

**Doing phases** (implement, verify) delegate to the `claude` CLI so Claude Code can use tools, edit files, and run commands in your project.

Three providers are supported: **Anthropic**, **OpenAI**, and **Google**. Each phase is assigned a model tier (strongest/mid/fast) that maps to the best available model for your chosen provider.

## Install

```bash
cd harnesses/sdlc
pip install -e .
```

Or via the staff CLI:

```bash
staff install sdlc
```

### Requirements

- Python 3.11+
- An API key for your chosen provider (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI for implement/verify phases

## Quick start

```bash
# Initialize a cycle in your project directory
cd ~/my-project
sdlc init --prompt "Build a REST API for managing bookmarks"

# Run phases individually
sdlc plan
sdlc architect
sdlc tasks

# Or run the full sequence with approval gates
sdlc run
```

## Commands

| Command | Description |
|---------|-------------|
| `sdlc init` | Initialize a new cycle. Accepts `--spec FILE`, `--prompt TEXT`, or opens `$EDITOR` |
| `sdlc plan` | Generate a development plan from the spec |
| `sdlc architect` | Design technical architecture |
| `sdlc tasks` | Break architecture into implementation tasks (outputs JSON) |
| `sdlc implement` | Implement tasks via Claude Code. `--task N` for a specific task |
| `sdlc verify` | Run tests, linter, type checker via Claude Code |
| `sdlc review` | Review implementation against the spec |
| `sdlc refine` | Generate refinement plan from review + your feedback |
| `sdlc run` | Run all phases sequentially with `y/n` gates |
| `sdlc status` | Show phase completion status |
| `sdlc reset [PHASE]` | Reset a phase and all subsequent phases |

## Options

```
--provider anthropic|openai|google   Provider (default: anthropic)
--model MODEL                        Override model for any phase
--force                              Overwrite existing .sdlc/ on init
```

## Providers and models

Each phase is assigned a tier. The tier maps to the best available model for your provider:

| Tier | Anthropic | OpenAI | Google |
|------|-----------|--------|--------|
| strongest | claude-opus-4 | gpt-4o | gemini-2.5-pro |
| mid | claude-sonnet-5 | gpt-4o-mini | gemini-2.5-flash |
| fast | claude-haiku-4-5 | gpt-4o-mini | gemini-2.5-flash |

Phase-to-tier mapping: plan/architect/review/refine → strongest, tasks/implement → mid, verify → fast.

Override any phase's model with `--model`:

```bash
sdlc plan --model claude-sonnet-5
```

## State

All state lives in `.sdlc/` inside your project:

```
.sdlc/
├── config.json          # Provider, model overrides
├── spec.md              # Input requirements
├── state.json           # Phase status tracking
├── plan.md              # Plan output
├── architecture.md      # Architecture output
├── tasks.json           # Structured task list
├── verification.md      # Test/lint results
├── reviews/             # Numbered review documents
│   └── review-001.md
└── refinements/         # Numbered refinement plans
    └── refinement-001.md
```

Reset and re-run any phase:

```bash
sdlc reset architect   # Resets architect + all subsequent phases
sdlc reset             # Resets everything
```

## Status

v0.1.0 — alpha. Core pipeline works. Not yet verified:

- Full `sdlc run` sequence end-to-end
- OpenAI and Google provider API calls
- GitHub issue input (`--issue`)
