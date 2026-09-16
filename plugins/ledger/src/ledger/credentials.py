"""Where the SimpleFIN access URL lives.

The access URL embeds Basic Auth credentials, so it is treated like a
password: macOS Keychain by default, an environment variable for
non-interactive contexts and tests. It never goes into the database, the
logs, the dashboard, or an MCP result. Claude never runs `ledger setup`.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys

SERVICE = "ledger-simplefin"
ENV_VAR = "SIMPLEFIN_ACCESS_URL"


class CredentialError(Exception):
    pass


def _account() -> str:
    return os.environ.get("USER") or getpass.getuser()


def _keychain_available() -> bool:
    return sys.platform == "darwin"


def get_access_url(run=subprocess.run) -> str | None:
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return env
    if not _keychain_available():
        return None
    r = run(
        ["security", "find-generic-password", "-a", _account(), "-s", SERVICE, "-w"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def source(run=subprocess.run) -> str | None:
    """'env', 'keychain', or None when no credential is present."""
    if os.environ.get(ENV_VAR, "").strip():
        return "env"
    if get_access_url(run) is not None:
        return "keychain"
    return None


def set_access_url(url: str, run=subprocess.run) -> None:
    url = url.strip()
    if not url.startswith("http"):
        raise CredentialError("access URL must start with http")
    if any(ch in url for ch in '"\n\r'):
        raise CredentialError("access URL contains characters that cannot be stored")
    if not _keychain_available():
        raise CredentialError(
            f"no keychain on this platform — export {ENV_VAR} instead"
        )
    # `security -i` reads its command from stdin, so the URL never appears in
    # a process list the way it would as an argument to add-generic-password.
    script = f'add-generic-password -U -a "{_account()}" -s "{SERVICE}" -w "{url}"\n'
    r = run(["security", "-i"], input=script, capture_output=True, text=True)
    if r.returncode != 0:
        raise CredentialError("keychain write failed: " + _redact(r.stderr.strip()))


def delete_access_url(run=subprocess.run) -> bool:
    if not _keychain_available():
        return False
    r = run(
        ["security", "delete-generic-password", "-a", _account(), "-s", SERVICE],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def _redact(text: str) -> str:
    from ledger.simplefin import redact
    return redact(text)
