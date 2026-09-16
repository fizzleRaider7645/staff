"""Price increases: the latest charge in a series is above the recent norm."""
from __future__ import annotations

from ledger import recurring
from ledger.insights import Insight
from ledger.money import fmt

MIN_PCT = 0.05
MIN_CENTS = 100


def compute(ctx) -> list[Insight]:
    out = []
    for s in ctx.roster:
        if s["status"] != "active" or s["occurrences"] < 4:
            continue
        amounts = [a for _, a in recurring.amounts_for(ctx.conn, s["id"])]
        if len(amounts) < 4:
            continue
        last, prior = amounts[-1], sorted(amounts[-4:-1])[1]
        delta = last - prior
        if delta > max(MIN_CENTS, prior * MIN_PCT):
            yearly = int(delta * 12 * recurring.MONTHLY_FACTOR.get(s["cadence"], 1.0))
            out.append(Insight(
                kind="price_increase", severity="notice", key=f"price_increase:{s['id']}:{last}",
                title=f"{s['label']} went up: {fmt(prior)} to {fmt(last)} per {s['cadence'].replace('ly', '')}",
                detail=f"That is {fmt(delta)} more each time, about {fmt(yearly)} a year.",
                amount_cents=yearly, series_id=s["id"],
                suggested_action="Check for a cheaper tier or an annual plan, or cancel."))
    return out
