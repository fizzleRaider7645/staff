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
    # A row a rule decided is stamped by the rule, not by the rule's author.
    assert cat(conn, "a") == {"n": "Entertainment", "s": "rule"}
    categorize.add_rule(conn, "netflix", "Kids", source="user")
    categorize.categorize(conn, only_uncategorized=False)
    assert cat(conn, "a") == {"n": "Kids", "s": "rule"}
    rules = categorize.list_rules(conn)
    assert [r["source"] for r in rules] == ["claude", "user"]
    assert [r["hits"] for r in rules] == [1, 1]


def test_a_row_a_rule_got_wrong_can_still_be_fixed(conn):
    # Stamping rule output with the rule's own source made it look hand-set,
    # so the row froze and the only way back was editing the database.
    _seed(conn, [tx("a", "2026-09-01", "-80.00", "TRADER JOE'S #123")])
    rid = categorize.add_rule(conn, "trader joe's", "Travel", source="user")
    categorize.categorize(conn, only_uncategorized=False)
    assert cat(conn, "a")["n"] == "Travel"
    categorize.remove_rule(conn, rid)
    categorize.categorize(conn, only_uncategorized=False)
    assert cat(conn, "a") == {"n": "Groceries", "s": "heuristic"}


def test_a_category_set_by_hand_is_still_untouchable(conn):
    _seed(conn, [tx("a", "2026-09-01", "-80.00", "TRADER JOE'S #123")])
    categorize.set_category(conn, ["a"], "Kids", source="user")
    categorize.categorize(conn, only_uncategorized=False)
    assert cat(conn, "a") == {"n": "Kids", "s": "user"}


def test_every_categorized_row_records_why(conn):
    _seed(conn, [
        tx("a", "2026-09-01", "-15.99", "NETFLIX.COM"),
        tx("b", "2026-09-01", "-80.00", "TRADER JOE'S #123"),
        tx("c", "2026-09-01", "-35.00", "OVERDRAFT FEE"),
    ])
    why = {r["id"]: r["category_reason"] for r in db.rows(
        conn, "SELECT id, category_reason FROM transactions")}
    assert why["a"] == "service:netflix"
    assert why["b"] == "keyword:TRADER JOE"
    assert why["c"].startswith("fee:")


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


def test_payments_to_an_unconnected_card_stay_visible_as_spending(conn):
    # The purchases behind them are invisible, so calling them transfers would
    # delete the money from the record entirely.
    _seed(conn, [
        tx("a", "2026-09-01", "-3901.02", "ACH: APPLECARD GSBANK"),
        tx("b", "2026-09-01", "-4693.47", "ACH: BARCLAYCARD US"),
        tx("c", "2026-09-01", "-5244.00", "ACH: BILT CARD"),
    ])
    for tid in ("a", "b", "c"):
        assert cat(conn, tid)["n"] == "Card Payments"
    assert db.one(conn, "SELECT kind FROM categories WHERE name = 'Card Payments'")["kind"] == "expense"


def test_a_card_payment_becomes_a_transfer_once_the_card_is_connected(conn):
    bridge = FakeBridge([
        account("chk", "Checking", "100.00", transactions=[
            tx("out", "2026-09-01", "-500.00", "ACH: BARCLAYCARD US")]),
        account("card", "Barclaycard", "-10.00", transactions=[
            tx("in", "2026-09-01", "500.00", "PAYMENT RECEIVED")]),
    ])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert cat(conn, "out")["n"] == "Transfer", "both halves are present, so it is money moving"
    assert cat(conn, "in")["n"] == "Transfer"


def test_nothing_inside_an_investment_or_loan_account_is_spending(conn):
    bridge = FakeBridge([
        account("plan", "MY SAVINGS PLAN", "191068.81", transactions=[
            tx("contrib", "2026-09-01", "936.97", "contribution"),
            tx("div", "2026-09-02", "12.00", "DIVIDEND")]),
        account("inv", "RESTRICTED STOCK UNITS", "3868.80", transactions=[
            tx("buy", "2026-09-01", "-25.00", "Invesco S&P 500 Equal Weight ETF")]),
        account("loan", "SoFi Personal Loan", "-46000.00", transactions=[
            tx("disb", "2026-09-01", "-46000.00", "Disbursement"),
            tx("fee", "2026-09-03", "-40.00", "INTEREST CHARGE")]),
    ])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    for tid in ("contrib", "div", "buy", "disb"):
        assert cat(conn, tid)["n"] == "Transfer", tid
    assert cat(conn, "fee")["n"] == "Fees & Interest", "a real charge inside the account still counts"


def test_borrowed_money_arriving_is_not_income(conn):
    _seed(conn, [tx("a", "2026-09-01", "25528.59", "ACH: SOFI PL DISB")])
    assert cat(conn, "a")["n"] == "Transfer"


def test_merchant_keywords_reach_the_names_that_were_missing(conn):
    _seed(conn, [
        tx("a", "2026-09-01", "-372.66", "BRGHTWHL L* LITTLE EXP"),
        tx("b", "2026-09-01", "-31.85", "Vinted"),
        tx("c", "2026-09-01", "-166.88", "TRAVELERS PER INS"),
        tx("d", "2026-09-01", "-757.66", "ACH: TOYOTA ACH LEASE"),
        tx("e", "2026-09-01", "-504.65", "ACH: Duquesne Light"),
        tx("f", "2026-09-01", "-46.42", "SAMS CLUB.COM"),
        tx("g", "2026-09-01", "-1715.24", "ACH: GUARANTEED RATE"),
    ])
    assert [cat(conn, t)["n"] for t in "abcdefg"] == [
        "Kids", "Shopping", "Insurance", "Transportation", "Utilities", "Groceries", "Housing"]


def test_paying_a_card_the_ledger_already_holds_is_a_transfer(conn):
    # Partial payments and statement timing stop the two halves from matching,
    # so pair_transfers never sees them; without this the payment would be
    # counted as spending on top of the card's own purchases.
    bridge = FakeBridge([
        account("chk", "Checking", "100.00", transactions=[
            tx("pay", "2026-09-01", "-200.00", "ACH: CHASE CREDIT CRD")]),
        account("card", "Chase Freedom Unlimited", "-3009.94", conn_id="chase",
                transactions=[tx("buy", "2026-09-02", "-40.00", "SOME SHOP")]),
    ])
    bridge.accounts[1]["org"] = {"id": "chase", "name": "Chase Bank"}
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert categorize.own_debt_issuers(conn) >= {"CHASE"}
    assert cat(conn, "pay")["n"] == "Transfer"


def test_issuers_are_only_taken_from_cards_and_loans_on_file(conn):
    bridge = FakeBridge([account("chk", "Checking", "100.00")])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert categorize.own_debt_issuers(conn) == set(), "a checking account is not an issuer"
    conn.execute("UPDATE accounts SET kind = 'credit' WHERE id = 'chk'")
    conn.commit()
    # "Demo Bank" contributes DEMO; BANK is too generic to identify anyone.
    assert categorize.own_debt_issuers(conn) == {"DEMO"}


def test_review_finds_a_wrong_category_not_just_a_missing_one(conn):
    from ledger import review
    bridge = FakeBridge([
        account("chk", "Checking - 9538", "100.00", transactions=[
            tx("w", "2026-09-01", "-500.00", "Withdrawal: To Savings - 8966")]),
        account("sav", "Savings - 8966", "500.00"),
    ])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    # Put it back the way the old keyword table had it.
    conn.execute("UPDATE transactions SET category_id = (SELECT id FROM categories WHERE name='Cash & ATM'), "
                 "category_source='heuristic' WHERE id = 'w'")
    conn.commit()
    checks = {a["check"] for a in review.anomalies(conn)}
    assert "transfer-shaped" in checks, "money between the user's own accounts was called spending"
    found = next(a for a in review.anomalies(conn) if a["check"] == "transfer-shaped")
    assert found["evidence"] == ["w"] and found["amount_cents"] == 50000


def test_reason_groups_say_what_each_category_rests_on(conn):
    from ledger import review
    _seed(conn, [
        tx("a", "2026-09-01", "-15.99", "NETFLIX.COM"),
        tx("b", "2026-09-02", "-80.00", "TRADER JOE'S #123"),
        tx("c", "2026-09-03", "-40.00", "TRADER JOE'S #456"),
    ])
    groups = {(g["category"], g["reason"]): g["count"] for g in review.reason_groups(conn)}
    assert groups[("Groceries", "keyword:TRADER JOE")] == 2
    assert groups[("Subscriptions", "service:netflix")] == 1


def test_a_repair_clears_a_category_nothing_stands_behind_any_more(conn):
    _seed(conn, [tx("a", "2026-09-01", "-12.00", "SOME UNKNOWN PLACE")])
    conn.execute("UPDATE transactions SET category_id = (SELECT id FROM categories WHERE name='Gas'), "
                 "category_source='heuristic' WHERE id='a'")
    conn.commit()
    categorize.categorize(conn, only_uncategorized=False)
    assert cat(conn, "a") == {"n": None, "s": None}, "a corrected keyword must not leave its answer behind"


def test_an_ordinary_run_never_clears_anything(conn):
    _seed(conn, [tx("a", "2026-09-01", "-12.00", "SOME UNKNOWN PLACE")])
    conn.execute("UPDATE transactions SET category_id = (SELECT id FROM categories WHERE name='Gas'), "
                 "category_source='heuristic' WHERE id='a'")
    conn.commit()
    categorize.categorize(conn)
    assert cat(conn, "a")["n"] == "Gas"
