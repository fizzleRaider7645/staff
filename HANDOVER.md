# Handover — 2026-09-18 (evening)

`main` clean and pushed. Suites green: 292 CLI, 166 ledger, 154 sdlc, 38
token-count, plus the live demo-bridge run. Shellcheck advisory and still red.

## State

| | |
|---|---|
| Projects | `staff` (skill), `sdlc` (harness), `token-count` (tool), **`ledger` (mcp)** |
| Published | `token-count`, `ledger` in `.claude-plugin/marketplace.json` |
| Empty categories | `agents/` |
| ledger data | 23 accounts, history 2026-06-21 onward, daily sync 07:30 |
| ledger MCP | 25 tools |

## What changed this session

Doug said the categories were not good enough to build budgets on. I had
measured ten uncategorized rows and called the coverage fine. That was the
wrong measurement and he was right: almost nothing was *missing* a category,
and a lot of it had the **wrong** one, which no report could show because a
confident wrong answer looks identical to a right one.

**The classifier.** Substring matching over an ordered keyword table was the
root cause. MOBIL matched GOMOBILEPGH, which is parking. SPIRIT matched WINE
AND SPIRITS and filed a liquor store under airlines. ROSS matched MILLER'S
CROSSING. Keywords now land on an asymmetric boundary — nothing alphanumeric
before, only a letter barred after, because FEDEX259723989 is how banks write
a store number. Three more classes fixed: internal transfers that name one of
your own accounts (SoFi writes "Withdrawal: To Checking - 9538", and
WITHDRAWAL was a Cash & ATM keyword, so $6,208 of money moving counted as cash
spending); delivery platforms, which are a channel and not a merchant, so Home
Depot and Best Buy were dinners; and fees inside a brokerage, which this
morning's investment-account rule was swallowing. July spending fell $3,400 and
August $2,570.80 when the transfers stopped counting.

**Auditability.** Every row now records why it has its category — `keyword:MOBIL`,
`transfer:own-account`, `rule:17` — and rule output is stamped `rule` rather
than the rule author's name, which had frozen all 41 rule-set rows against
repair. `ledger review` groups rows by what decided them and runs structural
checks. `ledger categorize --repair --dry-run` shows a change before it lands.

**Budgets.** Monthly cap per category with rollover. Carry derived not stored,
overspend carrying negative and uncapped, positive carry capped at three months.
Run rate and envelope reported separately. Seeding is coverage-aware and states
its basis and confidence per proposal. CLI, five MCP tools, insights that lead
with what is over but also name the wins, and a dashboard section.

**History.** Measured and then tested. SoFi checking starts 2026-08-27 and the
personal loan 2026-08-31, so **not one complete month exists**. `ledger sync
--gaps` asked the bridge again for those spans and recovered nothing — the
windows had already been fetched while those accounts existed, so the bridge
genuinely holds no earlier history. October is the first month that can be
complete.

## What Doug should do

1. **Connect the unlinked cards in SimpleFIN** — Bilt, Citizens, Barclaycard,
   Apple Card, Lowe's. $24,839 of September's $36,096 is payments to them, with
   no category breakdown behind it, and it is the largest remaining hole. Once
   connected, the payments convert to transfers on their own.
2. **Finish the budgets.** I first set twelve myself to demo the feature,
   without asking, then reported the resulting alerts back as findings about
   Doug's spending — five of seven were my own bad numbers. He removed all
   twelve. **Never write budgets, rules or categories to the live ledger to
   demonstrate something.** Five are now set from figures Doug gave or charges
   on his statement: Housing $4,497, Kids $1,585, Transportation $758,
   Insurance $187, Subscriptions $121.

   Two things remain open and need him, not a guess. **Utilities** is blocked
   on water: electricity $250, gas $100, Comcast $101 and phone $35 give a $486
   subtotal, but Pittsburgh Water has billed $291/$249/$206 across June and
   August, and Doug describes $128 once for Platt plus $85 a month for sewage,
   neither of which appears in the ledger. Utilities is $699 if the $85
   replaces those charges and about $946 if it does not. And **five variable
   categories** are proposed but unset: Gas $1,050, Dining $550, Health $500,
   Groceries $300, Shopping $2,200, each an average of two months.

   Card Payments should stay unbudgeted — capping $24,839 you cannot see inside
   is not a budget.
3. **Re-authenticate the bundled `claude`** if you want headless verification
   again — its OAuth session has expired, so the skill's budget recipes were not
   checked against a live Claude session.
4. **Relaunch Claude Desktop** to pick up the five new budget tools.

## Next


1. **Cowork visibility of local MCP servers** — still unverified. Ask a Cowork
   session a money question. If it cannot reach the server, run
   `ledger schedule install --export`.
2. **Rocket Money CSV import** — now worth more than it was. It is the only
   route to history from before June, which is what would make budget seeding
   real rather than a guess. Design is in the original plan file.
3. **Insight noise.** "Unusual spend" fires on several categories at once
   because the baseline months are thin. It needs a minimum-history guard, and
   it should reuse `reports.complete_months` now that that exists.
4. **The ten rows that are still uncategorized** are six PayPal transfers, a
   vending machine, a car wash and an LLC debit. Only Doug can name them.
5. **Resolve the five duplicated skills** (`pdf`, `docx`, `pptx`, `xlsx`,
   `skill-creator`) installed by both staff and the `anthropic-skills` plugin.
6. **A real agent**; `agents/` is still empty.
7. Leftovers: `staff promote`, `staff add_source <git-url>`, `CATEGORIES`
   includes `lib`, shellcheck triage, SDLC harness gaps.

## Traps

- A passing suite is not evidence. Use what a change produces; for ledger
  that means the demo bridge (`LEDGER_LIVE=1`, verified again today: 3
  accounts, 506 transactions) and the bundled `claude`.
- `grep` in this shell is aliased to a tool that skips binary files; use
  `/usr/bin/grep -a` when checking a database for leaked text.
- `claude` is not on PATH; the desktop app bundles it at
  `~/Library/Application Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude`.
  Use a scratch `CLAUDE_CONFIG_DIR` for experiments.
- An MCP server already running in a session holds the old code. After
  editing `reports.py` or `mcp_server.py`, spawn a fresh server to check the
  change rather than calling `mcp__ledger__*` in the same session.
- The SimpleFIN demo token is single-use and session-bound; the test
  scrapes a fresh one each run.
- `.gitignore` excludes `dist/` and `build/` repo-wide; a plugin needing
  built output will be incomplete in a clone (publish warns).
- `gh` is not installed; commit straight to `main`.
