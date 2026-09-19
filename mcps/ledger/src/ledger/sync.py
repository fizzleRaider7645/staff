"""Pull accounts and transactions from SimpleFIN into the database.

Constraints from the bridge shape everything here: at most 24 requests a
day, 90 days per request, and a history that may reach back years. So the
first run fetches the latest 85 days, every later run fetches what changed
since last time, and any budget left over walks history backwards one
window at a time until two windows in a row come back empty. Windows
overlap by five days because institutions post late.

Ingestion is idempotent: a transaction is keyed by the bridge's id, and a
re-fetch updates the bank-owned columns (amount, description, pending,
posted) while leaving what the user or Claude decided (category, ignored)
alone.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field

from ledger import categorize, db, simplefin
from ledger.money import epoch_to_date, parse_cents
from ledger.normalize import payee_key

DAY = 86400
# The bridge's own guidance (returned in errlist when exceeded): keep a
# request under 45 days. Windows overlap by five days because banks post late.
WINDOW_DAYS = 45
OVERLAP_DAYS = 5
DAILY_CEILING = 20          # of the bridge's 24, leaving room for manual runs
MAX_BACKFILL_DAYS = 730
# Stop walking back after this many consecutive windows with nothing posted:
# about five months of silence across every account, which is history
# ending rather than a quiet stretch.
EMPTY_WINDOWS_TO_STOP = 4
PENDING_MATCH_DAYS = 5


class BudgetExhausted(Exception):
    pass


@dataclass
class SyncResult:
    kind: str
    start: int
    end: int
    requests: int = 1
    accounts: int = 0
    tx_seen: int = 0
    tx_posted: int = 0        # non-pending rows in the window; drives backfill termination
    tx_new: int = 0
    tx_updated: int = 0
    tx_pending: int = 0
    superseded: int = 0
    errlist: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "start": epoch_to_date(self.start), "end": epoch_to_date(self.end),
            "requests": self.requests, "accounts": self.accounts, "transactions_seen": self.tx_seen,
            "new": self.tx_new, "updated": self.tx_updated, "pending": self.tx_pending,
            "superseded": self.superseded, "errlist": self.errlist,
        }


# --- bookkeeping -------------------------------------------------------

def requests_last_24h(conn: sqlite3.Connection, now: int) -> int:
    row = conn.execute("SELECT COALESCE(SUM(requests), 0) AS n FROM sync_log WHERE started_at >= ?",
                       (now - DAY,)).fetchone()
    return int(row["n"])


def budget_available(conn: sqlite3.Connection, now: int, ceiling: int = DAILY_CEILING) -> int:
    return max(0, ceiling - requests_last_24h(conn, now))


# Retirement and equity plans first: "MY SAVINGS PLAN" is a 401(k), not a
# savings account, and "RESTRICTED STOCK UNITS" is a brokerage account.
INVESTMENT_WORDS = ("401", "403B", "403(B)", "457", "IRA", "ROTH", "BROKERAGE", "INVEST",
                    "HSA", "529", "SAVINGS PLAN", "RETIREMENT", "PENSION", "RSU",
                    "RESTRICTED STOCK", "STOCK PLAN", "ESPP", "THRIFT SAVINGS", "ANNUITY")
# Card product names. Issuers rarely put "credit" or "card" in the account
# name: Capital One reports "Venture", Chase reports "Chase Freedom Unlimited".
CREDIT_WORDS = ("CREDIT", "CARD", "VISA", "MASTERCARD", "AMEX", "AMERICAN EXPRESS", "DISCOVER",
                "VENTURE", "VENTURE X", "QUICKSILVER", "SAVOR", "SPARK", "FREEDOM", "SAPPHIRE",
                "SLATE", "CUSTOM CASH", "DOUBLE CASH", "BLUE CASH", "ACTIVE CASH", "AUTOGRAPH",
                "PLATINUM", "GOLD DELTA", "SKYMILES", "REWARDS")
LOAN_WORDS = ("MORTGAGE", "LOAN", "AUTO FIN", "HELOC")
SAVINGS_WORDS = ("SAVING", "MONEY MARKET", "VAULT", "CERTIFICATE OF DEPOSIT")
CHECKING_WORDS = ("CHECKING", "CHEQUING", "SPENDING", "EVERYDAY", "CASH MANAGEMENT")
# When the name says nothing, the institution still might: an unclassified
# account at a brokerage is a brokerage account.
INVESTMENT_ORGS = ("FIDELITY", "VANGUARD", "SCHWAB", "ROBINHOOD", "E*TRADE", "ETRADE",
                   "MERRILL", "AMERITRADE", "INTERACTIVE BROKERS", "BETTERMENT",
                   "WEALTHFRONT", "INVEST", "SECURITIES", "STASH", "M1 FINANCE")


def _mentions(text: str, words) -> bool:
    """Substring match, except that a word ending in a digit or a short
    all-caps token has to stand alone: "IRA" must not match "MIRAMAR"."""
    for w in words:
        if len(w) <= 4:
            if re.search(r"(?<![A-Z0-9])" + re.escape(w) + r"(?![A-Z0-9])", text):
                return True
        elif w in text:
            return True
    return False


def account_kind(name: str, balance_cents: int | None = None, org: str | None = None) -> str:
    n = (name or "").upper()
    if _mentions(n, INVESTMENT_WORDS):
        return "investment"
    if _mentions(n, CREDIT_WORDS):
        return "credit"
    if _mentions(n, LOAN_WORDS):
        return "loan"
    if _mentions(n, SAVINGS_WORDS):
        return "savings"
    if _mentions(n, CHECKING_WORDS):
        return "checking"
    if balance_cents is not None and balance_cents < 0:
        # Owing money with nothing in the name that says loan: a card.
        return "credit"
    if org and _mentions(org.upper(), INVESTMENT_ORGS):
        return "investment"
    return "unknown"


def reclassify_accounts(conn: sqlite3.Connection) -> list[dict]:
    """Re-run the kind heuristic over stored accounts. Kinds you set by hand
    are left alone. Returns the accounts whose kind changed."""
    changed = []
    for a in db.rows(conn, """
            SELECT a.id, a.name, a.kind, a.balance_cents, c.name AS institution
            FROM accounts a LEFT JOIN connections c ON c.conn_id = a.conn_id
            WHERE a.kind_source != 'user'"""):
        guess = account_kind(a["name"], a["balance_cents"], a["institution"])
        if guess != a["kind"]:
            conn.execute("UPDATE accounts SET kind = ? WHERE id = ?", (guess, a["id"]))
            changed.append({"id": a["id"], "name": a["name"], "was": a["kind"], "kind": guess})
    conn.commit()
    return changed


def _log(conn: sqlite3.Connection, started: int, finished: int, result: SyncResult | None,
         kind: str, start: int | None, end: int | None, ok: bool, error: str | None) -> None:
    r = result or SyncResult(kind, start or 0, end or 0)
    conn.execute(
        """INSERT INTO sync_log (started_at, finished_at, kind, start_date, end_date, requests,
                                 accounts_n, tx_new, tx_updated, tx_pending, errlist_json, ok, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (started, finished, kind, start, end, r.requests, r.accounts, r.tx_new, r.tx_updated,
         r.tx_pending, json.dumps(r.errlist), 1 if ok else 0, error),
    )
    conn.commit()


# --- ingestion ---------------------------------------------------------

def ingest(conn: sqlite3.Connection, data: dict, now: int, kind: str = "incremental",
           start: int | None = None, end: int | None = None) -> SyncResult:
    """Write one /accounts response into the database."""
    result = SyncResult(kind, start or 0, end or now, errlist=list(data.get("errlist") or []))
    today = epoch_to_date(now)

    for c in data.get("connections") or []:
        conn.execute(
            """INSERT INTO connections (conn_id, name, org_id, org_url, sfin_url, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(conn_id) DO UPDATE SET name = excluded.name, org_id = excluded.org_id,
                 org_url = excluded.org_url, sfin_url = excluded.sfin_url, last_seen = excluded.last_seen""",
            (c.get("conn_id"), c.get("name", ""), c.get("org_id"), c.get("org_url"), c.get("sfin_url"), now, now),
        )

    org_names: dict[str | None, str] = {
        c.get("conn_id"): c.get("name", "") for c in data.get("connections") or []
    }

    new_ids: list[str] = []
    for acct in data.get("accounts") or []:
        aid = acct["id"]
        # SimpleFIN v1 nests the org on the account; v2 lists connections.
        conn_id = acct.get("conn_id") or (acct.get("org") or {}).get("id")
        if acct.get("org") and conn_id:
            org = acct["org"]
            conn.execute(
                """INSERT INTO connections (conn_id, name, org_id, org_url, sfin_url, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(conn_id) DO UPDATE SET last_seen = excluded.last_seen""",
                (conn_id, org.get("name", ""), org.get("id"), org.get("url"), org.get("sfin-url"), now, now),
            )
            org_names.setdefault(conn_id, org.get("name", "") or org.get("domain", ""))
        balance = parse_cents(acct.get("balance", "0"))
        available = acct.get("available-balance")
        available = parse_cents(available) if available not in (None, "") else None
        balance_date = int(acct.get("balance-date") or now)
        existing = conn.execute("SELECT kind, kind_source FROM accounts WHERE id = ?", (aid,)).fetchone()
        kind_guess = account_kind(acct.get("name", ""), balance, org_names.get(conn_id))
        if existing is None:
            conn.execute(
                """INSERT INTO accounts (id, conn_id, name, currency, balance_cents, available_cents,
                                         balance_date, kind, kind_source, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'heuristic', ?, ?)""",
                (aid, conn_id, acct.get("name", aid), acct.get("currency", "USD"), balance, available,
                 balance_date, kind_guess, now, now),
            )
        else:
            conn.execute(
                """UPDATE accounts SET conn_id = COALESCE(?, conn_id), name = ?, currency = ?,
                     balance_cents = ?, available_cents = ?, balance_date = ?, last_seen = ?,
                     kind = CASE WHEN kind_source = 'user' THEN kind ELSE ? END
                   WHERE id = ?""",
                (conn_id, acct.get("name", aid), acct.get("currency", "USD"), balance, available,
                 balance_date, now, kind_guess, aid),
            )
        conn.execute(
            """INSERT INTO balance_snapshots (account_id, day, balance_cents, available_cents)
               VALUES (?, ?, ?, ?) ON CONFLICT(account_id, day) DO UPDATE SET
                 balance_cents = excluded.balance_cents, available_cents = excluded.available_cents""",
            (aid, today, balance, available),
        )
        result.accounts += 1

        seen: set[str] = set()
        for t in acct.get("transactions") or []:
            tid = t["id"]
            seen.add(tid)
            result.tx_seen += 1
            pending = 1 if t.get("pending") else 0
            posted = int(t.get("posted") or 0)
            if posted <= 0:
                # Pending rows carry posted=0; a 1970 date would wreck every
                # report, so fall back to when it was transacted, then now.
                posted = int(t.get("transacted_at") or now)
                pending = 1
            amount = parse_cents(t.get("amount", "0"))
            desc = t.get("description") or ""
            extra = json.dumps(t.get("extra")) if t.get("extra") else None
            transacted = int(t["transacted_at"]) if t.get("transacted_at") else None
            if pending:
                result.tx_pending += 1
            else:
                result.tx_posted += 1
            row = conn.execute("SELECT amount_cents, description, pending, posted FROM transactions WHERE id = ?",
                               (tid,)).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO transactions (id, account_id, posted, posted_date, transacted_at, amount_cents,
                         currency, description, payee_key, pending, extra_json, source, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'simplefin', ?, ?)""",
                    (tid, aid, posted, epoch_to_date(posted), transacted, amount, acct.get("currency", "USD"),
                     desc, payee_key(desc), pending, extra, now, now),
                )
                new_ids.append(tid)
                result.tx_new += 1
            else:
                changed = (row["amount_cents"] != amount or row["description"] != desc
                           or row["pending"] != pending or row["posted"] != posted)
                conn.execute(
                    """UPDATE transactions SET posted = ?, posted_date = ?, transacted_at = ?, amount_cents = ?,
                         description = ?, pending = ?, extra_json = ?, last_seen = ?, removed_at = NULL
                       WHERE id = ?""",
                    (posted, epoch_to_date(posted), transacted, amount, desc, pending, extra, now, tid),
                )
                if changed:
                    result.tx_updated += 1
        if start is not None and end is not None:
            result.superseded += reconcile_pending(conn, aid, start, end, seen, now)

    if new_ids:
        categorize.categorize(conn, ids=new_ids)
    conn.commit()
    return result


def _tokens(key: str) -> set[str]:
    return {t for t in key.upper().replace("-", " ").split() if t}


def reconcile_pending(conn: sqlite3.Connection, account_id: str, start: int, end: int,
                      seen: set[str], now: int) -> int:
    """A pending row the bridge no longer returns either posted under a new
    id or was dropped by the bank. Link it to its posted twin when there is
    one; retire it either way so it is not counted twice."""
    stale = db.rows(conn, """
        SELECT id, posted, amount_cents, payee_key, category_id, category_source FROM transactions
        WHERE account_id = ? AND pending = 1 AND removed_at IS NULL AND superseded_by IS NULL
          AND posted BETWEEN ? AND ?""", (account_id, start - PENDING_MATCH_DAYS * DAY, end))
    n = 0
    for p in stale:
        if p["id"] in seen:
            continue
        candidates = db.rows(conn, """
            SELECT id, payee_key, category_id FROM transactions
            WHERE account_id = ? AND pending = 0 AND removed_at IS NULL AND id != ?
              AND amount_cents = ? AND ABS(posted - ?) <= ?
              AND id NOT IN (SELECT superseded_by FROM transactions WHERE superseded_by IS NOT NULL)
            ORDER BY ABS(posted - ?)""",
            (account_id, p["id"], p["amount_cents"], p["posted"], PENDING_MATCH_DAYS * DAY, p["posted"]))
        match = None
        for c in candidates:
            if c["payee_key"] == p["payee_key"]:
                match = c
                break
            a, b = _tokens(c["payee_key"]), _tokens(p["payee_key"])
            if a and b and len(a & b) / len(a | b) >= 0.5:
                match = c
                break
        if match:
            conn.execute("UPDATE transactions SET superseded_by = ?, removed_at = ? WHERE id = ?",
                         (match["id"], now, p["id"]))
            if match["category_id"] is None and p["category_id"] is not None:
                conn.execute("UPDATE transactions SET category_id = ?, category_source = ? WHERE id = ?",
                             (p["category_id"], p["category_source"], match["id"]))
        else:
            conn.execute("UPDATE transactions SET removed_at = ? WHERE id = ?", (now, p["id"]))
        n += 1
    return n


# --- orchestration -----------------------------------------------------

def _fetch_window(conn, access_url, fetch, kind, start, end, now) -> SyncResult:
    # Stamp the log with the sync's own clock. The request budget is counted
    # off these timestamps, so a caller that supplies `now` has to see its own
    # 24h window; reading the wall clock here made the budget disagree with
    # every other date in the run. Duration still comes from a real timer.
    t0 = time.monotonic()

    def finished() -> int:
        return now + int(time.monotonic() - t0)

    try:
        data = fetch(access_url, start, end, pending=True)
    except simplefin.SimpleFinError as e:
        _log(conn, now, finished(), None, kind, start, end, False, str(e))
        raise
    result = ingest(conn, data, now, kind, start, end)
    _log(conn, now, finished(), result, kind, start, end, True, None)
    return result


def first_run(conn, access_url, now, fetch) -> SyncResult:
    end, start = now, now - WINDOW_DAYS * DAY
    result = _fetch_window(conn, access_url, fetch, "backfill", start, end, now)
    db.set_meta(conn, "backfill_cursor", start)
    db.set_meta(conn, "backfill_empty_streak", 0)
    db.set_meta(conn, "last_incremental_end", end)
    _note_empty(conn, result, start, now)
    conn.commit()
    return result


def incremental(conn, access_url, now, fetch) -> list[SyncResult]:
    last_end = int(db.get_meta(conn, "last_incremental_end"))
    start = last_end - OVERLAP_DAYS * DAY
    results = []
    while True:
        end = min(now, start + WINDOW_DAYS * DAY)
        results.append(_fetch_window(conn, access_url, fetch, "incremental", start, end, now))
        db.set_meta(conn, "last_incremental_end", end)
        conn.commit()
        if end >= now:
            break
        start = end - OVERLAP_DAYS * DAY
    return results


def backfill_step(conn, access_url, now, fetch) -> SyncResult:
    cursor = int(db.get_meta(conn, "backfill_cursor"))
    end = cursor + OVERLAP_DAYS * DAY
    start = end - WINDOW_DAYS * DAY
    result = _fetch_window(conn, access_url, fetch, "backfill", start, end, now)
    db.set_meta(conn, "backfill_cursor", start)
    _note_empty(conn, result, start, now)
    conn.commit()
    return result


def _note_empty(conn, result: SyncResult, start: int, now: int) -> None:
    streak = int(db.get_meta(conn, "backfill_empty_streak", 0) or 0)
    # Pending activity may ride along in every response whatever the window,
    # so only posted rows say whether history reaches this far back.
    streak = streak + 1 if result.tx_posted == 0 else 0
    db.set_meta(conn, "backfill_empty_streak", streak)
    if streak >= EMPTY_WINDOWS_TO_STOP or start <= now - MAX_BACKFILL_DAYS * DAY:
        db.set_meta(conn, "backfill_done", "1")


def backfill_done(conn) -> bool:
    return db.get_meta(conn, "backfill_done") == "1"


def run(conn: sqlite3.Connection, access_url: str, *, now: int | None = None,
        max_requests: int = 6, fetch=None, ceiling: int = DAILY_CEILING) -> list[SyncResult]:
    """One sync: catch up on recent activity, then spend any remaining
    request budget extending history backwards."""
    now = now or db.now_epoch()
    fetch = fetch or simplefin.fetch_accounts
    budget = min(max_requests, budget_available(conn, now, ceiling))
    if budget <= 0:
        raise BudgetExhausted(
            f"{requests_last_24h(conn, now)} of {ceiling} SimpleFIN requests used in the last 24h")

    results: list[SyncResult] = []
    if db.get_meta(conn, "last_incremental_end") is None:
        results.append(first_run(conn, access_url, now, fetch))
        budget -= 1
    else:
        got = incremental(conn, access_url, now, fetch)
        results.extend(got)
        budget -= sum(r.requests for r in got)

    while budget > 0 and not backfill_done(conn):
        results.append(backfill_step(conn, access_url, now, fetch))
        budget -= 1
    return results


def last_sync(conn) -> dict | None:
    return db.one(conn, "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1")
