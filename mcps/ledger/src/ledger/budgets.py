"""Monthly caps per category, with rollover.

A budget here is one number per category per month, and what you did not spend
(or overspent) carries into the next month. That is the model people actually
hold in their heads: groceries has a number, a quiet month leaves room for a
noisy one, and a blown month has to be paid back.

Two decisions worth knowing about.

**Carry is derived, never stored.** It is recomputed by walking the months from
the budget's start. A stored carry would freeze whatever the categories said at
the time it was written, and these categories are still being corrected — a
month whose spending dropped $3,400 when internal transfers stopped counting as
cash would have poisoned every later month. The walk is over a handful of rows.

**Spending comes from `reports.spent_by_category` and nowhere else.** A budget
that counts differently from the report beside it is worse than no budget, so
the two share a function rather than a convention.
"""
from __future__ import annotations

import sqlite3

from ledger import categorize, db, reports
from ledger.money import (MIN_DAY_FOR_PACE, epoch_to_date, month_bounds, month_fraction,
                          month_of, prorate, shift_month)

DEFAULT_CARRY_CAP_MONTHS = 3.0


# --- writing -----------------------------------------------------------

def set_budget(conn: sqlite3.Connection, category: str, amount_cents: int, *,
               start_month: str | None = None, rollover: bool = True,
               carry_cap_months: float = DEFAULT_CARRY_CAP_MONTHS, basis: str = "user",
               notes: str | None = None, now: int | None = None) -> int:
    """Set a category's monthly cap from `start_month` onward.

    Changing an amount closes the previous row and opens a new one, so last
    quarter's budget still says what it said.
    """
    now = now or db.now_epoch()
    start_month = start_month or month_of(epoch_to_date(now))
    cid = categorize.category_id(conn, category)
    if cid is None:
        raise ValueError(f"unknown category: {category}")
    if amount_cents < 0:
        raise ValueError("a budget cannot be negative")
    prior = db.one(conn, """SELECT id, start_month FROM budgets
                            WHERE category_id = ? AND end_month IS NULL AND start_month < ?
                            ORDER BY start_month DESC LIMIT 1""", (cid, start_month))
    if prior:
        conn.execute("UPDATE budgets SET end_month = ? WHERE id = ?",
                     (shift_month(start_month, -1), prior["id"]))
    conn.execute("DELETE FROM budgets WHERE category_id = ? AND start_month = ?", (cid, start_month))
    cur = conn.execute(
        """INSERT INTO budgets (category_id, amount_cents, rollover, carry_cap_months,
                                start_month, basis, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, amount_cents, 1 if rollover else 0, carry_cap_months, start_month, basis, notes, now))
    conn.commit()
    return cur.lastrowid


def remove_budget(conn: sqlite3.Connection, category: str) -> int:
    """Drop every budget row for a category. Returns how many were removed."""
    cid = categorize.category_id(conn, category)
    if cid is None:
        return 0
    ids = [r["id"] for r in db.rows(conn, "SELECT id FROM budgets WHERE category_id = ?", (cid,))]
    if ids:
        marks = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM budget_adjustments WHERE budget_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM budgets WHERE id IN ({marks})", ids)
        conn.commit()
    return len(ids)


def adjust(conn: sqlite3.Connection, category: str, month: str, kind: str,
           amount_cents: int = 0, note: str | None = None, now: int | None = None) -> int:
    """Zero a category's carry, or hand it extra room, for one month."""
    if kind not in ("reset", "add"):
        raise ValueError("kind must be reset or add")
    row = budget_for(conn, category, month)
    if row is None:
        raise ValueError(f"no budget for {category} in {month}")
    cur = conn.execute(
        """INSERT INTO budget_adjustments (budget_id, month, kind, amount_cents, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (row["id"], month, kind, amount_cents, note, now or db.now_epoch()))
    conn.commit()
    return cur.lastrowid


# --- reading -----------------------------------------------------------

def budget_for(conn: sqlite3.Connection, category: str, month: str) -> dict | None:
    cid = categorize.category_id(conn, category)
    if cid is None:
        return None
    return db.one(conn, """
        SELECT b.*, c.name AS category FROM budgets b JOIN categories c ON c.id = b.category_id
        WHERE b.category_id = ? AND b.start_month <= ?
          AND (b.end_month IS NULL OR b.end_month >= ?)
        ORDER BY b.start_month DESC LIMIT 1""", (cid, month, month))


def _rows_in_effect(conn: sqlite3.Connection, month: str) -> list[dict]:
    return db.rows(conn, """
        SELECT b.*, c.name AS category FROM budgets b JOIN categories c ON c.id = b.category_id
        WHERE b.start_month <= ? AND (b.end_month IS NULL OR b.end_month >= ?)
        ORDER BY c.name""", (month, month))


def _amount_in(conn: sqlite3.Connection, category_id: int, month: str) -> dict | None:
    return db.one(conn, """
        SELECT * FROM budgets WHERE category_id = ? AND start_month <= ?
          AND (end_month IS NULL OR end_month >= ?)
        ORDER BY start_month DESC LIMIT 1""", (category_id, month, month))


def carry_into(conn: sqlite3.Connection, category_id: int, month: str) -> int:
    """What rolls into `month` from every month before it.

    Overspend carries forward negative and uncapped, which is what makes a cap
    mean anything. Unspent money carries forward but stops accumulating at
    `carry_cap_months` times the budget, so a category nobody touches for a
    year does not quietly become an unlimited allowance.
    """
    first = db.one(conn, "SELECT MIN(start_month) AS m FROM budgets WHERE category_id = ?", (category_id,))
    if not first or not first["m"] or first["m"] >= month:
        return 0
    carry = 0
    cursor = first["m"]
    while cursor < month:
        row = _amount_in(conn, category_id, cursor)
        if row is None:
            cursor = shift_month(cursor, 1)
            continue
        for a in db.rows(conn, "SELECT kind, amount_cents FROM budget_adjustments "
                               "WHERE budget_id = ? AND month = ? ORDER BY id", (row["id"], cursor)):
            carry = 0 if a["kind"] == "reset" else carry + a["amount_cents"]
        if not row["rollover"]:
            carry = 0
        start, end = month_bounds(cursor)
        name = db.one(conn, "SELECT name FROM categories WHERE id = ?", (category_id,))["name"]
        spent = reports.spent_by_category(conn, start, end).get(name, 0)
        carry += row["amount_cents"] - spent
        cap = int(row["carry_cap_months"] * row["amount_cents"])
        if row["rollover"] and carry > cap:
            carry = cap
        if not row["rollover"]:
            carry = 0
        cursor = shift_month(cursor, 1)
    return carry


def status(conn: sqlite3.Connection, month: str | None = None, now: int | None = None) -> list[dict]:
    """Every budget in effect for `month`, against what has actually been spent."""
    today = epoch_to_date(now or db.now_epoch())
    month = month or month_of(today)
    start, end = month_bounds(month)
    spent_all = reports.spent_by_category(conn, start, end)
    current = month == month_of(today)
    frac = month_fraction(today) if current else 1.0
    day = int(today[8:10]) if current else 99
    out = []
    for row in _rows_in_effect(conn, month):
        spent = spent_all.get(row["category"], 0)
        carry = carry_into(conn, row["category_id"], month) if row["rollover"] else 0
        available = row["amount_cents"] + carry
        projected = prorate(spent, today) if current else spent
        out.append({
            "budget_id": row["id"],
            "category": row["category"],
            "month": month,
            "amount_cents": row["amount_cents"],
            "carry_in_cents": carry,
            "available_cents": available,
            "spent_cents": spent,
            "remaining_cents": available - spent,
            "percent": round(100 * spent / available, 1) if available > 0 else None,
            # Two different questions, and a rollover budget hides the gap
            # between them: is the run rate sustainable, and will this month
            # blow the envelope? A category can fail the first and pass the
            # second because the carry covers it.
            "projected_cents": projected,
            "over_rate": projected > row["amount_cents"] and day >= MIN_DAY_FOR_PACE,
            "over_budget": spent > available,
            "on_track": spent <= available and not (projected > available and day >= MIN_DAY_FOR_PACE),
            "rollover": bool(row["rollover"]),
            "basis": row["basis"],
            "elapsed": round(frac, 3),
        })
    out.sort(key=lambda b: (b["on_track"], -b["spent_cents"]))
    return out


def summary(conn: sqlite3.Connection, month: str | None = None, now: int | None = None) -> dict:
    """The budget as a whole, including the spending no budget covers."""
    today = epoch_to_date(now or db.now_epoch())
    month = month or month_of(today)
    start, end = month_bounds(month)
    rows = status(conn, month, now)
    budgeted = {b["category"] for b in rows}
    unbudgeted = [{"category": k, "spent_cents": v}
                  for k, v in reports.spent_by_category(conn, start, end).items()
                  if k not in budgeted]
    unbudgeted.sort(key=lambda u: -u["spent_cents"])
    totals = reports.totals(conn, start, end)
    return {
        "month": month,
        "budgets": rows,
        "budgeted_cents": sum(b["amount_cents"] for b in rows),
        "available_cents": sum(b["available_cents"] for b in rows),
        "spent_cents": sum(b["spent_cents"] for b in rows),
        "remaining_cents": sum(b["remaining_cents"] for b in rows),
        "over_count": sum(1 for b in rows if b["over_budget"]),
        "income_cents": totals["income_cents"],
        "unbudgeted": unbudgeted,
        "unbudgeted_cents": sum(u["spent_cents"] for u in unbudgeted),
    }


# --- proposing ---------------------------------------------------------

RECURRING_SHARE = 0.8


def suggest(conn: sqlite3.Connection, months: int = 3, now: int | None = None) -> list[dict]:
    """Propose a budget per category, and say what each proposal rests on.

    Averaging over recent months is the obvious approach and it is wrong here:
    an account linked to the bridge in late August means July has a hole in it
    that looks exactly like a quiet month. So months that are missing an
    account are not used, and where too few remain the proposal comes from the
    recurring charges instead — a subscription or a bill already carries a
    monthly run-rate, and a single month is enough to know it.

    Every proposal says its basis and its confidence. None of them is a number
    on its own.
    """
    from ledger import recurring
    today = epoch_to_date(now or db.now_epoch())
    usable = [m["month"] for m in reports.complete_months(conn, today) if m["complete"]][-months:]

    history: dict[str, list[int]] = {}
    for m in usable:
        start, end = month_bounds(m)
        for name, cents in reports.spent_by_category(conn, start, end).items():
            history.setdefault(name, []).append(cents)

    committed: dict[str, int] = {}
    for series in recurring.roster(conn):
        if series.get("status") != "active" or not series.get("category"):
            continue
        committed[series["category"]] = committed.get(series["category"], 0) + (series.get("monthly_cents") or 0)

    # Every category with spending recently, so nothing is quietly left out.
    # The busiest single month, not the total and not the mean: an incomplete
    # month undercounts, so the fullest one is the closest thing to a month.
    seen: dict[str, int] = {}
    for back in range(3):
        start, end = month_bounds(shift_month(month_of(today), -back))
        for name, cents in reports.spent_by_category(conn, start, end).items():
            seen[name] = max(seen.get(name, 0), cents)

    out = []
    for category in sorted(set(history) | set(committed) | set(seen)):
        if category == "Uncategorized":
            continue
        kind = db.one(conn, "SELECT kind FROM categories WHERE name = ?", (category,))
        if kind and kind["kind"] in ("income", "transfer"):
            continue
        amounts = sorted(history.get(category, []))
        if len(amounts) >= 2:
            mid = len(amounts) // 2
            median = amounts[mid] if len(amounts) % 2 else (amounts[mid - 1] + amounts[mid]) // 2
            out.append({"category": category, "suggested_cents": median, "basis": "median",
                        "months_used": len(amounts), "confidence": "high",
                        "note": f"median of {len(amounts)} complete month(s)"})
        elif committed.get(category):
            out.append({"category": category, "suggested_cents": committed[category],
                        "basis": "recurring", "months_used": 0, "confidence": "medium",
                        "note": "from the recurring charges detected in this category, "
                                "which carry a monthly rate whatever the history length"})
        elif amounts:
            out.append({"category": category, "suggested_cents": amounts[0], "basis": "one_month",
                        "months_used": 1, "confidence": "low",
                        "note": "one complete month only; treat as a starting guess"})
        else:
            recent = seen.get(category, 0)
            out.append({"category": category, "suggested_cents": recent, "basis": "incomplete",
                        "months_used": 0, "confidence": "none",
                        "note": "no complete month of history covers this category — this is the "
                                "busiest month seen so far, which is a guess, not a baseline"})
    out.sort(key=lambda p: -p["suggested_cents"])
    return out
