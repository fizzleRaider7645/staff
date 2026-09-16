import base64
import io
import json
import urllib.error
import urllib.request

import pytest

from ledger import simplefin


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch, body=b"", status=200):
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(body))
        return FakeResponse(body)

    monkeypatch.setattr(simplefin, "urlopen", opener)
    return calls


def test_claim_posts_to_decoded_url(monkeypatch):
    claim_url = "https://bridge.example/simplefin/claim/ABC"
    token = base64.b64encode(claim_url.encode()).decode()
    calls = _capture(monkeypatch, b"https://u:p@bridge.example/simplefin\n")
    assert simplefin.claim(token) == "https://u:p@bridge.example/simplefin"
    req = calls[0]
    assert req.full_url == claim_url
    assert req.get_method() == "POST"
    assert req.get_header("Content-length") == "0"
    assert req.get_header("User-agent", "").startswith("ledger/")


def test_claim_403_is_already_claimed(monkeypatch):
    token = base64.b64encode(b"https://bridge.example/claim/X").decode()
    _capture(monkeypatch, b"", status=403)
    with pytest.raises(simplefin.SimpleFinError, match="already used"):
        simplefin.claim(token)


def test_claim_rejects_garbage_token():
    with pytest.raises(simplefin.SimpleFinError):
        simplefin.claim("not base64!!")
    with pytest.raises(simplefin.SimpleFinError, match="URL"):
        simplefin.claim(base64.b64encode(b"hello").decode())


def test_fetch_accounts_builds_request(monkeypatch):
    body = json.dumps({"errlist": [], "accounts": []}).encode()
    calls = _capture(monkeypatch, body)
    data = simplefin.fetch_accounts("https://user%40x:pa%2Fss@bridge.example/simplefin/",
                                    start=100, end=200, account_ids=["a1", "a2"])
    assert data == {"errlist": [], "accounts": []}
    req = calls[0]
    assert req.full_url.startswith("https://bridge.example/simplefin/accounts?")
    q = req.full_url.split("?", 1)[1]
    assert "start-date=100" in q and "end-date=200" in q and "pending=1" in q and "version=2" in q
    assert q.count("account=") == 2
    expected = "Basic " + base64.b64encode(b"user@x:pa/ss").decode()
    assert req.get_header("Authorization") == expected
    assert req.get_header("User-agent", "").startswith("ledger/")
    assert "user" not in req.full_url


def test_fetch_accounts_retries_once_on_5xx(monkeypatch):
    attempts = []

    def opener(req, timeout=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(req.full_url, 502, "bad", {}, io.BytesIO(b""))
        return FakeResponse(json.dumps({"accounts": []}).encode())

    monkeypatch.setattr(simplefin, "urlopen", opener)
    monkeypatch.setattr(simplefin.time, "sleep", lambda s: None)
    assert simplefin.fetch_accounts("https://u:p@b.example/sf")["accounts"] == []
    assert len(attempts) == 2


def test_fetch_accounts_403_is_terminal(monkeypatch):
    _capture(monkeypatch, b"", status=403)
    with pytest.raises(simplefin.SimpleFinError, match="403"):
        simplefin.fetch_accounts("https://u:p@b.example/sf")


def test_errors_never_leak_credentials(monkeypatch):
    def opener(req, timeout=None):
        raise urllib.error.URLError("dns failed for https://u:p@b.example/sf")

    monkeypatch.setattr(simplefin, "urlopen", opener)
    with pytest.raises(simplefin.SimpleFinError) as e:
        simplefin.fetch_accounts("https://u:p@b.example/sf")
    assert "u:p@" not in str(e.value)
    assert simplefin.redact("x https://alice:s3cret@host/p y") == "x https://***:***@host/p y"


def test_split_and_host():
    base, user, pw = simplefin.split_credentials("https://a:b@host:8443/simplefin/")
    assert (base, user, pw) == ("https://host:8443/simplefin", "a", "b")
    assert simplefin.host_of("https://a:b@host/simplefin") == "host"
    with pytest.raises(simplefin.SimpleFinError):
        simplefin.split_credentials("https://host/simplefin")
