from conftest import NOW, FakeBridge, account, tx

from ledger import reports, sync


def _seed(conn):
    bridge = FakeBridge([
        account("chk", "Checking", "1000.00", available="950.00", transactions=[
            tx("i1", "2026-09-05", "2500.00", "ACME PAYROLL DIRECT DEP"),
            tx("g1", "2026-09-06", "-80.00", "TRADER JOE'S #1"),
            tx("g2", "2026-09-12", "-20.00", "TRADER JOE'S #2"),
            tx("n1", "2026-09-01", "-15.99", "NETFLIX.COM"),
            tx("f1", "2026-09-02", "-35.00", "OVERDRAFT FEE"),
            tx("t1", "2026-09-03", "-300.00", "ONLINE PAYMENT THANK YOU"),
            tx("p1", "2026-08-06", "-50.00", "TRADER JOE'S #1"),
        ]),
        account("card", "Visa Credit Card", "-250.00", transactions=[
            tx("c1", "2026-09-10", "-40.00", "SHELL OIL 123"),
        ]),
    ])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)


def test_monthly_report_math(conn):
    _seed(conn)
    rep = reports.monthly_report(conn, "2026-09")
    assert rep["income_cents"] == 250000
    # groceries 100 + netflix 15.99 + fee 35 + gas 40; the transfer is excluded
    assert rep["expense_cents"] == 10000 + 1599 + 3500 + 4000
    assert rep["net_cents"] == rep["income_cents"] - rep["expense_cents"]
    assert rep["fees_cents"] == 3500
    assert rep["previous"]["month"] == "2026-08" and rep["previous"]["expense_cents"] == 5000
    by_cat = {c["key"]: c["spent_cents"] for c in rep["by_category"]}
    assert by_cat["Groceries"] == 10000 and "Transfer" not in by_cat and "Income" not in by_cat
    assert rep["top_payees"][0]["key"] == "TRADER JOE'S"


def test_cash_flow_and_net_worth(conn):
    _seed(conn)
    flow = reports.cash_flow(conn, 3, "2026-09")
    assert [m["month"] for m in flow] == ["2026-07", "2026-08", "2026-09"]
    assert flow[1]["expense_cents"] == 5000 and flow[0]["count"] == 0
    nw = reports.net_worth(conn)
    assert nw["total_cents"] == 100000 - 25000
    assert nw["assets_cents"] == 100000 and nw["liabilities_cents"] == -25000
    assert nw["cash_cents"] == 95000


def test_transaction_filters(conn):
    _seed(conn)
    assert len(reports.transactions(conn, start="2026-09-01", end="2026-10-01")) == 7
    assert [r["id"] for r in reports.transactions(conn, category="Groceries", start="2026-09-01")] == ["g2", "g1"]
    assert [r["id"] for r in reports.transactions(conn, text="shell")] == ["c1"]
    assert [r["id"] for r in reports.transactions(conn, account="Visa")] == ["c1"]
    assert [r["id"] for r in reports.transactions(conn, min_cents=30000)] == ["i1", "t1"]
    assert reports.transactions(conn, limit=2).__len__() == 2


def test_zero_available_balance_is_treated_as_unreported():
    # SimpleFIN's available-balance is optional and several institutions send
    # a literal 0 instead of omitting it, which emptied cash on hand.
    assert reports.spendable_cents({"available_cents": 0, "balance_cents": 476406}) == 476406
    assert reports.spendable_cents({"available_cents": None, "balance_cents": 476406}) == 476406
    # A real available balance, including a real zero, is still believed.
    assert reports.spendable_cents({"available_cents": 100193, "balance_cents": 100193}) == 100193
    assert reports.spendable_cents({"available_cents": 0, "balance_cents": 0}) == 0
    assert reports.spendable_cents({"available_cents": 500, "balance_cents": 476406}) == 500


def test_hidden_accounts_drop_out_of_every_total(conn):
    _seed(conn)
    before = reports.totals(conn, "2026-09-01", "2026-10-01")
    nw_before = reports.net_worth(conn)
    hidden = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE accounts SET hidden = 1 WHERE id = ?", (hidden,))
    conn.commit()
    after = reports.totals(conn, "2026-09-01", "2026-10-01")
    assert after["count"] < before["count"], "spending still counted a hidden account"
    assert reports.net_worth(conn)["total_cents"] != nw_before["total_cents"]
    assert all(a["id"] != hidden for a in reports.accounts(conn))
    # Naming the account still finds its rows.
    assert reports.transactions(conn, account=hidden)
    assert all(t["account_id"] != hidden for t in reports.transactions(conn))
