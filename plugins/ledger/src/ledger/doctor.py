"""Health checks. Each check is a dict {name, ok, level, detail}; level is
'ok', 'warn' or 'error'. Credentials are reported by source and host only."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from ledger import config, credentials, db, simplefin, sync
from ledger.money import epoch_to_date


def _check(name, ok, detail, level=None):
    return {"name": name, "ok": bool(ok), "level": level or ("ok" if ok else "error"), "detail": detail}


def checks(conn: sqlite3.Connection, now: int | None = None) -> list[dict]:
    now = now or db.now_epoch()
    out = []

    src = credentials.source()
    if src:
        url = credentials.get_access_url() or ""
        out.append(_check("credentials", True, f"{src}: {simplefin.host_of(url)}"))
    else:
        out.append(_check("credentials", False, "none — run: ledger setup"))

    path = config.db_path()
    if path.exists():
        n_tx = conn.execute("SELECT COUNT(*) FROM transactions WHERE removed_at IS NULL").fetchone()[0]
        n_acct = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        out.append(_check("database", True, f"{path} ({path.stat().st_size // 1024} KB, {n_acct} accounts, {n_tx} transactions)"))
    else:
        out.append(_check("database", True, f"{path} (not created yet)", "warn"))

    last = sync.last_sync(conn)
    if last is None:
        out.append(_check("last sync", False, "never — run: ledger sync", "warn"))
    else:
        errs = json.loads(last["errlist_json"] or "[]")
        when = epoch_to_date(last["started_at"])
        if not last["ok"]:
            out.append(_check("last sync", False, f"{when} failed: {last['error']}"))
        elif errs:
            out.append(_check("last sync", False, f"{when} ok, but the bridge reported: {'; '.join(map(str, errs))}", "warn"))
        else:
            out.append(_check("last sync", True, f"{when} {last['kind']} ({last['tx_new']} new)"))
        age_days = (now - last["started_at"]) // 86400
        if age_days >= 3:
            out.append(_check("sync freshness", False, f"{age_days} days since the last sync", "warn"))

    used = sync.requests_last_24h(conn, now)
    out.append(_check("request budget", used < sync.DAILY_CEILING, f"{used}/{sync.DAILY_CEILING} SimpleFIN requests in the last 24h",
                      "ok" if used < sync.DAILY_CEILING else "warn"))

    if db.get_meta(conn, "last_incremental_end") is not None:
        if sync.backfill_done(conn):
            out.append(_check("history", True, "backfill complete"))
        else:
            cursor = int(db.get_meta(conn, "backfill_cursor", now))
            out.append(_check("history", True, f"backfilled to {epoch_to_date(cursor)}; more arrives on each sync", "warn"))

    unc = conn.execute("SELECT COUNT(*) FROM transactions WHERE removed_at IS NULL AND category_id IS NULL").fetchone()[0]
    if unc:
        out.append(_check("categorization", True, f"{unc} uncategorized — ledger categorize, or ask Claude", "warn"))

    out.extend(schedule_checks(now))
    return out + registration_checks()


def schedule_checks(now: int) -> list[dict]:
    """The daily job and the dashboard it refreshes."""
    from ledger import schedule
    out = []
    try:
        st = schedule.status()
    except Exception as e:  # noqa: BLE001 - never let doctor itself fall over
        return [_check("schedule", False, f"could not read launchd state: {e}", "warn")]
    if not st["installed"]:
        out.append(_check("schedule", True, "no daily sync — ledger schedule install", "warn"))
    elif not st["loaded"]:
        out.append(_check("schedule", False, f"plist present but not loaded — ledger schedule install ({st['plist']})", "warn"))
    else:
        out.append(_check("schedule", True, f"daily sync at {st['hour']:02d}:{st['minute']:02d}" + (" with Cowork export" if st["export"] else "")))
    dash = config.dashboard_path()
    if dash.exists():
        age = (now - int(dash.stat().st_mtime)) // 86400
        out.append(_check("dashboard", True, f"{dash} ({age} day(s) old)", "ok" if age < 2 else "warn"))
    else:
        out.append(_check("dashboard", True, "not written yet — ledger dashboard", "warn"))
    return out


def registration_checks() -> list[dict]:
    """Where Claude can reach the MCP server. Absent registrations are
    informational: the CLI works without them."""
    out = []
    targets = [
        ("Claude Code", Path.home() / ".claude.json"),
        ("Claude Desktop", Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"),
    ]
    for label, path in targets:
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except ValueError:
            out.append(_check(f"mcp: {label}", False, f"{path} is not valid JSON", "warn"))
            continue
        present = "ledger" in (data.get("mcpServers") or {})
        out.append(_check(f"mcp: {label}", True, "registered" if present else "not registered (staff install ledger)",
                          "ok" if present else "warn"))
    return out


def problems(results: list[dict]) -> int:
    return sum(1 for r in results if r["level"] == "error")
