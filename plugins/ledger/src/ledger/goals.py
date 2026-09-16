"""Savings goals (an account should reach X by a date) and spending caps
(a category should stay under X per month)."""
from __future__ import annotations

import sqlite3

from ledger import categorize, db
from ledger.money import add_days, days_between, epoch_to_date, month_bounds, month_of

DAY = 86400


def add(conn: sqlite3.Connection, name: str, target_cents: int, *, target_date: str | None = None,
        account_id: str | None = None, category: str | None = None, from_now: bool = False,
        now: int | None = None, notes: str | None = None) -> int:
    now = now or db.now_epoch()
    if bool(account_id) == bool(category):
        raise ValueError("a goal is linked to exactly one account (savings goal) or one category (spending cap)")
    cid = None
    start = 0
    if account_id:
        acct = db.one(conn, "SELECT balance_cents FROM accounts WHERE id = ?", (account_id,))
        if not acct:
            raise ValueError(f"no account with id {account_id}")
        if from_now:
            start = acct["balance_cents"]
    else:
        cid = categorize.category_id(conn, category)
        if cid is None:
            raise ValueError(f"unknown category: {category}")
    cur = conn.execute(
        """INSERT INTO goals (name, target_cents, target_date, account_id, category_id, start_cents, created_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, target_cents, target_date, account_id, cid, start, now, notes))
    conn.commit()
    return cur.lastrowid


def remove(conn: sqlite3.Connection, goal_id: int) -> bool:
    cur = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()
    return cur.rowcount > 0


def _daily_rate(conn: sqlite3.Connection, account_id: str, today: str, days: int = 90) -> float | None:
    """Cents per day the balance has moved, from snapshots; falls back to
    the net of transactions when fewer than two snapshots exist."""
    snaps = db.rows(conn, "SELECT day, balance_cents FROM balance_snapshots WHERE account_id = ? AND day >= ? ORDER BY day",
                    (account_id, add_days(today, -days)))
    if len(snaps) >= 2:
        span = days_between(snaps[0]["day"], snaps[-1]["day"])
        if span >= 7:
            return (snaps[-1]["balance_cents"] - snaps[0]["balance_cents"]) / span
    row = db.one(conn, """SELECT COALESCE(SUM(amount_cents), 0) AS net, MIN(posted_date) AS first
                          FROM transactions WHERE account_id = ? AND removed_at IS NULL AND posted_date >= ?""",
                 (account_id, add_days(today, -days)))
    if row and row["first"]:
        span = max(days_between(row["first"], today), 7)
        return row["net"] / span
    return None


def progress(conn: sqlite3.Connection, now: int | None = None) -> list[dict]:
    now = now or db.now_epoch()
    today = epoch_to_date(now)
    month = month_of(today)
    out = []
    for g in db.rows(conn, "SELECT g.*, c.name AS category, a.name AS account FROM goals g "
                           "LEFT JOIN categories c ON c.id = g.category_id LEFT JOIN accounts a ON a.id = g.account_id ORDER BY g.id"):
        item = {"id": g["id"], "name": g["name"], "target_cents": g["target_cents"], "target_date": g["target_date"],
                "created": epoch_to_date(g["created_at"]), "notes": g["notes"]}
        if g["account_id"]:
            acct = db.one(conn, "SELECT balance_cents FROM accounts WHERE id = ?", (g["account_id"],))
            current = (acct["balance_cents"] if acct else 0) - g["start_cents"]
            remaining = max(g["target_cents"] - current, 0)
            rate = _daily_rate(conn, g["account_id"], today)
            projected = None
            if remaining == 0:
                projected = today
            elif rate and rate > 0:
                projected = add_days(today, int(remaining / rate) + 1)
            on_track = None
            if g["target_date"]:
                on_track = projected is not None and projected <= g["target_date"]
            item.update({"kind": "savings", "account": g["account"], "account_id": g["account_id"],
                         "current_cents": current, "remaining_cents": remaining,
                         "percent": round(100 * min(current / g["target_cents"], 1.0), 1) if g["target_cents"] else None,
                         "rate_cents_per_month": int(rate * 30) if rate is not None else None,
                         "projected_date": projected, "on_track": on_track,
                         "days_left": days_between(today, g["target_date"]) if g["target_date"] else None})
        else:
            s, e = month_bounds(month)
            row = db.one(conn, """SELECT COALESCE(-SUM(amount_cents), 0) AS spent FROM transactions
                                  WHERE category_id = ? AND removed_at IS NULL AND ignored = 0 AND amount_cents < 0
                                    AND posted_date >= ? AND posted_date < ?""", (g["category_id"], s, e))
            spent = int(row["spent"])
            item.update({"kind": "cap", "category": g["category"], "month": month, "current_cents": spent,
                         "remaining_cents": g["target_cents"] - spent,
                         "percent": round(100 * spent / g["target_cents"], 1) if g["target_cents"] else None,
                         "on_track": spent <= g["target_cents"]})
        out.append(item)
    return out
