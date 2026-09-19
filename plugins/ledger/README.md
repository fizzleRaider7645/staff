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
- **Budgets** are a monthly cap per category. Unspent money carries into the
  next month and an overspend carries as a debt, capped at three months of
  budget so an unused category does not become an unlimited allowance. Carry is
  derived by walking the months, never stored, so correcting a category
  correctly changes every month that depended on it. Status reports the run
  rate and the envelope separately: a category can be spending too fast this
  month and still be fine because of what it carried in, and saying only one of
  those is how a budget starts lying. `ledger budget suggest` proposes from
  history and states what each proposal rests on — it refuses to average over a
  month in which an account that carries the category was not yet reporting.
- **Categories** come from rules (yours > Claude's > imported > heuristic),
  then a service catalog (Netflix, Spotify, PG&E…), then keyword heuristics.
  Transfers between your own accounts are paired and excluded from spending.
  Keywords must land on token boundaries, because the obvious alternative files
  GOMOBILEPGH under Gas and WINE AND SPIRITS under airlines. A descriptor whose
  shape says internal transfer and which names an account you hold is money
  moving whatever words it uses. A delivery platform is a channel, not a
  merchant, so the shop is read out of the rest of the descriptor. Every row
  records **why** it got its category, which is what makes a wrong one findable.
- **`ledger review`** is for wrong categories rather than missing ones. It
  groups rows by what decided them, so a whole wrong group is visible at once,
  and runs structural checks that catch mistakes nobody anticipated: internal
  transfers filed as spending, one payee split across categories, a category
  that is really a single merchant.
  Nothing inside an investment or loan account counts as household spending
  or income: buying an ETF, a 401(k) contribution landing and a loan's
  disbursement are all movement, though a fee charged inside one is real.
  Paying a card the ledger already holds is a transfer even when the two
  halves never match exactly; paying one it does not hold is the only trace
  of that spending, so it stays an expense under **Card Payments** until the
  card is connected, at which point both halves become a transfer.
- **Accounts** are typed from the account name, then the balance, then the
  institution: issuers put the product name ("Venture", "Chase Freedom") in
  place of the word "card", and a "SAVINGS PLAN" is usually a 401(k).
  `ledger accounts set-kind` overrides one for good; `ledger accounts
  reclassify` re-runs the guess over the rest. `ledger accounts hide` drops
  an account from every total, which is what you want when an institution
  reports the same money twice — SoFi lists each savings vault as its own
  account *and* inside the parent balance.
- **Cash on hand** falls back to the balance when an institution reports an
  available balance of zero against a positive balance, which several of them
  do instead of omitting the field.
- **Recurring detection** groups charges by normalized payee, classifies the
  median gap (weekly, biweekly, monthly, quarterly, annual) and separates
  subscriptions (steady amount) from bills (variable). Series ids are stable
  so your labels and ignores survive re-detection.
- **Insights** are deterministic and carry their evidence (transaction ids,
  series id) and a suggested action; dismiss the ones you have handled.
- **Credentials** live in macOS Keychain (`security`), or `SIMPLEFIN_ACCESS_URL`
  for non-interactive use. Error messages are redacted. Nothing under
  `~/.ledger` contains the access URL.

The MCP server needs the `mcp` SDK, which the standard-library CLI does not.
`bin/ledger-mcp` finds an interpreter that has it: `LEDGER_PYTHON` if you set
one (authoritative — it fails rather than quietly using another), then the
project's `.venv`, then one it builds itself under `~/.ledger/mcp-venv`. A
plugin installed from a marketplace ships no `.venv`, so its first launch
does that build once and prints a line about it.

## Development

```bash
staff test ledger                 # pytest; the MCP smoke test runs when the venv exists
LEDGER_LIVE=1 .venv/bin/python -m pytest tests/test_live_demo.py   # against SimpleFIN's public demo bridge
```

The live test claims a fresh demo token from the bridge's developer page,
syncs three demo accounts into a temporary home, and checks that nothing
credential-shaped reaches the database.
