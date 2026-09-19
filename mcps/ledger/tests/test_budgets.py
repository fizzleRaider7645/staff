"""Budgets: a monthly cap per category, with what you did not spend carrying
forward. The carry is the part that can lie quietly, so most of this is carry.
"""
import pytest
from conftest import NOW, insert_account, insert_tx

from ledger import budgets, db, reports
from ledger.money import date_to_epoch

SEP = date_to_epoch("2026-09-20") + 12 * 3600   # two thirds through September


@pytest.fixture
def ledger(conn):
    insert_account(conn, "chk", "Checking", 500000)
    return conn


def spend(conn, tid, month, cents, category="Groceries", day=5):
    insert_tx(conn, tid, "chk", f"{month}-{day:02d}", -cents, f"SHOP {tid}", category)


def test_a_budget_is_measured_against_the_same_spending_the_report_shows(ledger):
    spend(ledger, "a", "2026-09", 8000)
    spend(ledger, "b", "2026-09", 2000)
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-09", now=NOW)
    row = budgets.status(ledger, "2026-09", now=SEP)[0]
    start, end = "2026-09-01", "2026-10-01"
    assert row["spent_cents"] == reports.spent_by_category(ledger, start, end)["Groceries"] == 10000
    assert row["available_cents"] == 50000 and row["remaining_cents"] == 40000


def test_what_you_did_not_spend_carries_into_the_next_month(ledger):
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-07", now=NOW)
    spend(ledger, "jul", "2026-07", 30000)
    spend(ledger, "aug", "2026-08", 45000)
    # July left $200, August left $50, so September opens $250 up.
    assert budgets.carry_into(ledger, _cid(ledger), "2026-09") == 25000
    row = budgets.status(ledger, "2026-09", now=SEP)[0]
    assert row["carry_in_cents"] == 25000 and row["available_cents"] == 75000


def test_overspending_carries_forward_negative_and_uncapped(ledger):
    # A cap that forgives itself every month is not a cap.
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-07", now=NOW)
    spend(ledger, "jul", "2026-07", 90000)
    spend(ledger, "aug", "2026-08", 80000)
    assert budgets.carry_into(ledger, _cid(ledger), "2026-09") == -70000
    row = budgets.status(ledger, "2026-09", now=SEP)[0]
    assert row["available_cents"] == -20000 and row["over_budget"] is True


def test_unspent_carry_stops_accumulating(ledger):
    # Otherwise a category nobody touches becomes an unlimited allowance.
    budgets.set_budget(ledger, "Groceries", 10000, start_month="2026-01",
                       carry_cap_months=2.0, now=NOW)
    assert budgets.carry_into(ledger, _cid(ledger), "2026-09") == 20000


def test_rollover_can_be_turned_off(ledger):
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-07", rollover=False, now=NOW)
    spend(ledger, "jul", "2026-07", 10000)
    row = budgets.status(ledger, "2026-09", now=SEP)[0]
    assert row["carry_in_cents"] == 0 and row["available_cents"] == 50000


def test_a_carry_can_be_reset_or_topped_up(ledger):
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-07", now=NOW)
    spend(ledger, "jul", "2026-07", 200000)
    assert budgets.carry_into(ledger, _cid(ledger), "2026-08") == -150000
    budgets.adjust(ledger, "Groceries", "2026-08", "reset", note="one-off, not repaying it", now=NOW)
    assert budgets.carry_into(ledger, _cid(ledger), "2026-09") == 50000
    budgets.adjust(ledger, "Groceries", "2026-09", "add", 10000, now=NOW)
    assert budgets.status(ledger, "2026-09", now=SEP)[0]["carry_in_cents"] == 50000


def test_changing_an_amount_keeps_what_the_old_one_said(ledger):
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-07", now=NOW)
    budgets.set_budget(ledger, "Groceries", 80000, start_month="2026-09", now=NOW)
    assert budgets.budget_for(ledger, "Groceries", "2026-07")["amount_cents"] == 50000
    assert budgets.budget_for(ledger, "Groceries", "2026-09")["amount_cents"] == 80000
    assert len(budgets.status(ledger, "2026-09", now=SEP)) == 1, "one budget in effect, not two"


def test_run_rate_and_envelope_are_different_questions(ledger):
    # Two thirds through the month, $400 of a $500 budget spent: the run rate
    # projects $600 and fails, but $250 of carry means the month is fine.
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-08", now=NOW)
    spend(ledger, "aug", "2026-08", 25000)
    spend(ledger, "sep", "2026-09", 40000)
    row = budgets.status(ledger, "2026-09", now=SEP)[0]
    assert row["carry_in_cents"] == 25000 and row["available_cents"] == 75000
    assert row["projected_cents"] == 60000
    assert row["over_rate"] is True, "spending faster than the budget"
    assert row["over_budget"] is False, "but the carry covers the month"


def test_spending_with_no_budget_is_reported_not_hidden(ledger):
    budgets.set_budget(ledger, "Groceries", 50000, start_month="2026-09", now=NOW)
    spend(ledger, "a", "2026-09", 10000)
    spend(ledger, "b", "2026-09", 30000, category="Dining")
    s = budgets.summary(ledger, "2026-09", now=SEP)
    assert s["unbudgeted"] == [{"category": "Dining", "spent_cents": 30000}]
    assert s["unbudgeted_cents"] == 30000


def test_a_suggestion_always_says_what_it_rests_on(ledger):
    spend(ledger, "a", "2026-09", 10000)
    for p in budgets.suggest(ledger, now=SEP):
        assert p["basis"] in ("median", "recurring", "one_month", "incomplete")
        assert p["confidence"] in ("high", "medium", "low", "none")
        assert p["note"]


def test_a_budget_needs_a_category_that_exists(ledger):
    with pytest.raises(ValueError, match="unknown category"):
        budgets.set_budget(ledger, "Yacht Maintenance", 100000, now=NOW)


def _cid(conn):
    return db.one(conn, "SELECT id FROM categories WHERE name = 'Groceries'")["id"]
