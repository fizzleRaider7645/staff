"""Read-side queries: summaries, monthly reports, cash flow, net worth,
transaction search. Everything returns plain dicts with integer cents so the
CLI, the MCP server and the dashboard all see the same numbers."""
from __future__ import annotations

import sqlite3

from ledger import db
from ledger.money import epoch_to_date, month_bounds, month_of, shift_month

LIVE = "t.removed_at IS NULL AND t.ignored = 0"


def accounts(conn: sqlite3.Connection, include_hidden: bool = False) -> list[dict]:
    where = "" if include_hidden else "WHERE a.hidden = 0"
    return db.rows(conn, f"""
        SELECT a.id, a.name, a.kind, a.currency, a.balance_cents, a.available_cents, a.balance_date,
               a.hidden, c.name AS institution,
               (SELECT COUNT(*) FROM transactions t WHERE t.account_id = a.id AND {LIVE}) AS transactions
        FROM accounts a LEFT JOIN connections c ON c.conn_id = a.conn_id
        {where} ORDER BY a.kind, a.name""")


def net_worth(conn: sqlite3.Connection) -> dict:
    accts = accounts(conn)
    assets = sum(a["balance_cents"] for a in accts if a["kind"] not in ("credit", "loan") and a["balance_cents"] > 0)
    liabilities = sum(a["balance_cents"] for a in accts if a["kind"] in ("credit", "loan") or a["balance_cents"] < 0)
    return {
        "total_cents": sum(a["balance_cents"] for a in accts),
        "assets_cents": assets,
        "liabilities_cents": liabilities,
        "cash_cents": sum((a["available_cents"] if a["available_cents"] is not None else a["balance_cents"])
                          for a in accts if a["kind"] in ("checking", "savings")),
        "accounts": accts,
    }


def transactions(conn: sqlite3.Connection, *, start: str | None = None, end: str | None = None,
                 account: str | None = None, category: str | None = None, payee: str | None = None,
                 text: str | None = None, min_cents: int | None = None, max_cents: int | None = None,
                 uncategorized: bool = False, include_removed: bool = False, limit: int = 200) -> list[dict]:
    where = [] if include_removed else [LIVE]
    params: list = []
    if start:
        where.append("t.posted_date >= ?"); params.append(start)
    if end:
        where.append("t.posted_date < ?"); params.append(end)
    if account:
        where.append("(t.account_id = ? OR a.name LIKE ?)"); params += [account, f"%{account}%"]
    if category:
        where.append("lower(c.name) = lower(?)"); params.append(category)
    if payee:
        where.append("t.payee_key = ?"); params.append(payee)
    if text:
        where.append("(t.description LIKE ? OR t.payee_key LIKE ?)"); params += [f"%{text}%", f"%{text}%"]
    if min_cents is not None:
        where.append("ABS(t.amount_cents) >= ?"); params.append(abs(min_cents))
    if max_cents is not None:
        where.append("ABS(t.amount_cents) <= ?"); params.append(abs(max_cents))
    if uncategorized:
        where.append("t.category_id IS NULL")
    sql = f"""
        SELECT t.id, t.account_id, a.name AS account, t.posted_date AS date, t.amount_cents, t.currency,
               t.description, t.payee_key, t.pending, c.name AS category, t.category_source, t.ignored,
               t.superseded_by, t.removed_at
        FROM transactions t
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN categories c ON c.id = t.category_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY t.posted DESC, t.id LIMIT ?"""
    params.append(limit)
    return db.rows(conn, sql, params)


def spending_summary(conn: sqlite3.Connection, start: str, end: str, group_by: str = "category") -> list[dict]:
    """Outflows between start (inclusive) and end (exclusive), excluding
    transfers and income, grouped. Amounts come back positive."""
    key = {"category": "COALESCE(c.name, 'Uncategorized')", "payee": "t.payee_key",
           "account": "a.name"}[group_by]
    return db.rows(conn, f"""
        SELECT {key} AS key, -SUM(t.amount_cents) AS spent_cents, COUNT(*) AS count
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        WHERE {LIVE} AND t.amount_cents < 0 AND t.posted_date >= ? AND t.posted_date < ?
          AND COALESCE(c.kind, 'expense') NOT IN ('transfer', 'income')
        GROUP BY key ORDER BY spent_cents DESC""", (start, end))


def totals(conn: sqlite3.Connection, start: str, end: str) -> dict:
    row = db.one(conn, f"""
        SELECT
          COALESCE(SUM(CASE WHEN t.amount_cents > 0 AND COALESCE(c.kind,'expense') != 'transfer' THEN t.amount_cents END), 0) AS income,
          COALESCE(SUM(CASE WHEN t.amount_cents < 0 AND COALESCE(c.kind,'expense') NOT IN ('transfer','income') THEN -t.amount_cents END), 0) AS expense,
          COALESCE(SUM(CASE WHEN COALESCE(c.kind,'expense') = 'transfer' THEN t.amount_cents END), 0) AS transfers_net,
          COALESCE(SUM(CASE WHEN c.kind = 'fee' THEN -t.amount_cents END), 0) AS fees,
          SUM(CASE WHEN t.category_id IS NULL THEN 1 ELSE 0 END) AS uncategorized,
          COUNT(*) AS count
        FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
        WHERE {LIVE} AND t.posted_date >= ? AND t.posted_date < ?""", (start, end))
    return {
        "income_cents": int(row["income"]), "expense_cents": int(row["expense"]),
        "net_cents": int(row["income"]) - int(row["expense"]),
        "transfers_net_cents": int(row["transfers_net"]), "fees_cents": int(row["fees"]),
        "uncategorized": int(row["uncategorized"] or 0), "count": int(row["count"]),
    }


def monthly_report(conn: sqlite3.Connection, month: str, top: int = 10) -> dict:
    start, end = month_bounds(month)
    prev_start, prev_end = month_bounds(shift_month(month, -1))
    this = totals(conn, start, end)
    prev = totals(conn, prev_start, prev_end)
    return {
        "month": month,
        **this,
        "previous": {"month": shift_month(month, -1), **prev},
        "by_category": spending_summary(conn, start, end, "category"),
        "top_payees": spending_summary(conn, start, end, "payee")[:top],
    }


def cash_flow(conn: sqlite3.Connection, months: int, end_month: str) -> list[dict]:
    out = []
    for i in range(months - 1, -1, -1):
        m = shift_month(end_month, -i)
        s, e = month_bounds(m)
        out.append({"month": m, **totals(conn, s, e)})
    return out


def balance_history(conn: sqlite3.Connection, account_id: str, days: int, today: str) -> list[dict]:
    from ledger.money import add_days
    return db.rows(conn, """
        SELECT day, balance_cents FROM balance_snapshots
        WHERE account_id = ? AND day >= ? ORDER BY day""", (account_id, add_days(today, -days)))


def uncategorized_payees(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return db.rows(conn, f"""
        SELECT t.payee_key AS payee, COUNT(*) AS count, -SUM(t.amount_cents) AS net_cents,
               MAX(t.description) AS example
        FROM transactions t WHERE {LIVE} AND t.category_id IS NULL
        GROUP BY t.payee_key ORDER BY count DESC LIMIT ?""", (limit,))


def summary(conn: sqlite3.Connection, now: int) -> dict:
    """The one-screen view: balances, this month against last, top
    categories, subscriptions, and how fresh the data is."""
    from ledger import recurring, sync
    today = epoch_to_date(now)
    month = month_of(today)
    s, e = month_bounds(month)
    ps, pe = month_bounds(shift_month(month, -1))
    nw = net_worth(conn)
    subs = [r for r in recurring.roster(conn) if r["is_subscription"] and r["status"] == "active"]
    last = sync.last_sync(conn)
    return {
        "as_of": today,
        "net_worth_cents": nw["total_cents"], "assets_cents": nw["assets_cents"],
        "liabilities_cents": nw["liabilities_cents"], "cash_cents": nw["cash_cents"],
        "accounts": [{k: a[k] for k in ("id", "name", "kind", "balance_cents", "available_cents")} for a in nw["accounts"]],
        "this_month": {"month": month, **totals(conn, s, e)},
        "last_month": {"month": shift_month(month, -1), **totals(conn, ps, pe)},
        "top_categories": spending_summary(conn, s, e, "category")[:6],
        "subscriptions": {"count": len(subs), "monthly_cents": sum(r["monthly_cents"] for r in subs)},
        "last_sync": None if last is None else {
            "at": epoch_to_date(last["started_at"]), "ok": bool(last["ok"]),
            "errlist": __import__("json").loads(last["errlist_json"] or "[]")},
    }
