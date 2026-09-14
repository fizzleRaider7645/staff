"""Counting logic, exercised against a stand-in counter.

The API round trip is the one thing not tested here: it needs live
credentials. Everything around it — path selection, binary detection, the
empty-input shortcut, concurrency, per-file error isolation — is where the
behaviour actually lives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from token_count.counter import (
    FileCount,
    collect_paths,
    count_paths,
    count_text,
    readable_text,
)


def fake_counter(calls: list[tuple[str, str]] | None = None):
    """A counter that returns one token per whitespace-separated word."""

    def count(text: str, model: str) -> int:
        if calls is not None:
            calls.append((text, model))
        return len(text.split())

    return count


# --- counting a string ------------------------------------------------------


def test_counts_a_string():
    assert count_text("one two three", "m", fake_counter()) == 3


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\t "])
def test_empty_input_skips_the_api(text):
    calls: list = []
    assert count_text(text, "m", fake_counter(calls)) == 0
    assert calls == [], "counting whitespace should not cost a round trip"


# --- reading files ----------------------------------------------------------


def test_reads_utf8(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("héllo wörld", encoding="utf-8")
    assert readable_text(f) == "héllo wörld"


def test_rejects_binary(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"PK\x03\x04\x00\x00binary")
    assert readable_text(f) is None


def test_rejects_known_binary_suffix(tmp_path: Path):
    f = tmp_path / "a.pyc"
    f.write_text("not really bytecode")
    assert readable_text(f) is None


def test_rejects_invalid_utf8(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"\xff\xfe\xfd bad bytes")
    assert readable_text(f) is None


# --- selecting paths --------------------------------------------------------


def test_collects_a_single_file(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("x")
    assert collect_paths([f]) == [f]


def test_walks_a_directory(tmp_path: Path):
    (tmp_path / "a.md").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("y")
    names = {p.name for p in collect_paths([tmp_path])}
    assert names == {"a.md", "b.md"}


def test_skips_vendor_and_hidden_directories(tmp_path: Path):
    (tmp_path / "keep.md").write_text("x")
    for noise in ("node_modules", ".git", "__pycache__"):
        (tmp_path / noise).mkdir()
        (tmp_path / noise / "junk.md").write_text("y")
    names = {p.name for p in collect_paths([tmp_path])}
    assert names == {"keep.md"}, "dependency and VCS trees dwarf the source"


def test_include_all_keeps_them(tmp_path: Path):
    (tmp_path / "keep.md").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.md").write_text("y")
    names = {p.name for p in collect_paths([tmp_path], include_all=True)}
    assert names == {"keep.md", "junk.md"}


def test_deduplicates_overlapping_targets(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("x")
    assert len(collect_paths([tmp_path, f])) == 1


# --- counting many files ----------------------------------------------------


def test_counts_each_file_separately(tmp_path: Path):
    (tmp_path / "a.md").write_text("one two")
    (tmp_path / "b.md").write_text("one two three")
    results = count_paths(collect_paths([tmp_path]), "m", fake_counter())
    by_name = {r.path.name: r.tokens for r in results}
    assert by_name == {"a.md": 2, "b.md": 3}


def test_binary_files_are_marked_not_text(tmp_path: Path):
    (tmp_path / "a.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / "b.md").write_text("one two")
    results = count_paths(collect_paths([tmp_path]), "m", fake_counter())
    errors = {r.path.name: r.error for r in results if not r.ok}
    assert errors == {"a.bin": "not text"}


def test_one_failure_does_not_lose_the_others(tmp_path: Path):
    (tmp_path / "good.md").write_text("one two")
    (tmp_path / "bad.md").write_text("boom")

    def flaky(text: str, model: str) -> int:
        if "boom" in text:
            raise RuntimeError("rate limited")
        return len(text.split())

    results = count_paths(collect_paths([tmp_path]), "m", flaky)
    ok = {r.path.name: r.tokens for r in results if r.ok}
    bad = {r.path.name: r.error for r in results if not r.ok}
    assert ok == {"good.md": 2}
    assert "rate limited" in bad["bad.md"]


def test_no_paths_is_not_an_error():
    assert count_paths([], "m", fake_counter()) == []


def test_filecount_ok_reflects_error():
    assert FileCount(Path("a"), 1).ok
    assert not FileCount(Path("a"), 0, error="nope").ok


def test_relative_paths_with_dotdot_are_not_treated_as_hidden(tmp_path, monkeypatch):
    # ".." starts with a dot but is navigation, not a hidden directory.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.md").write_text("one two")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    assert [p.name for p in collect_paths(["../pkg"])] == ["a.md"]


def test_hidden_directories_are_still_skipped(tmp_path, monkeypatch):
    (tmp_path / ".secret").mkdir()
    (tmp_path / ".secret" / "a.md").write_text("x")
    (tmp_path / "b.md").write_text("y")
    monkeypatch.chdir(tmp_path)
    assert [p.name for p in collect_paths(["."])] == ["b.md"]
