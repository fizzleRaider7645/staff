"""The same charge twice on the same day: a double swipe or a billing slip."""
from __future__ import annotations

from ledger import db
from ledger.insights import Insight
from ledger.money import add_days, fmt


def compute(ctx) -> list[Insight]:
    rows = db.rows(ctx.conn, """
        SELECT account_id, payee_key, posted_date, amount_cents, GROUP_CONCAT(id) AS ids, COUNT(*) AS n
        FROM transactions
        WHERE removed_at IS NULL AND ignored = 0 AND amount_cents < 0 AND pending = 0 AND payee_key != ''
          AND posted_date >= ?
        GROUP BY account_id, payee_key, posted_date, amount_cents HAVING n > 1
        ORDER BY posted_date DESC""", (add_days(ctx.today, -90),))
    out = []
    for r in rows:
        ids = r["ids"].split(",")
        out.append(Insight(
            kind="duplicate_charge", severity="notice", key=f"duplicate:{'|'.join(sorted(ids))}",
            title=f"{r['payee_key'].title()} charged {fmt(-r['amount_cents'])} {r['n']} times on {r['posted_date']}",
            detail="Same account, payee, amount and day.", amount_cents=-r["amount_cents"] * (r["n"] - 1),
            evidence=ids, suggested_action="If it was one purchase, dispute the extra charge."))
    return out
