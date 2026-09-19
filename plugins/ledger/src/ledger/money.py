"""Money and calendar helpers.

Amounts are integer cents everywhere inside ledger. Parsing goes through
Decimal so "0.10" is 10 cents and never 9.999...; floats only appear at the
edges (MCP results, JSON output) and are produced from cents, never the
other way round.
"""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

_CENT = Decimal("1")


def parse_cents(value) -> int:
    """'12.30' -> 1230, '-1,234.5' -> -123450, '(4.00)' -> -400, 7 -> 700."""
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    if isinstance(value, int):
        return value * 100
    s = str(value).strip().replace(",", "").replace("−", "-").replace("$", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if not s:
        raise ValueError("empty amount")
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"not a number: {value!r}") from e
    return int((d * 100).quantize(_CENT, rounding=ROUND_HALF_EVEN))


def fmt(cents: int, currency: str = "USD") -> str:
    """1234 -> '$12.34', -5 -> '-$0.05'. Non-USD currencies use their code."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    body = f"{whole:,}.{frac:02d}"
    if currency in ("USD", "", None):
        return f"{sign}${body}"
    return f"{sign}{currency} {body}"


def dollars(cents: int | None) -> float | None:
    return None if cents is None else round(cents / 100, 2)


# --- dates ---------------------------------------------------------------
# Epoch seconds in, ISO dates out, always in the machine's local zone so a
# purchase on the 1st stays on the 1st in every report.

def epoch_to_date(epoch: int | float) -> str:
    return dt.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d")


def date_to_epoch(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").timestamp())


def add_days(day: str, n: int) -> str:
    d = dt.date.fromisoformat(day) + dt.timedelta(days=n)
    return d.isoformat()


def days_between(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def month_of(day: str) -> str:
    return day[:7]


def shift_month(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_bounds(month: str) -> tuple[str, str]:
    """('2026-09-01', '2026-10-01') — start inclusive, end exclusive."""
    return f"{month}-01", f"{shift_month(month, 1)}-01"


def days_in_month(month: str) -> int:
    return calendar.monthrange(int(month[:4]), int(month[5:7]))[1]


MIN_DAY_FOR_PACE = 7


def month_fraction(today: str) -> float:
    """How much of `today`'s month has elapsed, as a fraction."""
    return int(today[8:10]) / days_in_month(month_of(today))


def prorate(cents: int, today: str) -> int:
    """Month-to-date spending projected to the end of the month."""
    frac = month_fraction(today)
    return int(cents / frac) if frac > 0 else cents
