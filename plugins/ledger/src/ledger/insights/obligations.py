"""What is due in the next 30 days against the cash on hand."""
from __future__ import annotations

from ledger.insights import Insight
from ledger.money import epoch_to_date, fmt

DAY = 86400
HORIZON = 30


def compute(ctx) -> list[Insight]:
    horizon = ctx.now + HORIZON * DAY
    due = [s for s in ctx.roster if s["status"] == "active" and s["next_expected"] and ctx.now - 3 * DAY <= s["next_expected"] <= horizon]
    if not due:
        return []
    due.sort(key=lambda s: s["next_expected"])
    total = sum(s["typical_amount_cents"] for s in due)
    cards = sum(-a["balance_cents"] for a in ctx.net_worth["accounts"] if a["kind"] == "credit" and a["balance_cents"] < 0)
    cash = ctx.net_worth["cash_cents"]
    lines = "; ".join(f"{epoch_to_date(s['next_expected'])} {s['label']} {fmt(s['typical_amount_cents'])}" for s in due[:8])
    if len(due) > 8:
        lines += f"; and {len(due) - 8} more"
    if total > cash:
        severity, title = "alert", f"{fmt(total)} of recurring charges due within 30 days, more than the {fmt(cash)} in cash"
        action = "Move money into checking before the first of these posts."
    elif total + cards > cash:
        severity, title = "warn", (f"{fmt(total)} of recurring charges plus {fmt(cards)} of card balances due within 30 days, "
                                   f"against {fmt(cash)} in cash")
        action = "The charges are covered but the card balances are not; pay the cards down in stages."
    else:
        severity, title = "info", f"{fmt(total)} of recurring charges due in the next 30 days; {fmt(cash)} in cash covers them"
        action = None
    return [Insight(kind="obligations", severity=severity, key=f"obligations:{ctx.month}", title=title,
                    detail=lines, amount_cents=total, evidence=[s["id"] for s in due], suggested_action=action)]
