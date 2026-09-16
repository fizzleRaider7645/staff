"""Daily sync as a launchd LaunchAgent.

The agent runs `ledger sync` once a day at a fixed time with a minimal
environment; the log lands in ~/.ledger/logs. Installing and removing goes
through launchctl bootstrap/bootout so the change takes effect without a
logout. Also carries the `schedule` subcommands for the CLI.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from ledger import config

LABEL = "com.staff.ledger.sync"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _ledger_bin() -> str:
    return str(Path(__file__).resolve().parent.parent.parent / "bin" / "ledger")


def build_plist(hour: int, minute: int, *, export: bool = False, max_requests: int = 6, ledger_bin: str | None = None) -> dict:
    args = [ledger_bin or _ledger_bin(), "sync", "--max-requests", str(max_requests)]
    if export:
        args.append("--export")
    logs = config.logs_dir()
    return {
        "Label": LABEL,
        "ProgramArguments": args,
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": False,
        "StandardOutPath": str(logs / "sync.log"),
        "StandardErrorPath": str(logs / "sync.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
            "HOME": str(Path.home()),
            "LEDGER_HOME": str(config.home()),
            "LEDGER_PYTHON": sys.executable,
        },
    }


def install(hour: int = 7, minute: int = 30, *, export: bool = False, run=subprocess.run) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("scheduling uses launchd and works on macOS only; use cron elsewhere")
    config.ensure_home()
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_plist(hour, minute, export=export)
    # The launcher needs an interpreter that can import the project; the one
    # running this command is the best evidence of that.
    plist["ProgramArguments"][0] = _ledger_bin()
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    with open(path, "wb") as f:
        plistlib.dump(plist, f)
    r = run(["launchctl", "bootstrap", _domain(), str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {r.stderr.strip() or r.stdout.strip()}")
    return {"plist": str(path), "label": LABEL, "hour": hour, "minute": minute, "export": export,
            "log": plist["StandardOutPath"]}


def uninstall(run=subprocess.run) -> dict:
    path = plist_path()
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    existed = path.exists()
    if existed:
        path.unlink()
    return {"removed": existed, "plist": str(path)}


def status(run=subprocess.run) -> dict:
    path = plist_path()
    out = {"installed": path.exists(), "plist": str(path), "loaded": False, "hour": None, "minute": None,
           "log": str(config.logs_dir() / "sync.log"), "export": False}
    if path.exists():
        try:
            with open(path, "rb") as f:
                plist = plistlib.load(f)
            cal = plist.get("StartCalendarInterval", {})
            out["hour"], out["minute"] = cal.get("Hour"), cal.get("Minute")
            out["export"] = "--export" in plist.get("ProgramArguments", [])
        except Exception as e:  # noqa: BLE001
            out["error"] = f"unreadable plist: {e}"
    if sys.platform == "darwin":
        r = run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
        out["loaded"] = r.returncode == 0
    log = config.logs_dir() / "sync.log"
    if log.exists():
        lines = log.read_text(errors="replace").rstrip().splitlines()
        out["last_log_lines"] = lines[-5:]
    return out


# --- CLI -------------------------------------------------------------------

def cmd_schedule(args) -> int:
    from ledger.cli import EXIT_OK, CliError, emit
    sub = getattr(args, "schedule_cmd", None) or "status"
    if sub == "install":
        try:
            info = install(args.hour, args.minute, export=args.export)
        except RuntimeError as e:
            raise CliError(str(e))
        emit(args, info, lambda: print(f"daily sync scheduled at {info['hour']:02d}:{info['minute']:02d}; log: {info['log']}"))
        return EXIT_OK
    if sub == "uninstall":
        info = uninstall()
        emit(args, info, lambda: print("removed" if info["removed"] else "was not installed"))
        return EXIT_OK
    info = status()

    def human():
        if not info["installed"]:
            print("not scheduled. install with: ledger schedule install [--hour H] [--minute M]")
            return
        state = "loaded" if info["loaded"] else "installed but not loaded (log in again or re-run install)"
        print(f"daily sync at {info['hour']:02d}:{info['minute']:02d} — {state}" + (" — exports for Cowork" if info["export"] else ""))
        for line in info.get("last_log_lines", []):
            print(f"  {line}")
    emit(args, info, human)
    return EXIT_OK


def add_commands(sub) -> None:
    s = sub.add_parser("schedule", help="run sync daily via launchd")
    ss = s.add_subparsers(dest="schedule_cmd")
    p = ss.add_parser("install"); p.add_argument("--hour", type=int, default=7); p.add_argument("--minute", type=int, default=30)
    p.add_argument("--export", action="store_true", help="also write the Cowork export on each sync")
    ss.add_parser("uninstall"); ss.add_parser("status")
    s.set_defaults(fn=cmd_schedule)
