"""Turn a bank description into a stable payee key.

"SQ *BLUE BOTTLE 0421 SAN FRANCISCO CA" and "SQ *BLUE BOTTLE 0422 SAN
FRANCISCO CA" must group together, and "NETFLIX.COM 866-579-7172" must be
the same payee as "PAYPAL *NETFLIX". The steps are data-driven
(data/payee_rules.json) so the table test can grow with real descriptions.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ledger import catalog

_DATA = Path(__file__).parent / "data" / "payee_rules.json"
MAX_TOKENS = 3


@lru_cache(maxsize=1)
def _rules():
    raw = json.loads(_DATA.read_text())
    strip = [(re.compile(r["pattern"]), r["replace"]) for r in raw["strip"]]
    states = "|".join(raw["states"])
    cities = sorted(raw["cities"], key=len, reverse=True)
    city_re = re.compile(r"\s+(?:" + "|".join(re.escape(c) for c in cities) + r")\s+(?:" + states + r")$")
    one_word_city_re = re.compile(r"\s+[A-Z]{3,}\s+(?:" + states + r")$")
    state_only_re = re.compile(r"\s+(?:" + states + r")$")
    return strip, city_re, one_word_city_re, state_only_re


def clean(description: str) -> str:
    """Uppercase, strip processor noise, numbers, locations; keep three words."""
    strip, city_re, one_word_city_re, state_only_re = _rules()
    s = (description or "").upper()
    for pattern, replacement in strip:
        s = pattern.sub(replacement, s)
    s = re.sub(r"[^A-Z0-9&'.\- ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Location suffixes: "<city> <ST>" for known multi-word cities, then a
    # single-word city, then a bare state. Only when a name is left over.
    # A one-word "city" is indistinguishable from the last word of a short
    # name ("UBER TRIP CA"), so that rule only fires when two words remain.
    for rx, min_left in ((city_re, 1), (one_word_city_re, 2), (state_only_re, 1)):
        stripped = rx.sub("", s)
        if stripped and stripped != s and len(stripped.split()) >= min_left:
            s = stripped
            break
    s = s.strip(" .-")
    tokens = [t for t in s.split(" ") if t]
    return " ".join(tokens[:MAX_TOKENS])


def payee_key(description: str) -> str:
    """Canonical service id when the catalog recognises the merchant,
    otherwise the cleaned description."""
    svc = catalog.match_service(description)
    if svc:
        return svc["id"]
    return clean(description)
