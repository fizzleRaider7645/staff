"""Where ledger keeps its state.

Everything lives under one directory (default ~/.ledger, override with the
LEDGER_HOME environment variable or --home). Nothing is written anywhere else
unless a command is explicitly told to (dashboard --out, export --dir).
"""
from __future__ import annotations

import os
from pathlib import Path

_override: Path | None = None


def set_home(path: str | os.PathLike | None) -> None:
    global _override
    _override = Path(path).expanduser() if path else None


def home() -> Path:
    if _override is not None:
        return _override
    return Path(os.environ.get("LEDGER_HOME", "~/.ledger")).expanduser()


def db_path() -> Path:
    return home() / "ledger.db"


def logs_dir() -> Path:
    return home() / "logs"


def dashboard_path() -> Path:
    return home() / "dashboard.html"


def ensure_home() -> Path:
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    try:
        h.chmod(0o700)
    except OSError:
        pass
    logs_dir().mkdir(parents=True, exist_ok=True)
    return h
