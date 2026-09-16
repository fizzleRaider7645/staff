from conftest import NOW, insert_account, insert_tx, monthly, snapshot

from ledger import goals, insights


def by_kind(found, kind):
    return [i for i in found if i.kind == kind]


def test_subscription_roster_and_trial(conn):
    insert_account(conn, "chk", "Checking", 500000)
    monthly(conn, "nf", "chk", 1, 6, -1599, "NETFLIX.COM", "Subscriptions")
    monthly(conn, "cg", "chk", 4, 4, 0, "OPENAI *CHATGPT SUBSCR", "Subscriptions", amounts=[0, -2000, -2000, -2000])
    found = insights.run_all(conn, NOW)
    roster = by_kind(found, "subscriptions")[0]
    assert roster.amount_cents == 3599 and len(roster.evidence) == 2 and "2 active subscriptions" in roster.title
    trial = by_kind(found, "trial_converted")[0]
    assert "OpenAI" in trial.title and trial.amount_cents == 2000


def test_price_increase(conn):
    insert_account(conn, "chk", "Checking", 500000)
    monthly(conn, "nf", "chk", 1, 5, 0, "NETFLIX.COM", "Subscriptions", amounts=[-1599] * 4 + [-1799])
    monthly(conn, "sp", "chk", 2, 5, -1099, "SPOTIFY USA", "Subscriptions")
    found = by_kind(insights.run_all(conn, NOW), "price_increase")
    assert len(found) == 1 and "Netflix" in found[0].title and found[0].amount_cents == 200 * 12
    assert found[0].key.endswith(":1799")


def test_overlapping_streaming(conn):
    insert_account(conn, "chk", "Checking", 500000)
    monthly(conn, "nf", "chk", 1, 4, -1599, "NETFLIX.COM", "Subscriptions")
    monthly(conn, "hu", "chk", 5, 4, -999, "HULU", "Subscriptions")
    monthly(conn, "sp", "chk", 2, 4, -1099, "SPOTIFY USA", "Subscriptions")
    found = by_kind(insights.run_all(conn, NOW), "overlap")
    assert len(found) == 1 and "video streaming" in found[0].title and found[0].amount_cents == 1599
    assert set(found[0].title.split(": ")[1].split(", ")) == {"Netflix", "Hulu"}


def test_fees_and_interest(conn):
    insert_account(conn, "chk", "Checking", 500000)
    insert_account(conn, "card", "Visa", -50000, kind="credit")
    insert_tx(conn, "f1", "chk", "2026-09-03", -3500, "OVERDRAFT FEE", "Fees & Interest")
    insert_tx(conn, "i1", "card", "2026-09-05", -4200, "INTEREST CHARGE ON PURCHASES", "Fees & Interest")
    insert_tx(conn, "f0", "chk", "2026-07-01", -1000, "MONTHLY SERVICE FEE", "Fees & Interest")
    found = insights.run_all(conn, NOW)
    interest = by_kind(found, "interest")[0]
    assert interest.severity == "warn" and interest.amount_cents == 4200 and interest.evidence == ["i1"]
    fees = by_kind(found, "fees")[0]
    assert fees.amount_cents == 7700 and "$8,700.00" not in fees.title and "over 90" in fees.title


def test_unusual_spend_and_pace(conn):
    insert_account(conn, "chk", "Checking", 500000)
    for m, amt in (("2026-05", -20000), ("2026-06", -20000), ("2026-07", -20000), ("2026-08", -60000), ("2026-09", -25000)):
        insert_tx(conn, f"d{m}", "chk", f"{m}-10", amt, "SUSHI PLACE", "Dining")
    found = insights.run_all(conn, NOW)
    spike = by_kind(found, "unusual_spend")[0]
    assert "Dining" in spike.title and "3.0x" in spike.title and spike.amount_cents == 40000
    pace = by_kind(found, "spend_pace")[0]
    assert "$500.00" in pace.title and pace.amount_cents == 30000


def test_obligations_against_cash(conn):
    insert_account(conn, "chk", "Checking", 1000, kind="checking")
    monthly(conn, "nf", "chk", 1, 4, -1599, "NETFLIX.COM", "Subscriptions")
    found = by_kind(insights.run_all(conn, NOW), "obligations")
    assert found[0].severity == "alert" and found[0].amount_cents == 1599 and "2026-10-01" in found[0].detail
    conn.execute("UPDATE accounts SET balance_cents = 100000 WHERE id = 'chk'"); conn.commit()
    assert by_kind(insights.run_all(conn, NOW), "obligations")[0].severity == "info"
    insert_account(conn, "card", "Visa", -150000, kind="credit")
    warn = by_kind(insights.run_all(conn, NOW), "obligations")[0]
    assert warn.severity == "warn" and "$1,500.00" in warn.title


def test_goal_insights(conn):
    insert_account(conn, "sav", "Savings", 100000, kind="savings")
    insert_account(conn, "chk", "Checking", 100000)
    goals.add(conn, "House", 5000000, target_date="2027-01-01", account_id="sav", now=NOW)
    goals.add(conn, "Dining cap", 10000, category="Dining", now=NOW)
    insert_tx(conn, "d1", "chk", "2026-09-04", -12000, "STEAK HOUSE", "Dining")
    found = insights.run_all(conn, NOW)
    behind = by_kind(found, "goal_behind")[0]
    assert "House" in behind.title and "never" in behind.title
    over = by_kind(found, "cap_exceeded")[0]
    assert over.severity == "warn" and over.amount_cents == 2000


def test_month_over_month_and_duplicates(conn):
    insert_account(conn, "chk", "Checking", 100000)
    insert_tx(conn, "g1", "chk", "2026-07-10", -10000, "SAFEWAY", "Groceries")
    insert_tx(conn, "g2", "chk", "2026-08-10", -20000, "SAFEWAY", "Groceries")
    insert_tx(conn, "x1", "chk", "2026-09-09", -4500, "SUSHI PLACE", "Dining")
    insert_tx(conn, "x2", "chk", "2026-09-09", -4500, "SUSHI PLACE", "Dining")
    found = insights.run_all(conn, NOW)
    mom = by_kind(found, "month_over_month")[0]
    assert "Groceries up $100.00" in mom.title and mom.amount_cents == 10000
    dup = by_kind(found, "duplicate_charge")[0]
    assert dup.amount_cents == 4500 and sorted(dup.evidence) == ["x1", "x2"]


def test_dismissal_and_ordering(conn):
    insert_account(conn, "chk", "Checking", 1000)
    insert_account(conn, "card", "Visa", -50000, kind="credit")
    monthly(conn, "nf", "chk", 1, 4, -1599, "NETFLIX.COM", "Subscriptions")
    insert_tx(conn, "i1", "card", "2026-09-05", -4200, "INTEREST CHARGE", "Fees & Interest")
    found = insights.run_all(conn, NOW)
    assert found[0].kind == "obligations" and found[0].severity == "alert"
    key = by_kind(found, "interest")[0].key
    insights.dismiss(conn, key, now=NOW)
    assert not by_kind(insights.run_all(conn, NOW), "interest")
    assert by_kind(insights.run_all(conn, NOW, include_dismissed=True), "interest")
    assert insights.undismiss(conn, key) and by_kind(insights.run_all(conn, NOW), "interest")
    assert all(i.severity in ("warn", "alert") for i in insights.run_all(conn, NOW, min_severity="warn"))
    assert [i.kind for i in insights.run_all(conn, NOW, kinds=["subscriptions"])] == ["subscriptions"]
