"""Savings goals off track or reached; spending caps blown or on pace to be."""
from __future__ import annotations

from ledger import goals as goals_mod
from ledger.insights import Insight
from ledger.money import days_in_month, fmt


def compute(ctx) -> list[Insight]:
    out = []
    day = int(ctx.today[8:10])
    frac = day / days_in_month(ctx.month)
    for g in goals_mod.progress(ctx.conn, ctx.now):
        key = f"goal:{g['id']}"
        if g["kind"] == "savings":
            if g["remaining_cents"] == 0:
                out.append(Insight(kind="goal_reached", severity="info", key=key + ":reached",
                                   title=f"Goal reached: {g['name']} ({fmt(g['target_cents'])})",
                                   detail=f"{g['account']} holds {fmt(g['current_cents'])}.", amount_cents=g["target_cents"]))
            elif g["on_track"] is False:
                when = g["projected_date"] or "never at the current rate"
                out.append(Insight(
                    kind="goal_behind", severity="notice", key=key + f":{ctx.month}",
                    title=f"{g['name']} is behind: {g['percent']}% there, projected {when} vs target {g['target_date']}",
                    detail=f"{fmt(g['remaining_cents'])} to go; {g['account']} is moving {fmt(g['rate_cents_per_month'] or 0)} a month.",
                    amount_cents=g["remaining_cents"],
                    suggested_action="Raise the automatic transfer, or push the target date out."))
        else:
            if g["current_cents"] > g["target_cents"]:
                out.append(Insight(
                    kind="cap_exceeded", severity="warn", key=key + f":{ctx.month}",
                    title=f"{g['category']} is over its {fmt(g['target_cents'])} cap: {fmt(g['current_cents'])} so far in {ctx.month}",
                    detail=f"{fmt(g['current_cents'] - g['target_cents'])} over.", amount_cents=g["current_cents"] - g["target_cents"],
                    suggested_action=f"Pause {g['category']} spending for the rest of the month."))
            elif day >= 7 and g["current_cents"] / frac > g["target_cents"]:
                out.append(Insight(
                    kind="cap_pace", severity="notice", key=key + f":{ctx.month}:pace",
                    title=f"{g['category']} is on pace to pass its {fmt(g['target_cents'])} cap ({fmt(int(g['current_cents'] / frac))} projected)",
                    detail=f"{fmt(g['current_cents'])} spent with {int(frac * 100)}% of the month gone.",
                    amount_cents=int(g["current_cents"] / frac) - g["target_cents"]))
    return out
