import pytest

from ledger.money import (add_days, days_in_month, dollars, fmt, month_bounds, parse_cents,
                          shift_month)


@pytest.mark.parametrize("raw,cents", [
    ("12.30", 1230), ("-12.30", -1230), ("0.1", 10), ("0.10", 10), ("1e2", 10000),
    ("-1,234.5", -123450), ("(4.00)", -400), ("$5", 500), (" 7 ", 700), (7, 700), (12.3, 1230),
    ("−3.25", -325), ("0.005", 0), ("0.015", 2), ("100.675", 10068),
])
def test_parse_cents(raw, cents):
    assert parse_cents(raw) == cents


@pytest.mark.parametrize("raw", ["", "abc", "1.2.3", None, True])
def test_parse_cents_rejects_junk(raw):
    with pytest.raises(ValueError):
        parse_cents(raw)


def test_fmt():
    assert fmt(1234) == "$12.34"
    assert fmt(-5) == "-$0.05"
    assert fmt(123456789) == "$1,234,567.89"
    assert fmt(250, "EUR") == "EUR 2.50"
    assert dollars(1234) == 12.34
    assert dollars(None) is None


def test_months():
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2026-12", 1) == "2027-01"
    assert month_bounds("2026-02") == ("2026-02-01", "2026-03-01")
    assert days_in_month("2028-02") == 29
    assert add_days("2026-02-28", 2) == "2026-03-02"
