from conftest import NOW, insert_account, insert_tx, monthly

from ledger import recurring
from ledger.money import date_to_epoch

DAY = 86400


def setup(conn):
    insert_account(conn, "chk", "Checking", 100000)
    insert_account(conn, "card", "Visa", -20000, kind="credit")


def test_monthly_subscription(conn):
    setup(conn)
    ids = monthly(conn, "nf", "chk", 1, 6, -1599, "NETFLIX.COM", "Subscriptions")
    found = recurring.redetect(conn, NOW)
    assert len(found) == 1
    s = found[0]
    assert (s.cadence, s.kind, s.is_subscription, s.service_id, s.occurrences, s.status) == \
        ("monthly", "subscription", True, "netflix", 6, "active")
    assert s.typical_amount_cents == 1599 and s.members == ids
    assert s.next_expected == date_to_epoch("2026-09-01") + 30 * DAY
    r = recurring.roster(conn)
    assert r[0]["label"] == "Netflix" and r[0]["monthly_cents"] == 1599 and r[0]["account"] == "Checking"


def test_biweekly_and_weekly(conn):
    setup(conn)
    for i in range(5):
        insert_tx(conn, f"g{i}", "chk", f"2026-0{7 + (i * 14) // 31}-{1 + (i * 14) % 31:02d}", -2500, "PLANET FIT CLUB FEE", "Health")
    for i in range(6):
        insert_tx(conn, f"w{i}", "card", f"2026-08-{3 + i * 7:02d}" if 3 + i * 7 <= 31 else f"2026-09-{3 + i * 7 - 31:02d}",
                  -1200, "WEEKLY LAUNDRY SVC", "Personal Care")
    found = {s.payee_key: s for s in recurring.redetect(conn, NOW)}
    assert found["planet-fitness"].cadence == "biweekly"
    assert recurring.monthly_equivalent(2500, "biweekly") == round(2500 * 26 / 12)
    assert found["WEEKLY LAUNDRY SVC"].cadence == "weekly"


def test_annual_needs_only_two_points_but_nothing_else_does(conn):
    setup(conn)
    insert_tx(conn, "a1", "chk", "2025-09-10", -13900, "AMAZON PRIME MEMBERSHIP", "Subscriptions")
    insert_tx(conn, "a2", "chk", "2026-09-08", -13900, "AMAZON PRIME MEMBERSHIP", "Subscriptions")
    insert_tx(conn, "b1", "chk", "2026-05-10", -5000, "RANDOM SHOP", "Shopping")
    insert_tx(conn, "b2", "chk", "2026-08-18", -5000, "RANDOM SHOP", "Shopping")
    found = recurring.redetect(conn, NOW)
    assert [s.payee_key for s in found] == ["amazon-prime"]
    assert found[0].cadence == "annual" and found[0].occurrences == 2
    assert recurring.monthly_equivalent(13900, "annual") == round(13900 / 12)


def test_variable_utility_is_a_bill_not_a_subscription(conn):
    setup(conn)
    monthly(conn, "pge", "chk", 12, 5, 0, "PG&E EZ-PAY", "Utilities", amounts=[-12000, -6000, -18000, -5000, -16000])
    monthly(conn, "net", "chk", 5, 5, -8000, "COMCAST CABLE COMM", "Utilities")
    found = {s.payee_key: s for s in recurring.redetect(conn, NOW)}
    assert found["PG&E EZ-PAY"].kind == "variable" and not found["PG&E EZ-PAY"].is_subscription
    assert found["comcast"].kind == "bill" and not found["comcast"].is_subscription
    assert recurring.roster(conn, subscriptions_only=True) == []
    assert len(recurring.roster(conn)) == 2


def test_price_change_does_not_split_the_series(conn):
    setup(conn)
    monthly(conn, "nf", "chk", 1, 6, 0, "NETFLIX.COM", "Subscriptions", amounts=[-1599] * 4 + [-1799] * 2)
    found = recurring.redetect(conn, NOW)
    assert len(found) == 1 and found[0].last_amount_cents == 1799 and found[0].typical_amount_cents == 1599


def test_month_end_dates_still_read_as_monthly(conn):
    setup(conn)
    for i, d in enumerate(["2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31"]):
        insert_tx(conn, f"r{i}", "chk", d, -210000, "ACME PROPERTY MGMT RENT", "Housing")
    found = recurring.redetect(conn, NOW)
    assert len(found) == 1 and found[0].cadence == "monthly" and found[0].kind == "bill"


def test_lapsed_series(conn):
    setup(conn)
    monthly(conn, "old", "chk", 1, 4, -999, "HULU", "Subscriptions", end="2026-05")
    found = recurring.redetect(conn, NOW)
    assert found[0].status == "lapsed"
    assert recurring.roster(conn) == [] and recurring.roster(conn, include_lapsed=True)[0]["status"] == "lapsed"


def test_user_overrides_survive_redetection(conn):
    setup(conn)
    monthly(conn, "nf", "chk", 1, 6, -1599, "NETFLIX.COM", "Subscriptions")
    sid = recurring.redetect(conn, NOW)[0].id
    assert recurring.set_override(conn, sid, label="Family Netflix", status="ignored", now=NOW)
    recurring.redetect(conn, NOW + DAY)
    assert recurring.roster(conn) == []
    r = recurring.roster(conn, include_ignored=True)[0]
    assert r["label"] == "Family Netflix" and r["status"] == "ignored" and r["id"] == sid
    assert recurring.set_override(conn, sid, status="", now=NOW)
    assert recurring.roster(conn)[0]["label"] == "Family Netflix"
    assert not recurring.set_override(conn, "nope", label="x")


def test_vanished_series_is_dropped_unless_the_user_touched_it(conn):
    setup(conn)
    monthly(conn, "nf", "chk", 1, 6, -1599, "NETFLIX.COM", "Subscriptions")
    monthly(conn, "sp", "chk", 3, 6, -1099, "SPOTIFY USA", "Subscriptions")
    found = {s.payee_key: s.id for s in recurring.redetect(conn, NOW)}
    recurring.set_override(conn, found["spotify"], label="Kept", now=NOW)
    conn.execute("DELETE FROM transactions"); conn.commit()
    recurring.redetect(conn, NOW)
    rows = recurring.roster(conn, include_lapsed=True)
    assert [r["label"] for r in rows] == ["Kept"] and rows[0]["status"] == "lapsed"


def test_transfers_income_and_pending_are_ignored(conn):
    setup(conn)
    monthly(conn, "pay", "card", 15, 5, -50000, "AUTOPAY PAYMENT THANK YOU", "Transfer")
    monthly(conn, "sal", "chk", 1, 5, 300000, "ACME PAYROLL", "Income")
    for i in range(4):
        insert_tx(conn, f"p{i}", "chk", f"2026-0{6 + i}-01", -500, "PENDING COFFEE", "Dining", pending=True)
    assert recurring.redetect(conn, NOW) == []


def test_classify_tolerances():
    assert recurring.classify([30, 31, 28, 31]) == ("monthly", 30, 1.0)
    assert recurring.classify([7, 7, 8, 6]) == ("weekly", 7, 1.0)
    assert recurring.classify([30, 31, 60, 31])[0] == "monthly"       # one skipped month, still 75% fit
    assert recurring.classify([30, 60, 90]) is None
    assert recurring.classify([]) is None
