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


# Columns added after a database already existed. schema.sql only runs
# CREATE TABLE IF NOT EXISTS, so a new column in it reaches new databases and
# no other; these are applied to every database on open.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "transactions": {
        # Why this row has the category it has: "keyword:MOBIL", "rule:17",
        # "transfer:own-account". Without it a wrong category is invisible.
        "category_reason": "TEXT",
        "category_rule_id": "INTEGER",
    },
}


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> list[str]:
    """ALTER TABLE ADD COLUMN for anything PRAGMA table_info does not report."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    added = []
    for name, decl in columns.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            added.append(name)
    return added


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript((_HERE / "schema.sql").read_text())
    for table, columns in ADDED_COLUMNS.items():
        ensure_columns(conn, table, columns)
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
