"""Spawn the real server over stdio, the way Claude Code and Claude Desktop
do, and talk to it with the SDK's client. Skipped when the mcp extra is not
installed for the interpreter running the tests."""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")
from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from conftest import NOW, insert_account, insert_tx, monthly  # noqa: E402
from ledger import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "bin" / "ledger-mcp"
SECRET = "sup3r-secret"


def _seed(home):
    conn = db.connect(home / "ledger.db")
    insert_account(conn, "chk", "Everyday Checking", 250000, available_cents=240000)
    insert_account(conn, "card", "Visa", -30000, kind="credit")
    monthly(conn, "nf", "chk", 1, 5, -1599, "NETFLIX.COM", "Subscriptions")
    monthly(conn, "hu", "chk", 3, 5, -999, "HULU", "Subscriptions")
    insert_tx(conn, "g1", "chk", "2026-09-06", -8000, "TRADER JOE'S #1", "Groceries")
    insert_tx(conn, "u1", "chk", "2026-09-07", -1200, "MYSTERY VENDOR")
    conn.close()


async def _session(home, fn):
    env = {**os.environ, "LEDGER_HOME": str(home), "SIMPLEFIN_ACCESS_URL": f"https://demo:{SECRET}@bridge.example/simplefin",
           "LEDGER_PYTHON": os.environ.get("LEDGER_PYTHON", "") or __import__("sys").executable}
    params = StdioServerParameters(command=str(LAUNCHER), args=[], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _payload(result):
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_tools_resources_and_no_credential_leak(home):
    _seed(home)

    async def run(session):
        tools = {t.name: t for t in (await session.list_tools()).tools}
        out = {"tools": tools}
        out["accounts"] = _payload(await session.call_tool("list_accounts", {}))
        out["summary"] = _payload(await session.call_tool("spending_summary", {"period": "2026-09"}))
        out["subs"] = _payload(await session.call_tool("list_subscriptions", {}))
        out["insights"] = _payload(await session.call_tool("get_insights", {}))
        out["status"] = _payload(await session.call_tool("sync_status", {}))
        out["cat"] = _payload(await session.call_tool("categorize_transactions", {"transaction_ids": ["u1"], "category": "Shopping"}))
        out["rule"] = _payload(await session.call_tool("add_rule", {"pattern": "MYSTERY VENDOR", "category": "Shopping"}))
        out["goal"] = _payload(await session.call_tool("set_goal", {"name": "Cushion", "target": 5000, "account_id": "chk", "by": "2027-01-01"}))
        out["res"] = json.loads((await session.read_resource("ledger://summary")).contents[0].text)
        out["everything"] = json.dumps({k: v for k, v in out.items() if k != "tools"})
        return out

    out = asyncio.run(_session(home, run))
    expected = {"list_accounts", "search_transactions", "spending_summary", "cash_flow", "list_subscriptions",
                "get_insights", "list_goals", "sync_status", "set_goal", "remove_goal", "categorize_transactions",
                "add_rule", "dismiss_insight", "mark_subscription", "run_sync", "write_dashboard"}
    assert expected <= set(out["tools"])
    assert all(out["tools"][n].description for n in expected), "every tool explains itself"

    accts = out["accounts"]
    assert accts["net_worth"] == 2200.0 and accts["cash"] == 2400.0
    assert {a["name"] for a in accts["accounts"]} == {"Everyday Checking", "Visa"}
    assert "balance_cents" not in accts["accounts"][0] and isinstance(accts["accounts"][0]["balance"], float)

    assert out["summary"]["expense"] == 15.99 + 9.99 + 80 + 12
    assert out["subs"]["active_subscriptions"] == 2 and out["subs"]["subscriptions_monthly"] == 25.98
    assert any(i["kind"] == "overlap" for i in out["insights"]["insights"])
    assert out["status"]["credentials"] == "env" and out["status"]["last_sync"] is None
    assert out["cat"]["updated"] == 1 and out["rule"]["rule_id"] >= 1
    assert out["goal"]["goal"]["name"] == "Cushion" and out["goal"]["goal"]["target"] == 5000.0
    assert out["res"]["net_worth"] == 2200.0 and out["res"]["subscriptions"]["count"] == 2

    assert SECRET not in out["everything"] and "demo:" not in out["everything"]
    assert not re.search(r"https?://[^/\s]+:[^/\s]+@", out["everything"])


def test_run_sync_reports_failure_without_credentials_in_it(home):
    _seed(home)

    async def run(session):
        return _payload(await session.call_tool("run_sync", {"max_requests": 1}))

    out = asyncio.run(_session(home, run))
    assert "error" in out and SECRET not in json.dumps(out)
