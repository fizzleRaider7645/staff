"""Integration test against SimpleFIN's public demo bridge.

Runs only with LEDGER_LIVE=1. The developer guide mints a fresh single-use
DEMO setup token on every page load, so the test scrapes one, claims it,
and syncs into a temporary home. SIMPLEFIN_ACCESS_URL, when set, is used
as-is instead.
"""
import os
import re
import urllib.request

import pytest

from ledger import db, reports, simplefin, sync

DEVELOPERS_PAGE = "https://beta-bridge.simplefin.org/info/developers"

pytestmark = pytest.mark.skipif(os.environ.get("LEDGER_LIVE") != "1", reason="set LEDGER_LIVE=1 to hit the demo bridge")


def claim_fresh_demo() -> str:
    """Load the developers page and claim the demo token it minted. The token
    is bound to the session cookie the page sets, so the same opener does
    both; the page also refuses urllib's default user agent."""
    import http.cookiejar
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    req = urllib.request.Request(DEVELOPERS_PAGE, headers={"User-Agent": "Mozilla/5.0 (ledger test)"})
    with opener.open(req, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    m = re.search(r"(aHR0cHM6Ly9iZXRhLWJyaWRnZS5zaW1wbGVmaW4ub3JnL3NpbXBsZWZpbi9jbGFpbS9[A-Za-z0-9+/=]+)", page)
    if not m:
        pytest.skip("no demo token found on the developers page")
    return simplefin.claim(m.group(1), opener=opener.open)


def _access_url():
    url = os.environ.get("SIMPLEFIN_ACCESS_URL")
    if url:
        return url
    try:
        return claim_fresh_demo()
    except simplefin.SimpleFinError as e:
        pytest.skip(f"demo token could not be claimed ({e})")


def test_demo_bridge_end_to_end(home):
    url = _access_url()
    conn = db.connect(home / "ledger.db")
    results = sync.run(conn, url, max_requests=3)
    assert results and results[0].accounts > 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] > 0
    accts = reports.accounts(conn)
    assert accts and all(a["balance_date"] for a in accts)
    month = reports.monthly_report(conn, results[0].as_dict()["end"][:7])
    assert month["count"] >= 0
    for r in results:
        assert not any("@" in str(e) for e in r.errlist)
    # Nothing credential-shaped may reach the database. (The demo password
    # is a common word, so look for the user:password@ form, not the word.)
    dump = "\n".join(conn.iterdump())
    _, user, password = simplefin.split_credentials(url)
    assert f"{user}:{password}@" not in dump
    assert not re.search(r"https?://[^/\s]+:[^/\s]+@", dump)
