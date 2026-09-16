"""A category running well above its own recent norm."""
from __future__ import annotations

import statistics

from ledger import reports
from ledger.insights import Insight
from ledger.money import days_in_month, fmt, month_bounds, shift_month

RATIO = 1.5
MIN_DELTA = 5000
MIN_DAY_FOR_PACE = 10


def _by_category(conn, month: str) -> dict[str, int]:
    s, e = month_bounds(month)
    return {r["key"]: r["spent_cents"] for r in reports.spending_summary(conn, s, e, "category")}


def compute(ctx) -> list[Insight]:
    conn = ctx.conn
    last = shift_month(ctx.month, -1)
    baseline_months = [shift_month(last, -i) for i in (1, 2, 3)]
    baselines = [_by_category(conn, m) for m in baseline_months]
    last_spend = _by_category(conn, last)
    out = []
    for cat, spent in last_spend.items():
        hist = [b.get(cat, 0) for b in baselines]
        if sum(1 for h in hist if h > 0) < 2:
            continue
        median = statistics.median(hist)
        if median > 0 and spent > RATIO * median and spent - median >= MIN_DELTA:
            out.append(Insight(
                kind="unusual_spend", severity="warn", key=f"unusual_spend:{cat}:{last}",
                title=f"{cat} was {fmt(spent)} in {last}, {spent / median:.1f}x the usual {fmt(int(median))}",
                detail=f"Typical month over the three before: {fmt(int(median))}.",
                amount_cents=spent - int(median),
                suggested_action=f"Look at the largest {cat} transactions for {last}; ask Claude to list them."))
    # Month to date, prorated by how far through the month we are.
    day = int(ctx.today[8:10])
    if day >= MIN_DAY_FOR_PACE:
        frac = day / days_in_month(ctx.month)
        mtd = _by_category(conn, ctx.month)
        recent = [last_spend] + baselines[:2]
        for cat, spent in mtd.items():
            hist = [b.get(cat, 0) for b in recent]
            if sum(1 for h in hist if h > 0) < 2:
                continue
            median = statistics.median(hist)
            pace = spent / frac
            if median > 0 and pace > RATIO * median and pace - median >= MIN_DELTA:
                out.append(Insight(
                    kind="spend_pace", severity="notice", key=f"spend_pace:{cat}:{ctx.month}",
                    title=f"{cat} is on pace for {fmt(int(pace))} this month, usually {fmt(int(median))}",
                    detail=f"{fmt(spent)} so far with {int(frac * 100)}% of the month gone.",
                    amount_cents=int(pace - median),
                    suggested_action="Nothing to fix if it is planned; otherwise ease off for the rest of the month."))
    return out
