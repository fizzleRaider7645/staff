---
name: ledger
description: The user's personal budget tracker (bank accounts and transactions synced from SimpleFIN into a local database). Use when they ask about spending, what they spent on something or somewhere, subscriptions, recurring bills, budgets, whether they are over or under, savings goals, cash flow, net worth, account balances, fees, whether they can afford something, why a category looks wrong, or want a finance dashboard, a budget set up, or a monthly money review.
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
| goals, am I on track for a savings target | `list_goals` |
| budgets, am I over, how much is left | `list_budgets(month)` |
| help me set up a budget | `suggest_budgets()` then `set_budget` |
| does this category look right, why is X in Y | `review_categories()` |
| what rules exist | `list_rules()` — always check before adding one |
| when did data last refresh, bridge problems | `sync_status` |

Write tools (say what you changed): `set_budget`, `remove_budget`,
`reset_carry`, `set_goal`, `remove_goal`, `categorize_transactions`, `add_rule`,
`remove_rule`, `recategorize`, `dismiss_insight`, `mark_subscription`,
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
actions the user could take. Lead with what is working before what is not.
Explain why a number moved rather than just that it did. Say when a figure
rests on thin history. Do not moralize about spending.


## Budget review

1. `list_budgets()`. Report in this order: what is **over**, what is on track to
   go over, then what is **working**. The wins are not filler — a category
   holding a month of unspent carry is where the money to fix another one comes
   from, and a review that is only bad news stops getting opened.
2. `over_budget` and `over_rate` are different questions and the difference is
   the interesting part. Over budget means this month has blown its limit. Over
   rate means the run rate is too high but carried-over room is absorbing it, so
   the month is fine and a second month like it would not be. Say which.
3. For anything over, `search_transactions(category=..., start=<month start>)`
   and name the two or three largest charges by payee. Check
   `list_subscriptions(include_bills=true)` to say whether it is committed
   spending or a choice — those get different advice.
4. `get_insights()` for the rest.
5. Offer one concrete adjustment and **ask before writing it**. Raising a budget
   that was always structurally wrong is a real answer; so is `reset_carry`
   after a one-off the user should not have to repay out of future months.

## Setting a budget up

Never build a budget on a picture you have not checked.

1. `review_categories()` first. If a category is mostly one merchant, or money
   moving between the user's own accounts is sitting in a spending category, fix
   that before budgeting against it.
2. `suggest_budgets()`. Every proposal carries a `basis` and a `confidence`.
   **Never quote a figure without them.** `median` rests on complete months;
   `recurring` is derived from detected recurring charges and is sound even from
   one month; `one_month` and `incomplete` are guesses, and `incomplete` in
   particular means an account carrying that category's spending was not
   reporting for part of the period, so the number is probably too low.
3. Confirm each figure with the user, then `set_budget`. Rollover is on by
   default and is usually what people want.

## Fixing a category that looks wrong

`review_categories()` groups rows by what decided them, so a whole wrong group
is visible at once. Then `list_rules()` before touching anything — a new rule
that fights an existing one is otherwise invisible, and the first match wins.
Fix with `add_rule`, `remove_rule` or `categorize_transactions`, then
`recategorize(dry_run=true)` to read the change before applying it.

## What the data cannot tell you

Say so rather than implying more precision than exists.

- **History is short.** `list_budgets` and `suggest_budgets` are only as good as
  the months behind them, and an account linked to the bridge recently has no
  history from before it was linked. That looks exactly like a quiet month.
- **Amazon is one merchant.** Every order arrives as the same payee with an
  order token that says nothing about what was bought, so a large Shopping
  figure may not be decomposable. Say that instead of guessing.
- **A payment to a card the ledger does not hold hides everything behind it.**
  It appears under Card Payments as a single expense; the purchases do not
  exist in the database at all.

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
