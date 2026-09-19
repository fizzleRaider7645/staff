import json
import re

from conftest import NOW, insert_account, insert_tx, monthly, snapshot

from ledger import dashboard, goals


def _seed(conn):
    insert_account(conn, "chk", "Everyday Checking", 250000, available_cents=240000)
    insert_account(conn, "card", "Visa", -30000, kind="credit")
    for d, b in (("2026-07-01", 200000), ("2026-08-01", 220000), ("2026-09-15", 250000)):
        snapshot(conn, "chk", d, b)
    monthly(conn, "nf", "chk", 1, 5, -1599, "NETFLIX.COM", "Subscriptions")
    monthly(conn, "rent", "chk", 3, 5, -150000, "ACME PROPERTY MGMT RENT", "Housing")
    insert_tx(conn, "g1", "chk", "2026-09-06", -8000, "TRADER JOE'S #1", "Groceries")
    insert_tx(conn, "g0", "chk", "2026-08-06", -6000, "TRADER JOE'S #1", "Groceries")
    insert_tx(conn, "i1", "chk", "2026-09-05", 400000, "ACME PAYROLL", "Income")
    insert_tx(conn, "u1", "chk", "2026-09-07", -1200, "MYSTERY <VENDOR> & CO")
    goals.add(conn, "Cushion", 500000, target_date="2027-01-01", account_id="chk", now=NOW)


def test_snapshot_and_render(conn, home):
    _seed(conn)
    snap = dashboard.build_snapshot(conn, NOW)
    assert snap["net_worth_cents"] == 220000 and snap["subscriptions_monthly_cents"] == 1599
    assert [b["label"] for b in snap["bills"]] == ["Acme Property Mgmt"]
    assert snap["this_month"]["income_cents"] == 400000 and snap["uncategorized"] == 1
    assert snap["upcoming_total_cents"] == 1599 + 150000

    html_out = dashboard.render(snap)
    for heading in ("This month", "Accounts", "Cash flow", "Spending by category", "Insights", "Subscriptions",
                    "Recurring bills", "Goals", "Due in the next 30 days"):
        assert heading in html_out
    assert "Netflix" in html_out and "Cushion" in html_out and "$2,200.00" in html_out
    # Self-contained: no scripts that run, no external resources.
    assert not re.search(r'(src|href)="(https?:)?//', html_out)
    assert html_out.count("<script") == 1 and 'type="application/json"' in html_out
    assert "<svg" in html_out
    # User text is escaped, and the embedded JSON round-trips.
    assert "MYSTERY &lt;VENDOR&gt;" in html_out or "MYSTERY <VENDOR>" not in html_out.split('<script')[0]
    embedded = re.search(r'<script type="application/json" id="snapshot">(.*)</script>', html_out, re.S).group(1)
    data = json.loads(embedded.replace("<\\/", "</"))
    assert data["net_worth_cents"] == 220000

    path = dashboard.write(conn, now=NOW)
    assert path == home / "dashboard.html" and path.exists() and (path.stat().st_mode & 0o777) == 0o600
    assert not list(home.glob(".dashboard.*")), "no temp file left behind"


def test_empty_database_renders(conn):
    html_out = dashboard.render(dashboard.build_snapshot(conn, NOW))
    assert "no accounts yet" in html_out and "no sync yet" in html_out


def test_the_dashboard_shows_budgets_and_what_they_do_not_cover(conn):
    from conftest import insert_account, insert_tx
    from ledger import budgets, dashboard
    insert_account(conn, "chk", "Checking", 500000)
    insert_tx(conn, "a", "chk", "2026-09-05", -80000, "SHOP A", "Groceries")
    insert_tx(conn, "b", "chk", "2026-09-06", -30000, "SHOP B", "Shopping")
    budgets.set_budget(conn, "Groceries", 50000, start_month="2026-09", now=NOW)
    snap = dashboard.build_snapshot(conn, NOW)
    assert snap["budgets"]["over_count"] == 1
    html = dashboard.render(snap)
    assert "Budgets" in html and "Groceries" in html
    assert "has no budget" in html, "spending outside every budget must be visible"
