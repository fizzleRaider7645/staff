"""SimpleFIN protocol client (https://www.simplefin.org/protocol.html).

Two operations: claim a setup token for an access URL, and GET /accounts.
Standard library only. Every error message passes through redact() so the
credentials embedded in the access URL cannot leak through a traceback.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
_CREDS = re.compile(r"//([^/@\s:]+):([^/@\s]+)@")
# The bridge's front door refuses urllib's default agent with a 403 that
# looks exactly like a spent token. Every request identifies itself.
USER_AGENT = "ledger/0.1 (+https://github.com/fizzleRaider7645/staff)"


class SimpleFinError(Exception):
    pass


def redact(text) -> str:
    return _CREDS.sub("//***:***@", str(text))


# Module attribute so tests can monkeypatch it without touching urllib.
urlopen = urllib.request.urlopen


def decode_setup_token(token: str) -> str:
    token = "".join(token.split())
    try:
        url = base64.b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except Exception as e:  # noqa: BLE001 - any decode failure is the same to the user
        raise SimpleFinError("setup token is not valid base64") from e
    if not url.startswith("http"):
        raise SimpleFinError("setup token does not decode to a URL")
    return url


def claim(setup_token: str, opener=None) -> str:
    """Exchange a setup token for an access URL. One-shot: a second claim
    of the same token is refused by the bridge with 403."""
    url = decode_setup_token(setup_token)
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("Content-Length", "0")
    req.add_header("User-Agent", USER_AGENT)
    try:
        with (opener or urlopen)(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise SimpleFinError("claim refused (403): the setup token was already used, or is not valid") from None
        raise SimpleFinError(f"claim failed: HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise SimpleFinError(f"claim failed: {redact(e.reason)}") from None
    if not body.startswith("http"):
        raise SimpleFinError("claim response was not an access URL")
    return body


def split_credentials(access_url: str) -> tuple[str, str, str]:
    """('https://bridge.example/simplefin', user, password)."""
    p = urllib.parse.urlsplit(access_url)
    if not p.username or p.password is None:
        raise SimpleFinError("access URL carries no credentials")
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    base = urllib.parse.urlunsplit((p.scheme, host, p.path.rstrip("/"), "", ""))
    return base, urllib.parse.unquote(p.username), urllib.parse.unquote(p.password)


def host_of(access_url: str) -> str:
    return urllib.parse.urlsplit(access_url).hostname or "?"


def fetch_accounts(
    access_url: str,
    start: int | None = None,
    end: int | None = None,
    *,
    pending: bool = True,
    balances_only: bool = False,
    account_ids=None,
    opener=None,
) -> dict:
    """GET /accounts. start/end are epoch seconds; the bridge caps the range
    at 90 days. Returns the parsed AccountSet; the caller must look at
    errlist, which the bridge uses for institution-level problems."""
    base, user, password = split_credentials(access_url)
    params: list[tuple[str, str]] = [("version", "2")]
    if start is not None:
        params.append(("start-date", str(int(start))))
    if end is not None:
        params.append(("end-date", str(int(end))))
    if pending:
        params.append(("pending", "1"))
    if balances_only:
        params.append(("balances-only", "1"))
    for a in account_ids or []:
        params.append(("account", a))
    url = f"{base}/accounts?{urllib.parse.urlencode(params)}"

    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)

    last_error = None
    for attempt in range(2):
        try:
            with (opener or urlopen)(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
            break
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            if e.code == 403:
                raise SimpleFinError("access denied (403): the access URL was revoked or is wrong") from None
            last_error = SimpleFinError(f"HTTP {e.code} from SimpleFIN: {redact(detail)}")
            if e.code == 429 or e.code >= 500:
                if attempt == 0:
                    time.sleep(2)
                    continue
            raise last_error from None
        except urllib.error.URLError as e:
            raise SimpleFinError(f"could not reach SimpleFIN: {redact(e.reason)}") from None
    else:
        raise last_error  # pragma: no cover - loop always breaks or raises

    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SimpleFinError("SimpleFIN returned something that is not JSON") from None
    if not isinstance(data, dict) or "accounts" not in data:
        raise SimpleFinError("unexpected response shape from SimpleFIN")
    data.setdefault("errlist", [])
    return data
