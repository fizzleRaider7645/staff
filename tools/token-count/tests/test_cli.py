"""CLI behaviour: argument handling, output shape, and exit codes."""

from __future__ import annotations

import json

import pytest

from token_count import cli


@pytest.fixture(autouse=True)
def stub_api(monkeypatch):
    """Never touch the network; credentials are assumed present."""
    monkeypatch.setattr(cli, "credentials_present", lambda: True)
    monkeypatch.setattr(cli, "api_counter", lambda *a, **k: (lambda text, model: len(text.split())))
    monkeypatch.setattr(cli, "context_window", lambda *a, **k: 1_000_000)


def test_counts_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("one two three"))
    assert cli.main([]) == 0
    assert "3" in capsys.readouterr().out


def test_counts_a_file(tmp_path, capsys):
    f = tmp_path / "a.md"
    f.write_text("one two three four")
    assert cli.main([str(f)]) == 0
    out = capsys.readouterr().out
    assert "4" in out and "a.md" in out


def test_json_output_is_machine_readable(tmp_path, capsys):
    (tmp_path / "a.md").write_text("one two")
    assert cli.main([str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_tokens"] == 2
    assert payload["model"] == cli.DEFAULT_MODEL
    assert payload["files"][0]["tokens"] == 2
    assert payload["context_window"] == 1_000_000


def test_model_is_passed_through(tmp_path, capsys, monkeypatch):
    seen = []
    monkeypatch.setattr(
        cli, "api_counter",
        lambda *a, **k: (lambda text, model: seen.append(model) or len(text.split())),
    )
    (tmp_path / "a.md").write_text("one")
    cli.main([str(tmp_path), "--model", "claude-haiku-4-5", "--no-budget"])
    assert seen == ["claude-haiku-4-5"]


def test_budget_line_reports_share_of_context(tmp_path, capsys):
    (tmp_path / "a.md").write_text("one two")
    cli.main([str(tmp_path)])
    assert "of claude-opus-5 input context" in capsys.readouterr().out


def test_no_budget_suppresses_it(tmp_path, capsys):
    (tmp_path / "a.md").write_text("one two")
    cli.main([str(tmp_path), "--no-budget"])
    assert "input context" not in capsys.readouterr().out


def test_top_limits_rows_and_summarises_the_rest(tmp_path, capsys):
    for i, n in enumerate(["a b c d", "a b c", "a b", "a"]):
        (tmp_path / f"f{i}.md").write_text(n)
    cli.main([str(tmp_path), "--top", "2", "--no-budget"])
    out = capsys.readouterr().out
    assert "2 more files" in out
    assert "10" in out, "the total still covers every file"


def test_missing_credentials_explains_how_to_fix(monkeypatch, capsys):
    monkeypatch.setattr(cli, "credentials_present", lambda: False)
    assert cli.main(["x"]) == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err and "ant auth login" in err


def test_nothing_to_count_is_an_error(tmp_path, capsys):
    assert cli.main([str(tmp_path)]) == 1
    assert "nothing to count" in capsys.readouterr().err


def test_binary_only_directory_says_so(tmp_path, capsys):
    (tmp_path / "a.bin").write_bytes(b"\x00\x01")
    (tmp_path / "b.bin").write_bytes(b"\x00\x02")
    # Files were found but none were countable — say that, rather than
    # implying the directory was empty.
    assert cli.main([str(tmp_path), "--no-budget"]) == 0
    out = capsys.readouterr().out
    assert "no text to count" in out
    assert "2 binary files skipped" in out


def test_bad_credentials_reported_once_not_per_file(tmp_path, capsys, monkeypatch):
    class AuthenticationError(Exception):
        status_code = 401

    def always_401(text, model):
        raise AuthenticationError("Error code: 401 - authentication_error")

    monkeypatch.setattr(cli, "api_counter", lambda *a, **k: always_401)
    for i in range(4):
        (tmp_path / f"f{i}.md").write_text("one two")

    assert cli.main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "rejected these credentials" in err
    assert err.count("rejected these credentials") == 1


def test_bad_credentials_on_stdin(monkeypatch, capsys):
    class AuthenticationError(Exception):
        status_code = 401

    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("hello"))
    monkeypatch.setattr(
        cli, "api_counter",
        lambda *a, **k: (lambda t, m: (_ for _ in ()).throw(AuthenticationError("401 authentication_error"))),
    )
    assert cli.main([]) == 2
    assert "rejected these credentials" in capsys.readouterr().err


def test_org_key_without_workspace_explains_the_fix(tmp_path, capsys, monkeypatch):
    class BadRequestError(Exception):
        status_code = 400

    def not_scoped(text, model):
        raise BadRequestError(
            "Error code: 400 - This API key is not scoped to a workspace, so "
            "this request must include the anthropic-workspace-id header"
        )

    monkeypatch.setattr(cli, "api_counter", lambda *a, **k: not_scoped)
    for i in range(4):
        (tmp_path / f"f{i}.md").write_text("one two")

    assert cli.main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_WORKSPACE_ID" in err
    assert "--workspace" in err
    assert err.count("not scoped to a workspace") == 1


def test_workspace_flag_reaches_the_client(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        cli, "api_counter",
        lambda ws=None: seen.append(ws) or (lambda t, m: len(t.split())),
    )
    (tmp_path / "a.md").write_text("one")
    cli.main([str(tmp_path), "--workspace", "wrkspc_123", "--no-budget"])
    assert seen == ["wrkspc_123"]


def test_workspace_falls_back_to_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_env")
    seen = []
    monkeypatch.setattr(
        cli, "api_counter",
        lambda ws=None: seen.append(ws) or (lambda t, m: len(t.split())),
    )
    (tmp_path / "a.md").write_text("one")
    cli.main([str(tmp_path), "--no-budget"])
    assert seen == ["wrkspc_env"]
