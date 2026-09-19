"""Finding the categories that are wrong.

Every tool here existed to find rows with *no* category, which is the easy
half and, it turned out, not where the damage was. A blank is visibly a blank.
A confident wrong answer looks exactly like a right one in every report, and
$6,208 of money moving between two of Doug's own accounts sat in Cash & ATM
for months because nothing ever asked.

Two ways in. `reason_groups` lists what the classifier decided and why, so a
line like "96 rows are Gas because the keyword BP# matched" can be scanned by
eye. `anomalies` runs structural checks that do not care what the reason was —
they look for shapes that are wrong however they got there, which is the only
kind of check that catches a mistake nobody anticipated.
"""
from __future__ import annotations

import sqlite3

from ledger import categorize, db, reports
from ledger.money import epoch_to_date, month_bounds

CONCENTRATION = 0.6
THIN_ROWS = 3
SAMPLES = 3


def _window(start: str | None, end: str | None) -> tuple[str, list]:
    where, params = "", []
    if start:
        where += " AND t.posted_date >= ?"; params.append(start)
    if end:
        where += " AND t.posted_date < ?"; params.append(end)
    return where, params


def reason_groups(conn: sqlite3.Connection, *, start: str | None = None,
                  end: str | None = None, limit: int = 40) -> list[dict]:
    """What the classifier decided, grouped by the reason it decided it."""
    clause, params = _window(start, end)
    return db.rows(conn, f"""
        SELECT COALESCE(c.name, 'Uncategorized') AS category,
               COALESCE(t.category_reason, '(not recorded)') AS reason,
               t.category_source AS source,
               COUNT(*) AS count,
               -SUM(CASE WHEN t.amount_cents < 0 THEN t.amount_cents ELSE 0 END) AS spent_cents,
               GROUP_CONCAT(SUBSTR(t.description, 1, 40), ' | ') AS samples
        FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
        WHERE {reports.VISIBLE}{clause}
        GROUP BY category, reason, source
        ORDER BY spent_cents DESC, count DESC
        LIMIT ?""", params + [limit])


def _anomaly(check, severity, detail, evidence, category=None, payee=None, amount_cents=0):
    return {"check": check, "severity": severity, "detail": detail,
            "category": category, "payee": payee, "amount_cents": amount_cents,
            "evidence": evidence[:8]}


def anomalies(conn: sqlite3.Connection, *, start: str | None = None,
              end: str | None = None) -> list[dict]:
    """Structural checks. Each says what is odd and what to look at."""
    clause, params = _window(start, end)
    out: list[dict] = []
    own = categorize.own_accounts(conn)

    # Money moving between the user's own accounts, filed as something else.
    misfiled: dict[str, list] = {}
    for r in db.rows(conn, f"""
            SELECT t.id, t.description, t.amount_cents, c.name AS category, c.kind AS kind
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE {reports.VISIBLE}{clause}""", params):
        if r["kind"] == "transfer":
            continue
        if categorize.is_internal_transfer(r["description"], own):
            misfiled.setdefault(r["category"] or "Uncategorized", []).append(r)
    for category, rows in misfiled.items():
        total = sum(abs(x["amount_cents"]) for x in rows)
        out.append(_anomaly(
            "transfer-shaped", "warn",
            f"{len(rows)} row(s) in {category} name one of your own accounts, so they are "
            f"money moving, not money spent",
            [x["id"] for x in rows], category, amount_cents=total))

    # One payee, several categories. Usually a rule that cannot express a sign.
    for r in db.rows(conn, f"""
            SELECT t.payee_key AS payee, COUNT(DISTINCT t.category_id) AS kinds,
                   GROUP_CONCAT(DISTINCT c.name) AS categories, COUNT(*) AS n
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE {reports.VISIBLE} AND t.payee_key != '' AND t.category_id IS NOT NULL{clause}
            GROUP BY t.payee_key HAVING kinds > 1""", params):
        ids = [x["id"] for x in db.rows(conn,
               f"SELECT t.id FROM transactions t WHERE {reports.VISIBLE} AND t.payee_key = ?",
               [r["payee"]])]
        out.append(_anomaly(
            "split-payee", "notice",
            f"{r['payee']} is filed under {r['categories']} across {r['n']} row(s)",
            ids, payee=r["payee"]))

    # A payee key that normalized away to nothing groups unrelated merchants.
    empty = db.rows(conn, f"""
        SELECT t.id, t.description FROM transactions t
        WHERE {reports.VISIBLE} AND t.payee_key = ''{clause}""", params)
    if empty:
        out.append(_anomaly(
            "empty-payee", "notice",
            f"{len(empty)} row(s) have no payee key, so they cannot be grouped or ruled on",
            [x["id"] for x in empty]))

    # An expense category holding money coming in, or the reverse.
    for r in db.rows(conn, f"""
            SELECT c.name AS category, c.kind AS kind, COUNT(*) AS n,
                   SUM(t.amount_cents) AS total, GROUP_CONCAT(t.id) AS ids
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE {reports.VISIBLE}{clause}
              AND ((c.kind = 'expense' AND t.amount_cents > 0)
                OR (c.kind = 'income' AND t.amount_cents < 0))
            GROUP BY c.name, c.kind""", params):
        out.append(_anomaly(
            "sign-mismatch", "notice",
            f"{r['n']} row(s) in {r['category']} run the wrong way for a {r['kind']} category",
            (r["ids"] or "").split(","), r["category"], amount_cents=abs(r["total"] or 0)))

    # A category whose whole content is one merchant, and too little of it.
    for r in db.rows(conn, f"""
            SELECT c.name AS category, COUNT(*) AS n, COUNT(DISTINCT t.payee_key) AS payees,
                   -SUM(t.amount_cents) AS spent, GROUP_CONCAT(t.id) AS ids,
                   MIN(t.description) AS example
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE {reports.VISIBLE} AND t.amount_cents < 0 AND c.kind = 'expense'{clause}
            GROUP BY c.name HAVING payees = 1 AND n < ?""", params + [THIN_ROWS]):
        out.append(_anomaly(
            "thin-category", "notice",
            f"{r['category']} contains only {r['example'][:40]!r} — one merchant, {r['n']} row(s)",
            (r["ids"] or "").split(","), r["category"], amount_cents=r["spent"] or 0))

    # One merchant dominating a category. Not wrong, but worth knowing.
    for group in reports.spending_summary(conn, start or "0000-01-01", end or "9999-12-31"):
        if group["key"] in ("Uncategorized",) or not group["spent_cents"]:
            continue
        top = db.rows(conn, f"""
            SELECT t.payee_key AS payee, -SUM(t.amount_cents) AS spent, COUNT(*) AS n
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE {reports.VISIBLE} AND t.amount_cents < 0 AND c.name = ?{clause}
            GROUP BY t.payee_key ORDER BY spent DESC LIMIT 1""", [group["key"]] + params)
        if top and top[0]["spent"] >= CONCENTRATION * group["spent_cents"] and top[0]["n"] >= THIN_ROWS:
            share = top[0]["spent"] / group["spent_cents"]
            out.append(_anomaly(
                "concentrated", "info",
                f"{top[0]['payee']} is {share:.0%} of {group['key']} "
                f"({top[0]['n']} row(s)); the category is really one merchant",
                [], group["key"], top[0]["payee"], top[0]["spent"]))

    rank = {"warn": 0, "notice": 1, "info": 2}
    out.sort(key=lambda a: (rank.get(a["severity"], 9), -a["amount_cents"]))
    return out


def report(conn: sqlite3.Connection, *, month: str | None = None, now: int | None = None) -> dict:
    """Everything worth a second look, in one payload."""
    start = end = None
    if month:
        start, end = month_bounds(month)
    return {
        "month": month,
        "as_of": epoch_to_date(now or db.now_epoch()),
        "reason_groups": reason_groups(conn, start=start, end=end),
        "anomalies": anomalies(conn, start=start, end=end),
        "uncategorized": reports.uncategorized_payees(conn),
    }
