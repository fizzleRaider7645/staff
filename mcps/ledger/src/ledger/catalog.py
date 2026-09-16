"""Known services: canonical ids, tags for overlap detection, default
categories. Loaded from data/services.json; aliases are matched as whole
words inside the uppercased raw description, longest alias wins."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "services.json"


@lru_cache(maxsize=1)
def services() -> list[dict]:
    raw = json.loads(_DATA.read_text())
    for svc in raw:
        svc["_aliases"] = [
            (re.compile(r"(?<![A-Z0-9])" + re.escape(a.upper()) + r"(?![A-Z0-9])"), len(a))
            for a in [svc["name"]] + svc.get("aliases", [])
        ]
    return raw


@lru_cache(maxsize=4096)
def match_service(description: str) -> dict | None:
    text = (description or "").upper()
    best, best_len = None, 0
    for svc in services():
        for rx, length in svc["_aliases"]:
            if length > best_len and rx.search(text):
                best, best_len = svc, length
    return best


def service(service_id: str) -> dict | None:
    for svc in services():
        if svc["id"] == service_id:
            return svc
    return None


def public(svc: dict) -> dict:
    return {k: v for k, v in svc.items() if not k.startswith("_")}
