"""Shared fixtures. Every test gets its own LEDGER_HOME and database; the
SimpleFIN bridge is a fake that serves canned accounts and records calls."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ledger import config, credentials, db
from ledger.money import date_to_epoch

FIXTURES = Path(__file__).parent / "fixtures"
NOW = date_to_epoch("2026-09-15") + 12 * 3600  # 2026-09-15 noon local


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SIMPLEFIN_ACCESS_URL", raising=False)
    # The Keychain is not scoped to LEDGER_HOME, so on a macOS machine that
    # has really run `ledger setup` the suite would otherwise find live bank
    # credentials and take the "configured" branch of every command.
    monkeypatch.setattr(credentials, "_keychain_available", lambda: False)
    config.set_home(None)
    yield tmp_path / "home"
    config.set_home(None)


@pytest.fixture
def conn(home):
    c = db.connect(home / "ledger.db")
    yield c
    c.close()


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def tx(id, date, amount, description, pending=False, account=None):
    """A SimpleFIN transaction dict. amount is a string in dollars."""
    posted = 0 if pending else date_to_epoch(date)
    t = {"id": id, "posted": posted, "amount": amount, "description": description}
    if pending:
        t["pending"] = True
        t["transacted_at"] = date_to_epoch(date)
    return t


def account(id, name, balance, transactions=(), available=None, conn_id="conn-1", kind_hint=None):
    a = {"id": id, "name": name, "conn_id": conn_id, "currency": "USD", "balance": balance,
         "balance-date": NOW, "transactions": list(transactions)}
    if available is not None:
        a["available-balance"] = available
    return a


def response(accounts, errlist=None):
    return {"errlist": errlist or [], "connections": [
        {"conn_id": "conn-1", "name": "Demo Bank", "org_id": "demo", "sfin_url": "https://bridge.example/simplefin"}],
        "accounts": accounts}


class FakeBridge:
    """Serves transactions filtered by the requested window and remembers
    every call, so tests can assert on windows and request counts."""

    def __init__(self, accounts, errlist=None):
        self.accounts = accounts
        self.errlist = errlist or []
        self.calls: list[tuple[int, int]] = []

    def __call__(self, access_url, start=None, end=None, **kw):
        self.calls.append((start, end))
        out = []
        for a in self.accounts:
            a2 = {k: v for k, v in a.items() if k != "transactions"}
            a2["transactions"] = [
                t for t in a.get("transactions", [])
                if _in_window(t, start, end)
            ]
            out.append(a2)
        return response(out, list(self.errlist))


def _in_window(t, start, end):
    if t.get("pending") and not t.get("posted"):
        return True   # the bridge returns pending activity regardless of window
    when = t["posted"] or t.get("transacted_at") or 0
    if start is not None and when < start:
        return False
    if end is not None and when > end:
        return False
    return True


@pytest.fixture
def access_url(monkeypatch):
    url = "https://user1:secret-pass@bridge.example/simplefin"
    monkeypatch.setenv("SIMPLEFIN_ACCESS_URL", url)
    return url


# --- direct-insert helpers for detection and insight tests ------------------

def insert_account(conn, id, name, balance_cents, kind="checking", available_cents=None):
    conn.execute(
        """INSERT OR REPLACE INTO accounts (id, conn_id, name, currency, balance_cents, available_cents, balance_date,
             kind, kind_source, first_seen, last_seen) VALUES (?, 'conn-1', ?, 'USD', ?, ?, ?, ?, 'user', ?, ?)""",
        (id, name, balance_cents, available_cents, NOW, kind, NOW, NOW))
    conn.commit()


def insert_tx(conn, id, account, date, amount_cents, description, category=None, pending=False, source="user"):
    from ledger import categorize
    from ledger.normalize import payee_key
    cid = categorize.category_id(conn, category, create=True) if category else None
    posted = date_to_epoch(date)
    conn.execute(
        """INSERT OR REPLACE INTO transactions (id, account_id, posted, posted_date, amount_cents, description, payee_key,
             pending, category_id, category_source, source, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'simplefin', ?, ?)""",
        (id, account, posted, date, amount_cents, description, payee_key(description), 1 if pending else 0,
         cid, source if cid else None, NOW, NOW))
    conn.commit()


def monthly(conn, prefix, account, day, months, amount_cents, description, category=None, end="2026-09", amounts=None):
    """Insert one charge per month on `day`, ending in `end`."""
    from ledger.money import shift_month
    ids = []
    for i in range(months):
        m = shift_month(end, -(months - 1 - i))
        amt = amounts[i] if amounts else amount_cents
        tid = f"{prefix}-{i}"
        insert_tx(conn, tid, account, f"{m}-{day:02d}", amt, description, category)
        ids.append(tid)
    return ids


def snapshot(conn, account, day, balance_cents):
    conn.execute("INSERT OR REPLACE INTO balance_snapshots (account_id, day, balance_cents) VALUES (?, ?, ?)",
                 (account, day, balance_cents))
    conn.commit()
