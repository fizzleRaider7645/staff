"""Matching bank descriptors against keyword tables.

A bank descriptor is a cramped, abbreviated, frequently truncated string, and
the obvious way to classify one — ask whether a keyword appears anywhere in it
— is wrong in a way that is invisible until you read the results. MOBIL matches
GOMOBILEPGH, which is parking. SPIRIT matches WINE AND SPIRITS, which is a
liquor store, and files it under airlines. Every such mistake looks like a
confident answer.

So a keyword has to land on a boundary, and the boundary is deliberately
asymmetric, because descriptors are asymmetric. Nothing alphanumeric may come
*before* a keyword: MOBIL inside GOMOBILEPGH is not Mobil, and 76 inside 1976
is not the gas station. Only a letter may not come *after* one: WENDY inside
WENDYS is fine but SPIRIT inside SPIRITS is not, while FEDEX259723989 and
BP#9622291 are exactly how banks write a store number after a merchant name.

Punctuation is a boundary either way, which is what lets TRADER JOE match
"TRADER JOE'S #123" and SAMS CLUB match "SAMSCLUB.COM". Keywords containing
punctuation of their own, like PG&E and H-E-B, match literally.

Two escape hatches, because some descriptors have no boundary to find:

- A keyword ending in `#` or `*` is a deliberate prefix (BP#, AMZN MKTP*).
- `squashed_match` drops every non-alphanumeric from both sides and asks
  whether the fragment is the start of the keyword. Processors truncate
  merchant names and drop their spaces — BESTBUY, GIANTEAGL, THEHOMEDE — and
  nothing else reaches them. It is a fallback only, for the remainder of a
  descriptor whose prefix has already been recognized.
"""
from __future__ import annotations

import re
from functools import lru_cache

_BEFORE = r"(?<![A-Z0-9])"   # nothing alphanumeric may precede a keyword
_AFTER = r"(?![A-Z])"        # only a letter may not follow one
MIN_SQUASHED = 6


@lru_cache(maxsize=8192)
def _pattern(keyword: str) -> re.Pattern:
    kw = keyword.upper().strip()
    if kw.endswith(("#", "*")):
        # A deliberate prefix: "AMZN MKTP*" must match whatever follows.
        return re.compile(_BEFORE + re.escape(kw))
    return re.compile(_BEFORE + re.escape(kw) + _AFTER)


def mentions(text: str, keyword: str) -> bool:
    """Does `keyword` appear in `text` as a whole token?"""
    return bool(_pattern(keyword).search((text or "").upper()))


def any_mention(text: str, keywords) -> bool:
    upper = (text or "").upper()
    return any(_pattern(k).search(upper) for k in keywords)


def first_mention(text: str, keywords) -> str | None:
    """The first keyword that lands, for recording why a decision was made."""
    upper = (text or "").upper()
    for k in keywords:
        if _pattern(k).search(upper):
            return k
    return None


def squash(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def squashed_match(fragment: str, keyword: str) -> bool:
    """Is `fragment` a truncation of `keyword`, ignoring punctuation?

    THEHOMEDE against "THE HOME DEPOT", GIANTEAGL against "GIANT EAGLE". Short
    fragments are refused: three characters would match almost anything.
    """
    f, k = squash(fragment), squash(keyword)
    if not k:
        return False
    # "THEHOMEDE" is The Home Depot; the keyword table says "HOME DEPOT".
    candidates = {f}
    if f.startswith("THE"):
        candidates.add(f[3:])
    # Only one direction: the fragment must be a truncation of the keyword.
    # The reverse would let the 3-letter TSA claim TSAOCAA, a bubble tea shop,
    # for the Travel category.
    return any(len(cand) >= MIN_SQUASHED and k.startswith(cand) for cand in candidates)
