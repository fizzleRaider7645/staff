# ledger

Personal budget tracker that runs itself. Bank accounts and transactions sync
daily from [SimpleFIN Bridge](https://beta-bridge.simplefin.org/) into a local
SQLite database; a zero-dependency CLI categorizes them, detects recurring
charges, finds savings opportunities, tracks goals and renders a dashboard;
an MCP server lets Claude Code and Claude Desktop answer questions about it
all. Nothing leaves the machine except what you ask Claude about.

```
$ ledger insights
[alert] $1,599.00 of recurring charges due within 30 days, more than the $1,200.00 in cash
    2026-10-01 Rent $1,500.00; 2026-10-01 Netflix $15.99
    -> Move money into checking before the first of these posts.
[info] 2 video streaming subscriptions: Netflix, Hulu
    $25.98 a month combined. Keeping one would save up to $15.99 a month.
    -> Pick the one you actually use and cancel the rest.
```

## Setup

1. Sign up at SimpleFIN Bridge ($1.50/month), connect your banks, and create
   a **setup token**.
2. Install and claim the token yourself — Claude never handles it:

   ```bash
   staff install ledger            # builds .venv, registers the MCP server with Claude Code, puts `ledger` on PATH
   ledger setup                    # paste the setup token; the access URL goes into macOS Keychain
   ledger sync                     # first 45 days now; history keeps arriving on later syncs
   ledger schedule install         # daily sync at 07:30 via launchd
   ```
3. For Claude Desktop (and Cowork), also register there and relaunch the app:

   ```bash
   staff install ledger --scope desktop
   ```

`ledger doctor` reports credentials (source and host only), database, last
sync and any bridge errors, request budget, backfill state, launchd, and where
the MCP server is registered.

## What you get

| Command | Does |
|---|---|
| `ledger sync` | Fetch new activity, then extend history while today's request budget lasts. Regenerates the dashboard. |
| `ledger accounts` | Balances, kinds, net worth. `accounts set-kind <id> savings` fixes a wrong guess. |
| `ledger transactions` | Search by date, account, category, payee, text, amount; `--uncategorized`. |
| `ledger categorize` | Apply rules and heuristics. `categorize set <id> --category X` for one-offs. |
| `ledger rules add <payee> --category X` | Categorize a payee from now on (`--type contains|regex` for text). |
| `ledger report --months 6` | Monthly income, spending, categories, top payees, cash flow. |
| `ledger subscriptions` | Recurring charges with cadence, monthly-equivalent cost and next date. `--bills` includes rent and utilities. |
| `ledger insights` | Subscription roster, overlapping services, price increases, converted trials, fees and interest, unusual spend, upcoming obligations vs cash, goals, month-over-month movers, duplicate charges. |
| `ledger goals add <name> --target 10000 --by 2027-06-01 --account <id>` | Savings goal with projection; `--category Dining` makes it a monthly cap. |
| `ledger dashboard --open` | One self-contained HTML page: no scripts, no network, works as a private artifact. |
| `ledger export` | Summary JSON plus the dashboard into `~/Documents/Claude/ledger/` for Cowork (opt-in; contains financial data). |
| `ledger schedule install\|status\|uninstall` | The daily launchd job. |
| `ledger mcp` | Serve the MCP server over stdio (what Claude launches). |

Every command takes `--json`. Exit codes: 0 ok, 1 error, 2 not set up, 3
request budget exhausted.

## Claude

The MCP server exposes read tools (`list_accounts`, `search_transactions`,
`spending_summary`, `cash_flow`, `list_subscriptions`, `get_insights`,
`list_goals`, `sync_status`, resource `ledger://summary`) and write tools named
as verbs (`set_goal`, `remove_goal`, `categorize_transactions`, `add_rule`,
`dismiss_insight`, `mark_subscription`, `run_sync`, `write_dashboard`).
Amounts are dollars; dates are ISO. `skill/SKILL.md` teaches Claude when to
reach for them and how to run a monthly review; `staff publish ledger` ships
both as a plugin.

Cowork runs sessions in a VM and may not reach a local MCP server. If it
cannot, `ledger schedule install --export` writes `summary.json` and the
dashboard into Cowork's folder on every sync.

## How it works

- **Sync** honours the bridge's limits: 45-day windows overlapping by five
  days, at most 20 requests a day (of the allowed 24), history walked back
  one window per spare request until five months of silence or two years.
  Ingestion is idempotent; bank-owned columns update, your categories stay.
  Pending charges are reconciled against their posted twins.
- **Categories** come from rules (yours > Claude's > imported > heuristic),
  then a service catalog (Netflix, Spotify, PG&E…), then keyword heuristics.
  Transfers between your own accounts are paired and excluded from spending.
- **Recurring detection** groups charges by normalized payee, classifies the
  median gap (weekly, biweekly, monthly, quarterly, annual) and separates
  subscriptions (steady amount) from bills (variable). Series ids are stable
  so your labels and ignores survive re-detection.
- **Insights** are deterministic and carry their evidence (transaction ids,
  series id) and a suggested action; dismiss the ones you have handled.
- **Credentials** live in macOS Keychain (`security`), or `SIMPLEFIN_ACCESS_URL`
  for non-interactive use. Error messages are redacted. Nothing under
  `~/.ledger` contains the access URL.

## Development

```bash
staff test ledger                 # pytest; the MCP smoke test runs when the venv exists
LEDGER_LIVE=1 .venv/bin/python -m pytest tests/test_live_demo.py   # against SimpleFIN's public demo bridge
```

The live test claims a fresh demo token from the bridge's developer page,
syncs three demo accounts into a temporary home, and checks that nothing
credential-shaped reaches the database.
