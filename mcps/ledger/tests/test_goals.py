from conftest import NOW, insert_account, insert_tx, snapshot
import pytest

from ledger import goals


def test_savings_goal_progress_and_projection(conn):
    insert_account(conn, "sav", "Savings", 400000, kind="savings")
    snapshot(conn, "sav", "2026-06-17", 100000)
    snapshot(conn, "sav", "2026-09-15", 400000)
    gid = goals.add(conn, "Emergency fund", 1000000, target_date="2027-06-01", account_id="sav", now=NOW)
    g = goals.progress(conn, NOW)[0]
    assert g["id"] == gid and g["kind"] == "savings"
    assert g["current_cents"] == 400000 and g["remaining_cents"] == 600000 and g["percent"] == 40.0
    assert 95000 <= g["rate_cents_per_month"] <= 105000
    assert g["projected_date"] < "2027-04-01" and g["on_track"] is True and g["days_left"] == 259


def test_from_now_counts_only_new_savings(conn):
    insert_account(conn, "sav", "Savings", 400000, kind="savings")
    goals.add(conn, "Trip", 100000, account_id="sav", from_now=True, now=NOW)
    g = goals.progress(conn, NOW)[0]
    assert g["current_cents"] == 0 and g["percent"] == 0.0 and g["projected_date"] is None and g["on_track"] is None


def test_reached_goal(conn):
    insert_account(conn, "sav", "Savings", 400000, kind="savings")
    goals.add(conn, "Cushion", 300000, account_id="sav", target_date="2026-12-01", now=NOW)
    g = goals.progress(conn, NOW)[0]
    assert g["remaining_cents"] == 0 and g["projected_date"] == "2026-09-15" and g["on_track"] is True


def test_spending_cap(conn):
    insert_account(conn, "chk", "Checking", 100000)
    insert_tx(conn, "d1", "chk", "2026-09-02", -20000, "SUSHI PLACE", "Dining")
    gid = goals.add(conn, "Eat in more", 30000, category="Dining", now=NOW)
    g = goals.progress(conn, NOW)[0]
    assert g["kind"] == "cap" and g["current_cents"] == 20000 and g["on_track"] and g["remaining_cents"] == 10000
    insert_tx(conn, "d2", "chk", "2026-09-10", -15000, "TACO TRUCK", "Dining")
    g = goals.progress(conn, NOW)[0]
    assert g["current_cents"] == 35000 and not g["on_track"]
    assert goals.remove(conn, gid) and goals.progress(conn, NOW) == [] and not goals.remove(conn, gid)


def test_validation(conn):
    insert_account(conn, "sav", "Savings", 1, kind="savings")
    with pytest.raises(ValueError):
        goals.add(conn, "x", 1, now=NOW)
    with pytest.raises(ValueError):
        goals.add(conn, "x", 1, account_id="sav", category="Dining", now=NOW)
    with pytest.raises(ValueError):
        goals.add(conn, "x", 1, account_id="nope", now=NOW)
    with pytest.raises(ValueError):
        goals.add(conn, "x", 1, category="Nope Category", now=NOW)
