"""Budgets over, on pace to go over, quietly working, or missing entirely.

The wins are here on purpose. A budget tool that only ever tells you what
you got wrong is one you stop opening, and "this category has built up two
months of room" is as actionable as "this one is over" — it is where the money
to fix something else comes from.
"""
from __future__ import annotations

from ledger import budgets as budgets_mod
from ledger.insights import Insight
from ledger.money import MIN_DAY_FOR_PACE, fmt

# Spending with no budget, below which it is not worth a line.
UNBUDGETED_FLOOR = 20000
# Carry worth mentioning, as a share of the budget itself.
HEALTHY_CARRY = 1.0


def compute(ctx) -> list[Insight]:
    out: list[Insight] = []
    day = int(ctx.today[8:10])
    summary = budgets_mod.summary(ctx.conn, ctx.month, ctx.now)

    for b in summary["budgets"]:
        key = f"budget:{b['budget_id']}:{ctx.month}"
        over = b["spent_cents"] - b["available_cents"]
        if b["over_budget"]:
            share = b["spent_cents"] / b["available_cents"] if b["available_cents"] > 0 else 99
            out.append(Insight(
                kind="budget_over",
                severity="alert" if share >= 1.25 else "warn",
                key=key,
                title=f"{b['category']} is {fmt(over)} over its {fmt(b['available_cents'])} for {ctx.month}",
                detail=f"{fmt(b['spent_cents'])} spent against a {fmt(b['amount_cents'])} budget"
                       + (f" plus {fmt(b['carry_in_cents'])} carried in" if b["carry_in_cents"] else "")
                       + ".",
                amount_cents=over,
                suggested_action=f"Hold off on {b['category']} until {ctx.month} ends, or raise the "
                                 f"budget if {fmt(b['spent_cents'])} is what it really costs."))
        elif b["over_rate"] and day >= MIN_DAY_FOR_PACE:
            # Spending faster than the budget but still inside the month,
            # because carry is covering it. Both halves belong in the sentence.
            projected_over = b["projected_cents"] - b["amount_cents"]
            out.append(Insight(
                kind="budget_pace", severity="notice", key=key + ":pace",
                title=f"{b['category']} is running at {fmt(b['projected_cents'])} a month "
                      f"against a {fmt(b['amount_cents'])} budget",
                detail=f"{fmt(b['spent_cents'])} spent with {int(b['elapsed'] * 100)}% of {ctx.month} gone. "
                       + (f"{fmt(b['carry_in_cents'])} carried in covers it this month, "
                          f"but not a second one." if b["carry_in_cents"] > 0
                          else "Nothing carried in to absorb it."),
                amount_cents=projected_over))
        elif b["carry_in_cents"] >= HEALTHY_CARRY * b["amount_cents"] and b["amount_cents"] > 0:
            out.append(Insight(
                kind="budget_carry_built", severity="info", key=key + ":carry",
                title=f"{b['category']} has {fmt(b['carry_in_cents'])} of room built up",
                detail=f"Consistently under {fmt(b['amount_cents'])} a month. That is real money "
                       f"sitting in a category you are not using.",
                amount_cents=b["carry_in_cents"],
                suggested_action=f"Move some of it to a category that is over, or lower the "
                                 f"{b['category']} budget and put the difference into a goal."))

    biggest = [u for u in summary["unbudgeted"]
               if u["spent_cents"] >= UNBUDGETED_FLOOR and u["category"] != "Uncategorized"]
    if biggest:
        named = ", ".join(f"{u['category']} {fmt(u['spent_cents'])}" for u in biggest[:3])
        out.append(Insight(
            kind="budget_unbudgeted", severity="notice", key=f"budget:unbudgeted:{ctx.month}",
            title=f"{fmt(summary['unbudgeted_cents'])} of {ctx.month} spending has no budget",
            detail=f"{named}. A budget that covers part of the money will always look like it is working.",
            amount_cents=summary["unbudgeted_cents"],
            suggested_action="Set budgets for these, or decide out loud that they are not budgeted."))

    if summary["budgets"] and not summary["over_count"] and day >= MIN_DAY_FOR_PACE:
        out.append(Insight(
            kind="budget_healthy", severity="info", key=f"budget:healthy:{ctx.month}",
            title=f"Every budget is inside its limit with {int(100 - summary['budgets'][0]['elapsed'] * 100)}% "
                  f"of {ctx.month} left",
            detail=f"{fmt(summary['spent_cents'])} spent of {fmt(summary['available_cents'])} available "
                   f"across {len(summary['budgets'])} categories.",
            amount_cents=summary["remaining_cents"]))
    return out
