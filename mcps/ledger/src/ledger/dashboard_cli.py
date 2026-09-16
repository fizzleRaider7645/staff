"""`ledger dashboard` and `ledger export`."""
from __future__ import annotations

import subprocess
import sys

from ledger import dashboard, export
from ledger.cli import EXIT_OK, emit, open_db


def cmd_dashboard(args) -> int:
    path = dashboard.write(open_db(), args.out)
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    emit(args, {"path": str(path)}, lambda: print(path))
    return EXIT_OK


def cmd_export(args) -> int:
    info = export.write(open_db(), args.dir)
    emit(args, info, lambda: print(f"wrote {info['summary']} and {info['dashboard']}"))
    return EXIT_OK


def add_commands(sub) -> None:
    s = sub.add_parser("dashboard", help="write the HTML dashboard (default ~/.ledger/dashboard.html)")
    s.add_argument("--out", metavar="PATH"); s.add_argument("--open", action="store_true", help="open it in the browser")
    s.set_defaults(fn=cmd_dashboard)
    s = sub.add_parser("export", help="write summary.json and the dashboard into Cowork's folder (~/Documents/Claude/ledger)")
    s.add_argument("--dir", metavar="DIR")
    s.set_defaults(fn=cmd_export)
