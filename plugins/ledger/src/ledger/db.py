"""SQLite access. One file, WAL mode, schema applied on every connect."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ledger import config

SCHEMA_VERSION = "1"
_HERE = Path(__file__).parent


def now_epoch() -> int:
    return int(time.time())


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    if path is None:
        config.ensure_home()
        path = config.db_path()
    path = str(path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript((_HERE / "schema.sql").read_text())
    if get_meta(conn, "schema_version") is None:
        set_meta(conn, "schema_version", SCHEMA_VERSION)
    seed_categories(conn)
    conn.commit()


def seed_categories(conn: sqlite3.Connection) -> None:
    """Insert the built-in categories that are missing. Never renames or
    deletes: the user may have re-pointed rules at them."""
    seeds = json.loads((_HERE / "data" / "categories.json").read_text())
    for c in seeds:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, kind, aliases_json) VALUES (?, ?, ?)",
            (c["name"], c.get("kind", "expense"), json.dumps(c.get("aliases", []))),
        )


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return default if row is None else row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, None if value is None else str(value)),
    )


def del_meta(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM meta WHERE key = ?", (key,))


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return None if r is None else dict(r)
