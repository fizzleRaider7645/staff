"""Month-over-month movers: which categories changed most last month."""
from __future__ import annotations

from ledger import reports
from ledger.insights import Insight
from ledger.money import fmt, month_bounds, shift_month

MIN_DELTA = 2500
MIN_PCT = 0.20
TOP = 3


def compute(ctx) -> list[Insight]:
    last, before = shift_month(ctx.month, -1), shift_month(ctx.month, -2)
    a = {r["key"]: r["spent_cents"] for r in reports.spending_summary(ctx.conn, *month_bounds(last), "category")}
    b = {r["key"]: r["spent_cents"] for r in reports.spending_summary(ctx.conn, *month_bounds(before), "category")}
    if not a or not b:
        return []
    deltas = []
    for cat in set(a) | set(b):
        x, y = b.get(cat, 0), a.get(cat, 0)
        d = y - x
        if abs(d) >= MIN_DELTA and (x == 0 or abs(d) / x >= MIN_PCT):
            deltas.append((d, cat, x, y))
    deltas.sort(key=lambda t: -abs(t[0]))
    out = []
    for d, cat, x, y in deltas[:TOP]:
        direction = "up" if d > 0 else "down"
        out.append(Insight(
            kind="month_over_month", severity="info", key=f"mom:{cat}:{last}",
            title=f"{cat} {direction} {fmt(abs(d))} in {last}: {fmt(x)} to {fmt(y)}",
            detail=f"Compared with {before}.", amount_cents=d))
    return out
