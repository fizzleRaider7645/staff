"""The subscription roster and its monthly total; trials that converted."""
from __future__ import annotations

from ledger import recurring
from ledger.insights import Insight
from ledger.money import fmt


def compute(ctx) -> list[Insight]:
    subs = [s for s in ctx.roster if s["is_subscription"] and s["status"] == "active"]
    out = []
    if subs:
        total = sum(s["monthly_cents"] for s in subs)
        names = ", ".join(f"{s['label']} {fmt(s['monthly_cents'])}/mo" for s in subs[:8])
        if len(subs) > 8:
            names += f", and {len(subs) - 8} more"
        out.append(Insight(
            kind="subscriptions", severity="info", key="subscriptions:roster",
            title=f"{len(subs)} active subscriptions cost {fmt(total)} a month ({fmt(total * 12)} a year)",
            detail=names, amount_cents=total, evidence=[s["id"] for s in subs],
            suggested_action="Cancel what you no longer use; the overlap and price-increase insights point at candidates."))
    for s in subs:
        amounts = recurring.amounts_for(ctx.conn, s["id"])
        if len(amounts) >= 3 and amounts[0][1] <= max(100, amounts[-1][1] * 0.1) and amounts[-1][1] > 0:
            out.append(Insight(
                kind="trial_converted", severity="notice", key=f"trial_converted:{s['id']}",
                title=f"{s['label']} started as a trial and now bills {fmt(amounts[-1][1])} per {s['cadence'].replace('ly', '')}",
                detail=f"First charge {fmt(amounts[0][1])}, latest {fmt(amounts[-1][1])}.",
                amount_cents=s["monthly_cents"], series_id=s["id"],
                suggested_action="Decide whether the paid tier is worth keeping."))
    return out
