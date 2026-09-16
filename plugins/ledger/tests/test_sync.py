from conftest import NOW, FakeBridge, account, response, tx

import pytest

from ledger import db, sync
from ledger.money import date_to_epoch, epoch_to_date

DAY = 86400


def _bridge(extra=()):
    checking = account("chk", "Everyday Checking", "1250.00", available="1200.00", transactions=[
        tx("t1", "2026-09-01", "-15.99", "NETFLIX.COM 866-579-7172 CA"),
        tx("t2", "2026-09-03", "-42.10", "SQ *BLUE BOTTLE 0421 SAN FRANCISCO CA"),
        tx("t3", "2026-09-05", "2500.00", "ACME CORP PAYROLL DIRECT DEP"),
        tx("t4", "2026-09-14", "-8.50", "STARBUCKS STORE 05421 SEATTLE WA", pending=True),
        *extra,
    ])
    card = account("card", "Sapphire Credit Card", "-310.25", transactions=[
        tx("c1", "2026-09-02", "-60.00", "SHELL OIL 12345678 OAKLAND CA"),
    ])
    return FakeBridge([checking, card])


def test_first_run_fetches_latest_window_and_ingests(conn):
    bridge = _bridge()
    results = sync.run(conn, "https://u:p@b/sf", now=NOW, fetch=bridge, max_requests=1)
    assert len(results) == 1 and results[0].kind == "backfill"
    start, end = bridge.calls[0]
    assert end == NOW and (end - start) == sync.WINDOW_DAYS * DAY

    accts = db.rows(conn, "SELECT * FROM accounts ORDER BY id")
    assert [a["id"] for a in accts] == ["card", "chk"]
    chk = [a for a in accts if a["id"] == "chk"][0]
    assert chk["balance_cents"] == 125000 and chk["available_cents"] == 120000
    assert chk["kind"] == "checking"
    assert [a for a in accts if a["id"] == "card"][0]["kind"] == "credit"

    rows = db.rows(conn, "SELECT id, payee_key, pending, posted_date, category_id FROM transactions ORDER BY id")
    assert len(rows) == 5
    by_id = {r["id"]: r for r in rows}
    assert by_id["t1"]["payee_key"] == "netflix"
    assert by_id["t4"]["pending"] == 1 and by_id["t4"]["posted_date"] == "2026-09-14"
    assert all(r["category_id"] is not None for r in rows), "heuristics categorize everything here"
    assert conn.execute("SELECT COUNT(*) FROM balance_snapshots").fetchone()[0] == 2
    assert db.get_meta(conn, "backfill_cursor") == str(start)


def test_sync_is_idempotent(conn):
    bridge = _bridge()
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    before = db.rows(conn, "SELECT id, amount_cents, category_id, first_seen FROM transactions ORDER BY id")
    sync.run(conn, "u", now=NOW + 3600, fetch=bridge, max_requests=1)
    after = db.rows(conn, "SELECT id, amount_cents, category_id, first_seen FROM transactions ORDER BY id")
    assert before == after
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 5


def test_user_category_survives_resync(conn):
    from ledger import categorize
    # Dated inside the next incremental window (last 5 days), so the
    # second run re-fetches it with a changed description.
    recent = tx("t5", "2026-09-13", "-30.00", "LOCAL HARDWARE STORE")
    bridge = _bridge(extra=[recent])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    categorize.set_category(conn, ["t5"], "Groceries", source="user")
    recent["description"] = "LOCAL HARDWARE STORE (updated)"
    sync.run(conn, "u", now=NOW + DAY, fetch=bridge, max_requests=1)
    row = db.one(conn, "SELECT description, category_source, c.name AS cat FROM transactions t JOIN categories c ON c.id = t.category_id WHERE t.id = 't5'")
    assert row["description"].endswith("(updated)")
    assert row["cat"] == "Groceries" and row["category_source"] == "user"


def test_second_run_is_incremental_then_backfills(conn):
    bridge = _bridge()
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert not sync.backfill_done(conn)
    results = sync.run(conn, "u", now=NOW + DAY, fetch=bridge, max_requests=1 + sync.EMPTY_WINDOWS_TO_STOP)
    kinds = [r.kind for r in results]
    assert kinds == ["incremental"] + ["backfill"] * sync.EMPTY_WINDOWS_TO_STOP
    inc_start, inc_end = bridge.calls[1]
    assert inc_end == NOW + DAY and inc_start == NOW - sync.OVERLAP_DAYS * DAY
    # Backfill windows walk backwards, each overlapping the previous by 5 days.
    (b1s, b1e), (b2s, b2e) = bridge.calls[2], bridge.calls[3]
    first_start = bridge.calls[0][0]
    assert b1e == first_start + sync.OVERLAP_DAYS * DAY and b1e - b1s == sync.WINDOW_DAYS * DAY
    assert b2e == b1s + sync.OVERLAP_DAYS * DAY
    # Enough empty windows in a row end the backfill.
    assert sync.backfill_done(conn)
    results = sync.run(conn, "u", now=NOW + 2 * DAY, fetch=bridge, max_requests=5)
    assert [r.kind for r in results] == ["incremental"]


def test_backfill_resumes_across_runs_and_finds_old_history(conn):
    old = [tx("o1", "2026-03-10", "-99.00", "OLD PURCHASE"), tx("o2", "2025-11-20", "-5.00", "OLDER")]
    bridge = _bridge(extra=old)
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    sync.run(conn, "u", now=NOW + DAY, fetch=bridge, max_requests=2)   # incremental + 1 backfill
    assert not sync.backfill_done(conn)
    cursor_after = int(db.get_meta(conn, "backfill_cursor"))
    # Daily runs keep walking back until two windows in a row are empty.
    for day in range(2, 12):
        sync.run(conn, "u", now=NOW + day * DAY, fetch=bridge, max_requests=6)
        if sync.backfill_done(conn):
            break
    assert int(db.get_meta(conn, "backfill_cursor")) < cursor_after
    ids = {r["id"] for r in db.rows(conn, "SELECT id FROM transactions")}
    assert {"o1", "o2"} <= ids
    assert sync.backfill_done(conn)
    # Every request stayed inside the bridge's recommended range.
    assert all(e - s <= sync.WINDOW_DAYS * DAY for s, e in bridge.calls)


def test_request_budget_is_enforced(conn):
    bridge = _bridge()
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    # The run may ask for 6 but only 3 remain under a ceiling of 4.
    results = sync.run(conn, "u", now=NOW + 60, fetch=bridge, max_requests=6, ceiling=4)
    assert sum(r.requests for r in results) == 3
    assert sync.requests_last_24h(conn, NOW + 60) == 4
    with pytest.raises(sync.BudgetExhausted):
        sync.run(conn, "u", now=NOW + 120, fetch=bridge, max_requests=1, ceiling=4)
    # A day later the window has rolled over.
    assert sync.budget_available(conn, NOW + 2 * DAY, 4) == 4
    assert sync.run(conn, "u", now=NOW + 2 * DAY, fetch=bridge, max_requests=1, ceiling=4)


def test_pending_transaction_superseded_by_posted_twin(conn):
    bridge = _bridge()
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert db.one(conn, "SELECT pending FROM transactions WHERE id = 't4'")["pending"] == 1
    # The bank posts it under a new id two days later and drops the pending one.
    chk = bridge.accounts[0]
    chk["transactions"] = [t for t in chk["transactions"] if t["id"] != "t4"]
    chk["transactions"].append(tx("t4-posted", "2026-09-16", "-8.50", "STARBUCKS STORE 05421 SEATTLE WA"))
    sync.run(conn, "u", now=NOW + 2 * DAY, fetch=bridge, max_requests=1)
    old = db.one(conn, "SELECT superseded_by, removed_at FROM transactions WHERE id = 't4'")
    assert old["superseded_by"] == "t4-posted" and old["removed_at"] is not None
    live = db.rows(conn, "SELECT id FROM transactions WHERE removed_at IS NULL AND payee_key = 'STARBUCKS STORE'")
    assert [r["id"] for r in live] == ["t4-posted"]


def test_pending_dropped_by_bank_is_retired(conn):
    bridge = _bridge()
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    chk = bridge.accounts[0]
    chk["transactions"] = [t for t in chk["transactions"] if t["id"] != "t4"]
    sync.run(conn, "u", now=NOW + 2 * DAY, fetch=bridge, max_requests=1)
    old = db.one(conn, "SELECT superseded_by, removed_at FROM transactions WHERE id = 't4'")
    assert old["superseded_by"] is None and old["removed_at"] is not None


def test_errlist_is_logged_and_returned(conn):
    bridge = _bridge()
    bridge.errlist = ["Demo Bank: connection needs re-authentication"]
    results = sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert results[0].errlist == bridge.errlist
    assert "re-authentication" in sync.last_sync(conn)["errlist_json"]


def test_fetch_failure_is_logged_and_raised(conn):
    from ledger.simplefin import SimpleFinError

    def broken(*a, **k):
        raise SimpleFinError("HTTP 500 from SimpleFIN: boom")

    with pytest.raises(SimpleFinError):
        sync.run(conn, "u", now=NOW, fetch=broken, max_requests=1)
    last = sync.last_sync(conn)
    assert last["ok"] == 0 and "boom" in last["error"]
    assert db.get_meta(conn, "last_incremental_end") is None, "a failed first run leaves nothing half-set"


def test_pending_never_becomes_1970(conn):
    bridge = FakeBridge([account("a", "Checking", "1.00", transactions=[
        {"id": "p", "posted": 0, "amount": "-1.00", "description": "PENDING THING", "pending": True}])])
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    assert db.one(conn, "SELECT posted_date FROM transactions WHERE id = 'p'")["posted_date"] == epoch_to_date(NOW)


def test_user_account_kind_survives(conn):
    bridge = _bridge()
    sync.run(conn, "u", now=NOW, fetch=bridge, max_requests=1)
    conn.execute("UPDATE accounts SET kind = 'savings', kind_source = 'user' WHERE id = 'chk'")
    conn.commit()
    sync.run(conn, "u", now=NOW + DAY, fetch=bridge, max_requests=1)
    assert db.one(conn, "SELECT kind FROM accounts WHERE id = 'chk'")["kind"] == "savings"
