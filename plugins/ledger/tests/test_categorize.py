from conftest import NOW, FakeBridge, account, tx

from ledger import categorize, db, sync


def _seed(conn, rows):
    bridge = FakeBridge([account("chk", "Checking", "100.00", transactions=rows)])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)


def cat(conn, tid):
    return db.one(conn, "SELECT c.name AS n, t.category_source AS s FROM transactions t "
                        "LEFT JOIN categories c ON c.id = t.category_id WHERE t.id = ?", (tid,))


def test_heuristics_cover_common_merchants(conn):
    _seed(conn, [
        tx("a", "2026-09-01", "-15.99", "NETFLIX.COM"),
        tx("b", "2026-09-01", "-80.00", "TRADER JOE'S #123"),
        tx("c", "2026-09-01", "-35.00", "OVERDRAFT FEE"),
        tx("d", "2026-09-01", "3000.00", "ACME PAYROLL DIRECT DEP"),
        tx("e", "2026-09-01", "-500.00", "ONLINE PAYMENT THANK YOU"),
        tx("f", "2026-09-01", "-12.00", "SOME UNKNOWN PLACE"),
    ])
    assert cat(conn, "a")["n"] == "Subscriptions"
    assert cat(conn, "b")["n"] == "Groceries"
    assert cat(conn, "c")["n"] == "Fees & Interest"
    assert cat(conn, "d")["n"] == "Income"
    assert cat(conn, "e")["n"] == "Transfer"
    assert cat(conn, "f")["n"] is None


def test_rules_beat_heuristics_and_user_beats_claude(conn):
    _seed(conn, [tx("a", "2026-09-01", "-15.99", "NETFLIX.COM")])
    categorize.add_rule(conn, "netflix", "Entertainment", source="claude")
    categorize.categorize(conn, only_uncategorized=False)
    assert cat(conn, "a") == {"n": "Entertainment", "s": "claude"}
    categorize.add_rule(conn, "netflix", "Kids", source="user")
    categorize.categorize(conn, only_uncategorized=False, include_user=True)
    assert cat(conn, "a") == {"n": "Kids", "s": "user"}
    rules = categorize.list_rules(conn)
    assert [r["source"] for r in rules] == ["claude", "user"]
    assert [r["hits"] for r in rules] == [1, 1]


def test_hand_set_category_is_never_overwritten(conn):
    _seed(conn, [tx("a", "2026-09-01", "-15.99", "NETFLIX.COM")])
    categorize.set_category(conn, ["a"], "Gifts & Donations", source="user")
    categorize.add_rule(conn, "netflix", "Entertainment", source="claude")
    categorize.categorize(conn, only_uncategorized=False)
    assert cat(conn, "a")["n"] == "Gifts & Donations"


def test_contains_and_regex_rules(conn):
    _seed(conn, [tx("a", "2026-09-01", "-9.00", "MYSTERY VENDOR 42"),
                 tx("b", "2026-09-01", "-9.00", "ACME WIDGETS INC")])
    categorize.add_rule(conn, "mystery", "Shopping", match_type="contains")
    categorize.add_rule(conn, r"^ACME\s+W", "Business", match_type="regex")
    categorize.categorize(conn)
    assert cat(conn, "a")["n"] == "Shopping" and cat(conn, "b")["n"] == "Business"


def test_alias_resolves_to_seed_category(conn):
    assert categorize.category_id(conn, "Restaurants") == categorize.category_id(conn, "Dining")
    assert categorize.category_id(conn, "nonexistent") is None
    new = categorize.category_id(conn, "Hobby Farm", create=True)
    assert new and categorize.category_name(conn, new) == "Hobby Farm"


def test_transfer_pairing_across_accounts(conn):
    bridge = FakeBridge([
        account("chk", "Checking", "100.00", transactions=[tx("out", "2026-09-02", "-400.00", "WEB TRNSFR TO SAV")]),
        account("sav", "Savings", "900.00", transactions=[tx("in", "2026-09-03", "400.00", "WEB TRNSFR FROM CHK")]),
    ])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert cat(conn, "out")["n"] == "Transfer" and cat(conn, "in")["n"] == "Transfer"
