import json

from conftest import NOW, FakeBridge, account, tx
import pytest

from ledger import cli, credentials, simplefin, sync


@pytest.fixture
def bridge(monkeypatch, access_url):
    b = FakeBridge([account("chk", "Everyday Checking", "1250.00", transactions=[
        tx("t1", "2026-09-01", "-15.99", "NETFLIX.COM"),
        tx("t2", "2026-09-03", "-42.10", "SQ *BLUE BOTTLE 0421 SAN FRANCISCO CA"),
        tx("t3", "2026-09-05", "2500.00", "ACME CORP PAYROLL DIRECT DEP"),
        tx("t4", "2026-09-06", "-12.00", "MYSTERY VENDOR"),
    ])])
    monkeypatch.setattr(sync.simplefin, "fetch_accounts", b)
    monkeypatch.setattr(sync.db, "now_epoch", lambda: NOW)
    return b


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_sync_then_every_read_command_emits_json(capsys, bridge):
    code, out, _ = run(capsys, "--json", "sync", "--no-dashboard")
    assert code == 0
    data = json.loads(out)
    # first window, then the empty backfill windows that end the history walk
    assert data["new"] == 4 and data["requests"] == 1 + sync.EMPTY_WINDOWS_TO_STOP
    assert data["runs"][0]["kind"] == "backfill"
    assert data["backfill_done"] is True

    for argv in (["accounts"], ["transactions"], ["transactions", "--uncategorized"], ["categorize"],
                 ["rules", "list"], ["report", "--month", "2026-09", "--months", "2"], ["doctor"]):
        code, out, err = run(capsys, "--json", *argv)
        assert code in (0, 1), (argv, err)
        json.loads(out)

    code, out, _ = run(capsys, "--json", "transactions", "--uncategorized")
    assert [t["id"] for t in json.loads(out)["transactions"]] == ["t4"]

    code, out, _ = run(capsys, "--json", "rules", "add", "MYSTERY VENDOR", "--category", "Shopping")
    assert code == 0 and json.loads(out)["applied"] == 1
    code, out, _ = run(capsys, "--json", "transactions", "--uncategorized")
    assert json.loads(out)["count"] == 0

    code, out, _ = run(capsys, "--json", "categorize", "set", "t2", "--category", "Dining")
    assert json.loads(out)["updated"] == 1

    code, out, _ = run(capsys, "--json", "report", "--month", "2026-09")
    rep = json.loads(out)
    assert rep["income_cents"] == 250000 and rep["expense_cents"] == 1599 + 4210 + 1200


def test_human_output_is_readable(capsys, bridge):
    run(capsys, "sync", "--no-dashboard")
    code, out, _ = run(capsys, "accounts")
    assert code == 0 and "Everyday Checking" in out and "net worth $1,250.00" in out
    code, out, _ = run(capsys, "report", "--month", "2026-09")
    assert "Subscriptions" in out and "$15.99" in out


def test_sync_without_credentials_exits_2(capsys):
    code, out, err = run(capsys, "sync")
    assert code == 2 and "ledger setup" in err


def test_sync_reports_bridge_errors_on_stderr(capsys, bridge):
    bridge.errlist = ["Demo Bank: needs re-auth"]
    code, out, err = run(capsys, "sync", "--no-dashboard")
    assert code == 0 and "needs re-auth" in err


def test_budget_exhausted_exits_3(capsys, bridge):
    run(capsys, "sync", "--no-dashboard")            # first window + empty backfills
    for _ in range(sync.DAILY_CEILING - (1 + sync.EMPTY_WINDOWS_TO_STOP)):
        assert run(capsys, "sync", "--no-dashboard")[0] == 0
    code, _, err = run(capsys, "sync", "--no-dashboard")
    assert code == 3 and "requests" in err


def test_setup_never_echoes_the_token(capsys, monkeypatch):
    token = "c2VjcmV0LXRva2Vu"
    stored = {}
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": token)
    monkeypatch.setattr(simplefin, "claim", lambda t: "https://u:p@bridge.example/simplefin")
    monkeypatch.setattr(credentials, "set_access_url", lambda url: stored.setdefault("url", url))
    monkeypatch.setattr(credentials, "source", lambda: None)
    code, out, err = run(capsys, "setup")
    assert code == 0
    assert token not in out + err and "u:p@" not in out + err
    assert "bridge.example" in out and stored["url"].startswith("https://u:p@")


def test_error_messages_are_redacted(capsys, monkeypatch, access_url):
    def boom(*a, **k):
        raise simplefin.SimpleFinError("could not reach https://user1:secret-pass@bridge.example/simplefin")

    monkeypatch.setattr(sync.simplefin, "fetch_accounts", boom)
    code, out, err = run(capsys, "sync", "--no-dashboard")
    assert code == 1 and "secret-pass" not in err and "***" in err


def test_home_override(capsys, bridge, tmp_path):
    other = tmp_path / "elsewhere"
    code, _, _ = run(capsys, "--home", str(other), "sync", "--no-dashboard")
    assert code == 0 and (other / "ledger.db").exists()


def test_phase2_commands(capsys, bridge):
    from conftest import monthly, insert_account
    run(capsys, "sync", "--no-dashboard")
    from ledger import db
    conn = db.connect()
    monthly(conn, "sp", "chk", 2, 5, -1099, "SPOTIFY USA", "Subscriptions")
    conn.close()

    code, out, _ = run(capsys, "--json", "subscriptions")
    data = json.loads(out)
    assert code == 0 and [s["label"] for s in data["series"]] == ["Spotify"] and data["subscriptions_monthly_cents"] == 1099
    sid = data["series"][0]["id"]
    code, out, _ = run(capsys, "--json", "subscriptions", "label", sid, "Spotify Duo")
    assert code == 0
    code, out, _ = run(capsys, "subscriptions")
    assert "Spotify Duo" in out

    code, out, _ = run(capsys, "--json", "goals", "add", "Cushion", "--target", "5000", "--account", "chk", "--by", "2027-01-01")
    gid = json.loads(out)["id"]
    code, out, _ = run(capsys, "goals")
    assert code == 0 and "Cushion" in out and "$5,000.00" in out
    code, out, _ = run(capsys, "--json", "goals", "add", "bad", "--target", "1")
    assert code == 1

    code, out, _ = run(capsys, "--json", "insights")
    data = json.loads(out)
    assert code == 0 and any(i["kind"] == "subscriptions" for i in data["insights"])
    key = data["insights"][0]["key"]
    assert run(capsys, "--json", "insights", "dismiss", key)[0] == 0
    code, out, _ = run(capsys, "--json", "insights")
    assert key not in [i["key"] for i in json.loads(out)["insights"]]
    assert run(capsys, "--json", "goals", "remove", str(gid))[0] == 0


def test_dashboard_export_and_schedule_commands(capsys, bridge, tmp_path, monkeypatch):
    code, out, _ = run(capsys, "--json", "sync")
    data = json.loads(out)
    assert code == 0 and data["dashboard"].endswith("dashboard.html")
    from pathlib import Path
    assert Path(data["dashboard"]).exists()

    code, out, _ = run(capsys, "--json", "dashboard", "--out", str(tmp_path / "d.html"))
    assert code == 0 and (tmp_path / "d.html").exists()

    code, out, _ = run(capsys, "--json", "export", "--dir", str(tmp_path / "cowork"))
    info = json.loads(out)
    assert code == 0 and (tmp_path / "cowork" / "summary.json").exists() and (tmp_path / "cowork" / "dashboard.html").exists()
    summary = json.loads((tmp_path / "cowork" / "summary.json").read_text())
    assert summary["net_worth_cents"] == 125000 and "insights" in summary

    from ledger import schedule
    monkeypatch.setattr(schedule.Path, "home", classmethod(lambda cls: tmp_path))
    code, out, _ = run(capsys, "--json", "schedule", "status")
    assert code == 0 and json.loads(out)["installed"] is False
    code, out, _ = run(capsys, "schedule")
    assert "not scheduled" in out
