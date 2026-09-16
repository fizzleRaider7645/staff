"""Bank fees and interest charges."""
from __future__ import annotations

from ledger import db
from ledger.insights import Insight
from ledger.money import add_days, fmt


def compute(ctx) -> list[Insight]:
    since30, since90 = add_days(ctx.today, -30), add_days(ctx.today, -90)
    rows = db.rows(ctx.conn, """
        SELECT t.id, t.posted_date, t.amount_cents, t.description, a.kind AS account_kind, a.name AS account
        FROM transactions t JOIN categories c ON c.id = t.category_id LEFT JOIN accounts a ON a.id = t.account_id
        WHERE c.kind = 'fee' AND t.removed_at IS NULL AND t.ignored = 0 AND t.amount_cents < 0 AND t.posted_date >= ?
        ORDER BY t.posted_date DESC""", (since90,))
    if not rows:
        return []
    out = []
    last30 = [r for r in rows if r["posted_date"] >= since30]
    total30 = -sum(r["amount_cents"] for r in last30)
    total90 = -sum(r["amount_cents"] for r in rows)
    interest = [r for r in rows if "INTEREST" in r["description"].upper() or "FINANCE CHARGE" in r["description"].upper()]
    if interest:
        amt = -sum(r["amount_cents"] for r in interest)
        accounts = sorted({r["account"] for r in interest if r["account"]})
        out.append(Insight(
            kind="interest", severity="warn", key="interest:" + ",".join(accounts),
            title=f"{fmt(amt)} in interest charges in the last 90 days",
            detail="On " + ", ".join(accounts) + ". Carrying a balance costs more than almost any subscription.",
            amount_cents=amt, evidence=[r["id"] for r in interest],
            suggested_action="Pay the statement balance in full, or move the balance to a lower-rate option."))
    if total30 > 0:
        out.append(Insight(
            kind="fees", severity="notice", key=f"fees:{ctx.month}",
            title=f"{fmt(total30)} in fees in the last 30 days ({fmt(total90)} over 90)",
            detail="; ".join(f"{r['posted_date']} {r['description'][:40]} {fmt(-r['amount_cents'])}" for r in last30[:5]),
            amount_cents=total30, evidence=[r["id"] for r in last30],
            suggested_action="Most fees are avoidable: ask the bank to waive it, set up autopay, or switch accounts."))
    return out
