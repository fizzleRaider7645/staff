"""Opt-in export for Claude Cowork, which runs in a VM and may not reach a
local MCP server: a summary JSON and the dashboard, written into the folder
Cowork can read. Off unless `ledger export` is run or `sync --export` is
scheduled; the files contain financial data."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from ledger import dashboard, db, insights, recurring, reports
from ledger.money import epoch_to_date

DEFAULT_DIR = Path.home() / "Documents" / "Claude" / "ledger"


def write(conn: sqlite3.Connection, directory: str | os.PathLike | None = None, now: int | None = None) -> dict:
    now = now or db.now_epoch()
    out = Path(directory) if directory else DEFAULT_DIR
    out.mkdir(parents=True, exist_ok=True)
    ctx = insights.context(conn, now)
    summary = reports.summary(conn, now)
    summary["subscriptions_list"] = [
        {k: r[k] for k in ("label", "cadence", "typical_amount_cents", "monthly_cents", "status", "is_subscription")}
        | {"next_expected": epoch_to_date(r["next_expected"]) if r["next_expected"] else None}
        for r in ctx.roster]
    summary["insights"] = [i.as_dict() for i in insights.run_all(conn, now, ctx=ctx)]
    summary["note"] = ("Amounts are integer cents. Written by `ledger export`; regenerate with `ledger sync --export` "
                       "or `ledger export`.")
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    dash = dashboard.write(conn, out / "dashboard.html", now)
    return {"dir": str(out), "summary": str(out / "summary.json"), "dashboard": str(dash)}
