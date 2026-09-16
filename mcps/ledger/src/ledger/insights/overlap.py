"""Two or more active subscriptions that do the same job."""
from __future__ import annotations

from ledger.insights import Insight
from ledger.money import fmt

LABELS = {"streaming": "video streaming", "music": "music", "cloud-storage": "cloud storage",
          "vpn": "VPN", "news": "news", "fitness": "fitness", "password-manager": "password manager",
          "meal-kit": "meal kit", "ai-assistant": "AI assistant", "delivery-membership": "delivery membership",
          "shopping-membership": "shopping membership", "wellness": "wellness", "gaming": "gaming"}


def compute(ctx) -> list[Insight]:
    by_tag: dict[str, dict[str, dict]] = {}
    for s in ctx.roster:
        if s["status"] != "active" or not s["is_subscription"] or not s.get("service"):
            continue
        for tag in s["service"].get("tags", []):
            by_tag.setdefault(tag, {})[s["service"]["id"]] = s
    out = []
    for tag, services in sorted(by_tag.items()):
        if len(services) < 2:
            continue
        subs = sorted(services.values(), key=lambda s: -s["monthly_cents"])
        total = sum(s["monthly_cents"] for s in subs)
        cheapest = min(s["monthly_cents"] for s in subs)
        out.append(Insight(
            kind="overlap", severity="info", key=f"overlap:{tag}:" + ",".join(sorted(services)),
            title=f"{len(subs)} {LABELS.get(tag, tag)} subscriptions: " + ", ".join(s["label"] for s in subs),
            detail=f"{fmt(total)} a month combined. Keeping one would save up to {fmt(total - cheapest)} a month.",
            amount_cents=total - cheapest, evidence=[s["id"] for s in subs],
            suggested_action="Pick the one you actually use and cancel the rest."))
    return out
