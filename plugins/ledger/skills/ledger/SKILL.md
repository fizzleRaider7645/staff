---
name: ledger
description: The user's personal budget tracker (bank accounts and transactions synced from SimpleFIN into a local database). Use when they ask about spending, what they spent on something or somewhere, subscriptions, recurring bills, savings goals, budget caps, cash flow, net worth, account balances, fees, whether they can afford something, or want a finance dashboard or a monthly money review.
---

# ledger

Local-first budget tracker. Bank data comes from SimpleFIN Bridge into
`~/.ledger/ledger.db`; nothing leaves the machine except what you report.
Amounts from the MCP tools are dollars; negative transaction amounts are money
out. Categories are names like Groceries, Dining, Subscriptions, Transfer.

## Two ways in

1. **MCP tools (preferred).** When the `ledger` MCP server is connected, use its
   tools directly. They return structured data and need no shell.
2. **CLI fallback.** If the server is not connected, run the CLI with `--json`:
   `${CLAUDE_PLUGIN_ROOT}/bin/ledger --json <command>` from the plugin, or
   `ledger --json <command>` if it is on PATH. Same data, same names.

Never run `ledger setup` and never ask for the SimpleFIN setup token or access
URL. If `sync_status` reports credentials `none`, tell the user to run
`ledger setup` in a terminal themselves.

## Tool guide

| Question | Tool |
|---|---|
| balances, net worth, cash on hand | `list_accounts` |
| how much on X this month / last month / in August | `spending_summary(period, group_by)` |
| show me the transactions at Y | `search_transactions(text=..., start=..., end=...)` |
| trend over time | `cash_flow(months)` |
| subscriptions, recurring bills, what renews next | `list_subscriptions(include_bills=true)` |
| where can I save, anything wrong | `get_insights()` |
| goals, am I on track, budget caps | `list_goals` |
| when did data last refresh, bridge problems | `sync_status` |

Write tools (say what you changed): `set_goal`, `remove_goal`,
`categorize_transactions`, `add_rule`, `dismiss_insight`, `mark_subscription`,
`run_sync` (budgeted: about 20 bridge requests a day; keep `max_requests` at 1
or 2), `write_dashboard`.

`spending_summary` excludes transfers between the user's own accounts and
income. `period` accepts `month`, `last_month`, `last_30_days`, `last_90_days`,
`year`, or `YYYY-MM`. Pending charges are included; superseded pending rows
are not.

## Monthly review recipe

1. `sync_status` — if the last sync is older than two days, `run_sync(max_requests=2)`
   and surface any `errlist` entries verbatim (they mean a bank connection
   needs attention on the SimpleFIN site).
2. `spending_summary(period="last_month")` and `cash_flow(months=6)` — income,
   spending, net, and how last month compares.
3. `list_subscriptions(include_bills=true)` — the roster with monthly and
   yearly totals; note anything lapsed or renewing soon.
4. `get_insights()` — lead with alerts and warnings; then savings opportunities
   (overlaps, price increases, trials that converted, fees).
5. `list_goals` — progress and projections.
6. `search_transactions(uncategorized=true)` — offer to categorize what is
   left with `categorize_transactions`, and `add_rule` for payees that will
   recur. Prefer existing category names; ask before inventing new ones.

Report with concrete amounts, name the payees, and end with two or three
actions the user could take. Do not moralize about spending.

## Dashboard

`write_dashboard` regenerates `~/.ledger/dashboard.html` (or the CLI:
`ledger dashboard`). To share it, read the file and publish it as a private
artifact; tell the user it contains their financial data before doing so.
The page is self-contained (inline SVG, no network) so it renders anywhere.

## Interpreting the data

- Recurring detection needs at least three charges (two for annual) at a
  steady cadence. A brand-new subscription will not appear until then; say so.
- `payee_key` is a normalized merchant key (`netflix`, `TRADER JOE'S`). Use it
  with `add_rule(match_type="payee")`; use `contains` for free text.
- Account `kind` (checking, savings, credit, loan, investment) drives net
  worth and the cash figure; if a kind is wrong, the user can fix it with
  `ledger accounts set-kind <id> <kind>`.
- History arrives in 45-day windows over the first few daily syncs;
  `sync_status.history_complete` says when the backfill is done.
