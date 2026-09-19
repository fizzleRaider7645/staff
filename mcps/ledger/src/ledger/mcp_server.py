"""MCP server: Claude's door into the ledger, over stdio.

Read tools return plain data — dollars as numbers, ISO dates, category
names — so Claude can answer "what did I spend on subscriptions last month"
without arithmetic on cents. Write tools are verbs and say what they change.
The server never handles credentials: run_sync calls sync.run(), which reads
them itself, and every error string is redacted before it leaves.
"""
from __future__ import annotations

import json

from mcp.server import MCPServer

from ledger import (__version__, categorize, credentials, db, goals, insights, recurring,
                    reports, review, simplefin, sync)
from ledger.money import add_days, epoch_to_date, month_bounds, month_of, parse_cents, shift_month

INSTRUCTIONS = (
    "ledger is the user's personal budget tracker: bank accounts and transactions synced from SimpleFIN into a "
    "local database, with categories, recurring-charge detection, insights and savings goals. Amounts are in "
    "dollars; negative transaction amounts are money out. Use spending_summary for totals, search_transactions "
    "for detail, list_subscriptions and get_insights for savings opportunities. Tools whose names are verbs "
    "(set_goal, categorize_transactions, add_rule, dismiss_insight, run_sync) change state: say what you did. "
    "Never ask for or handle the SimpleFIN setup token; the user runs `ledger setup` themselves."
)

server = MCPServer("ledger", instructions=INSTRUCTIONS)


# --- helpers -------------------------------------------------------------

def _conn():
    return db.connect()


def _dollars(obj):
    """Recursively turn every *_cents integer into a dollar float under the
    same name without the suffix."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.endswith("_cents") and (v is None or isinstance(v, (int, float))):
                out[k[:-6]] = None if v is None else round(v / 100, 2)
            else:
                out[k] = _dollars(v)
        return out
    if isinstance(obj, list):
        return [_dollars(v) for v in obj]
    return obj


def _period_bounds(period: str, today: str) -> tuple[str, str]:
    month = month_of(today)
    if period in ("month", "this_month"):
        return month_bounds(month)
    if period == "last_month":
        return month_bounds(shift_month(month, -1))
    if period == "last_90_days":
        return add_days(today, -90), add_days(today, 1)
    if period == "last_30_days":
        return add_days(today, -30), add_days(today, 1)
    if period == "year":
        return f"{today[:4]}-01-01", add_days(today, 1)
    if len(period) == 7 and period[4] == "-":
        return month_bounds(period)
    raise ValueError("period must be month, last_month, last_30_days, last_90_days, year, or YYYY-MM")


def _today() -> str:
    return epoch_to_date(db.now_epoch())


# --- read tools ----------------------------------------------------------

@server.tool()
def list_accounts(include_hidden: bool = False) -> dict:
    """Every synced account with its balance, kind (checking, savings, credit, loan, investment) and
    institution, plus net worth, assets, liabilities and cash on hand."""
    conn = _conn()
    nw = reports.net_worth(conn)
    accts = reports.accounts(conn, include_hidden=include_hidden)
    for a in accts:
        a["as_of"] = epoch_to_date(a["balance_date"]) if a["balance_date"] else None
    return _dollars({"accounts": accts, "net_worth_cents": nw["total_cents"], "assets_cents": nw["assets_cents"],
                     "liabilities_cents": nw["liabilities_cents"], "cash_cents": nw["cash_cents"]})


@server.tool()
def search_transactions(start: str | None = None, end: str | None = None, account: str | None = None,
                        category: str | None = None, payee: str | None = None, text: str | None = None,
                        min_amount: float | None = None, max_amount: float | None = None,
                        uncategorized: bool = False, limit: int = 100) -> dict:
    """Transactions, newest first. Dates are YYYY-MM-DD (end is exclusive). account matches an id or part of a
    name; text matches the description; payee is an exact normalized payee key; amounts are absolute dollars.
    Set uncategorized=true to find what still needs a category."""
    conn = _conn()
    rows = reports.transactions(
        conn, start=start, end=end, account=account, category=category, payee=payee, text=text,
        min_cents=parse_cents(min_amount) if min_amount is not None else None,
        max_cents=parse_cents(max_amount) if max_amount is not None else None,
        uncategorized=uncategorized, limit=max(1, min(limit, 1000)))
    for r in rows:
        r["pending"] = bool(r["pending"])
        r.pop("removed_at", None); r.pop("superseded_by", None); r.pop("ignored", None)
    return _dollars({"transactions": rows, "count": len(rows)})


@server.tool()
def spending_summary(period: str = "month", group_by: str = "category") -> dict:
    """Spending totals for a period — month (current), last_month, last_30_days, last_90_days, year, or a
    YYYY-MM — grouped by category, payee or account. Also returns income, net and fees for the period.
    Transfers between the user's own accounts are excluded."""
    conn = _conn()
    if group_by not in ("category", "payee", "account"):
        raise ValueError("group_by must be category, payee or account")
    s, e = _period_bounds(period, _today())
    return _dollars({"period": period, "start": s, "end": e, **reports.totals(conn, s, e),
                     "groups": reports.spending_summary(conn, s, e, group_by)})


@server.tool()
def cash_flow(months: int = 6) -> dict:
    """Income, spending and net for each of the last N months, oldest first."""
    conn = _conn()
    return _dollars({"months": reports.cash_flow(conn, max(1, min(months, 36)), month_of(_today()))})


@server.tool()
def list_subscriptions(include_lapsed: bool = False, include_bills: bool = False) -> dict:
    """Recurring charges detected from the transaction history: subscriptions (steady amount, steady cadence)
    and, with include_bills, recurring bills such as rent, utilities and insurance. Each has a cadence, a
    typical amount, a monthly-equivalent cost, the next expected date, and evidence. Re-runs detection first."""
    conn = _conn()
    now = db.now_epoch()
    recurring.redetect(conn, now)
    rows = recurring.roster(conn, include_lapsed=include_lapsed, subscriptions_only=not include_bills)
    for r in rows:
        for k in ("first_seen", "last_seen", "next_expected"):
            r[k] = epoch_to_date(r[k]) if r[k] else None
    active = [r for r in rows if r["status"] == "active" and r["is_subscription"]]
    return _dollars({"series": rows, "active_subscriptions": len(active),
                     "subscriptions_monthly_cents": sum(r["monthly_cents"] for r in active),
                     "subscriptions_yearly_cents": 12 * sum(r["monthly_cents"] for r in active)})


@server.tool()
def get_insights(kinds: list[str] | None = None, min_severity: str = "info") -> dict:
    """Savings opportunities and warnings, most severe first: subscription roster, overlapping services,
    price increases, trials that converted, fees and interest, unusual category spend, upcoming obligations
    versus cash, goal progress, month-over-month movers, duplicate charges. Each carries evidence ids, an
    amount and a suggested action. Severities: info, notice, warn, alert."""
    conn = _conn()
    found = insights.run_all(conn, kinds=kinds, min_severity=min_severity)
    return _dollars({"insights": [i.as_dict() for i in found], "count": len(found)})


@server.tool()
def list_goals() -> dict:
    """Savings goals (account should reach a target by a date) and spending caps (category under a monthly
    amount), each with progress, projection and whether it is on track."""
    conn = _conn()
    return _dollars({"goals": goals.progress(conn)})


@server.tool()
def sync_status() -> dict:
    """When data was last refreshed, whether the bridge reported problems (errlist), how much of today's
    request budget is used, and how far back history reaches. Credentials are reported only as present or
    absent."""
    conn = _conn()
    now = db.now_epoch()
    last = sync.last_sync(conn)
    return {
        "credentials": credentials.source() or "none",
        "last_sync": None if last is None else {
            "at": epoch_to_date(last["started_at"]), "kind": last["kind"], "ok": bool(last["ok"]),
            "new": last["tx_new"], "errlist": json.loads(last["errlist_json"] or "[]"),
            "error": simplefin.redact(last["error"]) if last["error"] else None},
        "requests_used_24h": sync.requests_last_24h(conn, now), "request_ceiling": sync.DAILY_CEILING,
        "history_complete": sync.backfill_done(conn),
        "history_from": epoch_to_date(int(db.get_meta(conn, "backfill_cursor", now))),
    }


@server.resource("ledger://summary", mime_type="application/json")
def summary_resource() -> str:
    """One-screen summary: balances, this month vs last, top categories, subscriptions, last sync."""
    conn = _conn()
    return json.dumps(_dollars(reports.summary(conn, db.now_epoch())), indent=1)


# --- write tools ---------------------------------------------------------

@server.tool()
def set_goal(name: str, target: float, by: str | None = None, account_id: str | None = None,
             category: str | None = None, from_now: bool = False) -> dict:
    """Create a goal. Give account_id for a savings goal (the account's balance should reach `target`
    dollars by `by`, YYYY-MM-DD) or category for a monthly spending cap. from_now counts only money saved
    from today."""
    conn = _conn()
    gid = goals.add(conn, name, parse_cents(target), target_date=by, account_id=account_id,
                    category=category, from_now=from_now)
    return _dollars({"created": gid, "goal": next(g for g in goals.progress(conn) if g["id"] == gid)})


@server.tool()
def remove_goal(goal_id: int) -> dict:
    """Delete a goal by id."""
    return {"removed": goals.remove(_conn(), goal_id)}


@server.tool()
def categorize_transactions(transaction_ids: list[str], category: str) -> dict:
    """Set the category on specific transactions (creates the category if new). Recorded as decided by
    Claude; a category the user set by hand is never overwritten by automation."""
    conn = _conn()
    return {"updated": categorize.set_category(conn, transaction_ids, category, source="claude"), "category": category}


@server.tool()
def add_rule(pattern: str, category: str, match_type: str = "payee") -> dict:
    """Categorize this payee from now on. match_type payee matches the normalized payee key exactly (see
    payee_key on transactions), contains matches text in the description, regex is a regular expression.
    Applies to existing transactions too, except ones the user categorized by hand."""
    conn = _conn()
    rid = categorize.add_rule(conn, pattern, category, match_type=match_type, source="claude")
    applied = categorize.categorize(conn, only_uncategorized=False)
    return {"rule_id": rid, "recategorized": applied}


@server.tool()
def review_categories(period: str | None = None) -> dict:
    """What the categories are built on, and what looks wrong about them.

    reason_groups says how each set of rows got its category ("96 rows are Gas because the keyword
    BP# matched"), which is how a wrong category is spotted at all — a confident wrong answer looks
    identical to a right one in every total. anomalies flags shapes that are wrong however they
    arose: money moving between the user's own accounts filed as spending, one payee split across
    categories, a category that is really one merchant. Run this before trusting a budget."""
    conn = _conn()
    month = None
    if period:
        month = period if len(period) == 7 else month_of(epoch_to_date(db.now_epoch()))
    return _dollars(review.report(conn, month=month))


@server.tool()
def list_rules() -> dict:
    """Every categorization rule, with how many transactions it has claimed.

    Check this before adding one: a new rule that duplicates or fights an existing rule is
    invisible otherwise, and the first match in source order wins."""
    return {"rules": categorize.list_rules(_conn())}


@server.tool()
def remove_rule(rule_id: int) -> dict:
    """Delete a categorization rule and re-derive the rows it was deciding.

    Their categories fall back to whatever the other rules and the heuristics say, so this is how a
    rule that turned out to be wrong gets undone."""
    conn = _conn()
    removed = categorize.remove_rule(conn, rule_id)
    return {"removed": removed, "recategorized": categorize.categorize(conn, only_uncategorized=False)}


@server.tool()
def recategorize(dry_run: bool = True) -> dict:
    """Re-derive every category that a rule or heuristic chose, leaving hand-set ones alone.

    With dry_run (the default) it returns the changes it would make and why, so they can be read
    before anything moves. Use it after adding or removing rules."""
    conn = _conn()
    if dry_run:
        changes = categorize.preview(conn)
        return _dollars({"dry_run": True, "changes": changes, "count": len(changes)})
    return {"dry_run": False, "recategorized": categorize.categorize(conn, only_uncategorized=False)}


@server.tool()
def dismiss_insight(key: str) -> dict:
    """Hide an insight for good, by its key. Use when the user says it is expected or already handled."""
    insights.dismiss(_conn(), key, by="claude")
    return {"dismissed": key}


@server.tool()
def mark_subscription(series_id: str, label: str | None = None, ignore: bool | None = None,
                      is_subscription: bool | None = None) -> dict:
    """Adjust a detected recurring series: give it a readable label, ignore it (ignore=true) or bring it
    back (ignore=false), or override whether it counts as a subscription."""
    status = None if ignore is None else ("ignored" if ignore else "")
    ok = recurring.set_override(_conn(), series_id, label=label, status=status, is_subscription=is_subscription)
    return {"updated": ok, "series_id": series_id}


@server.tool()
def run_sync(max_requests: int = 2) -> dict:
    """Fetch new activity from SimpleFIN now. Budgeted: the bridge allows about 20 requests a day and the
    daily job uses most of them, so keep max_requests small. Returns what changed and any bridge errors."""
    conn = _conn()
    url = credentials.get_access_url()
    if not url:
        return {"error": "no SimpleFIN credentials; the user must run `ledger setup`"}
    try:
        results = sync.run(conn, url, max_requests=max(1, min(max_requests, 6)))
    except (sync.BudgetExhausted, simplefin.SimpleFinError) as e:
        return {"error": simplefin.redact(e)}
    return {"runs": [r.as_dict() for r in results], "new": sum(r.tx_new for r in results),
            "updated": sum(r.tx_updated for r in results), "errlist": [e for r in results for e in r.errlist]}


@server.tool()
def write_dashboard() -> dict:
    """Regenerate the HTML dashboard from the database and return its path, so it can be read and published
    as a private artifact. The file contains the user's financial data."""
    try:
        from ledger import dashboard
    except ImportError:
        return {"error": "dashboard not available in this build"}
    return {"path": str(dashboard.write(_conn()))}


def main() -> int:
    server.run(transport="stdio")
    return 0
