# Handover — 2026-09-18

`main` clean, all suites green: 292 CLI (Linux + macOS in CI), 131 ledger,
154 sdlc, 38 token-count. Shellcheck advisory and still red.

## State

| | |
|---|---|
| Commands | `list, add_source, update_source, remove_source, install, uninstall, build, test, init, publish, doctor` |
| Projects | `staff` (skill), `sdlc` (harness), `token-count` (tool), **`ledger` (mcp)** |
| Published | `token-count`, `ledger` in `.claude-plugin/marketplace.json` |
| Empty categories | `agents/` |
| ledger data | 23 accounts, 4 institutions, history back to 2026-01-16, last sync 2026-09-18 |
| ledger schedule | installed, daily 07:30, `~/.ledger/logs/sync.log` |

## What changed on 2026-09-18

The four near-term fixes found on real data, plus the plugin's interpreter.

**Account kinds.** Issuers put the product name in the account name instead
of the word "card", so Venture, Chase Freedom and Chase Sapphire came back
"unknown"; a 401(k) named "MY SAVINGS PLAN" was filed as savings. The
heuristic reads plan and card product names, falls back to a negative
balance meaning credit and to the institution for an unclassifiable
brokerage account, and requires short tokens like IRA to stand alone.
`ledger accounts reclassify` re-runs it without waiting for a sync; it fixed
6 of the 13 automatically. The other 7 are set by hand: SoFi Invest "Active"
and "Automated" as investment, and the six generically named SoFi vaults as
savings.

**Cash on hand** was $1,000 against $9,000 of balances because SimpleFIN's
available-balance is optional and most of these institutions send a literal
0 rather than omitting it. A zero available against a positive balance now
reads as unreported. Cash is $9,088.28.

**SoFi vaults.** The seven accounts sharing number 8966 are buckets inside
"Savings - 8966" ($2,086.44 of the parent's $2,238.19), and net worth counted
them twice. They are hidden, and hiding now drops an account from every
total and from recurring detection, not just the account list; its rows stay
searchable by naming the account. Net worth is $155,111.36.

**Categorization.** 184 uncategorized rows carrying $84.7k are down to 10
rows worth $335. Nothing inside an investment or loan account counts as
household cash flow now — an ETF purchase, a 401(k) contribution landing and
a loan disbursement are all movement, though a fee charged inside one is
still a fee. Paying a card is matched against the institutions where the
ledger already holds a card or a loan: if it is on file the payment is a
transfer even though partial payments mean the halves never pair, and if it
is not, the payment is the only trace of that spending and stays an expense
under a new **Card Payments** category. It converts to a transfer on its own
once the card is connected. Merchant coverage grew to cover childcare,
resale apps, insurers, car finance, regional utilities and gas chains,
warehouse clubs, hardware, mortgage servicers and buy-now-pay-later.

**The published plugin's server** no longer dies on launch. `bin/ledger-mcp`
checks each candidate interpreter for the `mcp` SDK instead of assuming, and
builds a venv under `~/.ledger/mcp-venv` when nothing on the machine has it.
Only the SDK goes in it; the code still comes from the plugin's own `src/`.
`LEDGER_PYTHON` is now authoritative rather than a preference with a silent
fallback.

Two suite bugs surfaced on the way. The sync log stamped rows with the wall
clock instead of the sync's own clock, so the request budget disagreed with
every other date in the run and the budget test became a time bomb that
started failing the day after it was written. And the tests never blocked
the Keychain, so on a macOS machine that has really run `ledger setup` the
suite found live bank credentials — which is why CI was green while the
suite failed here.

## Two calls to check

Both are single-command reversals and both were judgement calls made without
you.

1. **`FREEDOM` → Housing.** The handover read these as transfers to Chase
   Freedom. The data says otherwise: Chase Freedom is paid from Checking-9538
   as "ACH: CHASE CREDIT CRD", while `FREEDOM` is a monthly $2,653.95 from
   Capital One 360 Checking that stepped to $2,729.14 in September, which
   looks like a mortgage with an escrow change. Read as Freedom Mortgage.
   If that is wrong: `ledger rules remove 2` then re-add.
2. **`ACH: Lowes` $5,688.17 stayed Shopping.** It could be a Lowe's store-card
   payment, which would make it Card Payments. It does not recur, the Lowe's
   purchases on the Venture card are small, and it was not in the list of
   unlinked cards you gave, so it was left as a purchase. It is the reason
   September Shopping reads $7,763.

## Still uncategorized

10 rows, $335 total, all of them things only you can name: six "ACH: PAYPAL"
($174), "WAVES #2" ($90), "Debit Card: PALOT KESARI LLC" ($40), "Direct
Payment: PAYPAL" ($30), "VIATOUCH MEDIA" ($1).

## Next

1. **Cowork visibility of local MCP servers** — still unverified. Ask a Cowork
   session a money question. If it cannot reach the server, run
   `ledger schedule install --export` so `~/Documents/Claude/ledger/summary.json`
   and the dashboard refresh daily.
2. **Claude Desktop** needs a full quit and relaunch to pick up the registration
   if that has not happened yet.
3. **Rocket Money CSV import** (Phase 5 in the plan) — blocked, no export
   exists yet. Design is in the plan file.
4. **Insight noise.** "Unusual spend" fires on seven categories at once
   because history only reaches 2026-01 and the early months are thin. Worth
   a minimum-history guard.
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
