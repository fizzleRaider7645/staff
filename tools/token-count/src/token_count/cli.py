from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from token_count.counter import (
    AUTH_ABORTED,
    AUTH_FAILED,
    WORKSPACE_REQUIRED,
    DEFAULT_MODEL,
    FileCount,
    api_counter,
    collect_paths,
    context_window,
    count_text,
    count_paths,
    credentials_present,
    is_auth_error,
    needs_workspace,
)

CREDENTIALS_HELP = """no Anthropic credentials found.

Set one of:
  export ANTHROPIC_API_KEY=...     an API key
  ant auth login                   an OAuth profile the SDK reads automatically

Counts come from the API because they are model-specific; there is no accurate
offline tokenizer for Claude."""

AUTH_HELP = """the Anthropic API rejected these credentials.

Check the key in ANTHROPIC_API_KEY, or re-authenticate with `ant auth login`."""

WORKSPACE_HELP = """this API key is not scoped to a workspace, so requests must name one.

Set ANTHROPIC_WORKSPACE_ID, pass --workspace <id>, or use a workspace-scoped key.
Workspace IDs are listed in the Console under Settings > Workspaces."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token-count",
        description="Count Claude tokens in files, directories, or stdin.",
        epilog=(
            "Counts come from the Anthropic count_tokens endpoint and are "
            "specific to the model given by --model."
        ),
    )
    parser.add_argument(
        "paths", nargs="*", metavar="PATH",
        help="files or directories to count; '-' reads stdin (default: stdin)",
    )
    parser.add_argument(
        "--model", "-m", default=DEFAULT_MODEL,
        help=f"model to count against (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--json", dest="as_json", action="store_true",
        help="emit JSON instead of a table",
    )
    parser.add_argument(
        "--top", type=int, metavar="N",
        help="show only the N largest files",
    )
    parser.add_argument(
        "--all", dest="include_all", action="store_true",
        help="include hidden and vendor directories that are skipped by default",
    )
    parser.add_argument(
        "--workspace", metavar="ID",
        default=os.environ.get("ANTHROPIC_WORKSPACE_ID"),
        help="workspace id, for an org-level key (env: ANTHROPIC_WORKSPACE_ID)",
    )
    parser.add_argument(
        "--workers", type=int, default=8, metavar="N",
        help="parallel requests when counting many files (default: 8)",
    )
    parser.add_argument(
        "--no-budget", dest="budget", action="store_false",
        help="skip the context-window comparison",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not credentials_present():
        print(f"token-count: {CREDENTIALS_HELP}", file=sys.stderr)
        return 2

    try:
        counter = api_counter(args.workspace)
    except RuntimeError as exc:
        print(f"token-count: {exc}", file=sys.stderr)
        return 2

    reading_stdin = not args.paths or args.paths == ["-"]

    if reading_stdin:
        text = sys.stdin.read()
        try:
            total = count_text(text, args.model, counter)
        except Exception as exc:
            if needs_workspace(exc):
                print(f"token-count: {WORKSPACE_HELP}", file=sys.stderr)
                return 2
            if is_auth_error(exc):
                print(f"token-count: {AUTH_HELP}", file=sys.stderr)
                return 2
            print(f"token-count: {exc}", file=sys.stderr)
            return 1
        results = [FileCount(Path("<stdin>"), total)]
    else:
        paths = collect_paths(args.paths, include_all=args.include_all)
        if not paths:
            print("token-count: nothing to count", file=sys.stderr)
            return 1
        results = count_paths(paths, args.model, counter, workers=args.workers)

    counted = [r for r in results if r.ok]
    skipped = [r for r in results if r.error == "not text"]
    failed = [r for r in results if not r.ok and r.error != "not text"]
    total = sum(r.tokens for r in counted)

    if any(r.error == WORKSPACE_REQUIRED for r in failed):
        print(f"token-count: {WORKSPACE_HELP}", file=sys.stderr)
        return 2

    # Bad credentials are not a per-file problem — say so once.
    if any(r.error in (AUTH_FAILED, AUTH_ABORTED) for r in failed):
        print(f"token-count: {AUTH_HELP}", file=sys.stderr)
        return 2

    if not counted and not failed and skipped:
        noun = "file" if len(skipped) == 1 else "files"
        print(f"no text to count ({len(skipped)} binary {noun} skipped)")
        return 0

    # A failure that reached the API is worth surfacing even in JSON mode;
    # a binary file that was skipped is not.
    if args.as_json:
        print(json.dumps(_as_json(args.model, counted, failed, total, args.budget, args.workspace), indent=2))
    else:
        _render(args.model, counted, failed, total, args.top, args.budget, args.workspace)

    if failed and not counted:
        return 1
    return 0


def _as_json(model, counted, failed, total, want_budget, workspace=None) -> dict:
    payload: dict = {
        "model": model,
        "total_tokens": total,
        "files": [{"path": str(r.path), "tokens": r.tokens} for r in counted],
    }
    if failed:
        payload["errors"] = [{"path": str(r.path), "error": r.error} for r in failed]
    if want_budget:
        limit = context_window(model, workspace)
        if limit:
            payload["context_window"] = limit
            payload["context_used"] = round(total / limit, 6)
    return payload


def _render(model, counted, failed, total, top, want_budget, workspace=None) -> None:
    if not counted and not failed:
        print("nothing to count")
        return

    rows = sorted(counted, key=lambda r: r.tokens, reverse=True)
    shown = rows[:top] if top else rows

    width = max((len(f"{r.tokens:,}") for r in shown), default=6)
    width = max(width, 6)

    for r in shown:
        share = f"{r.tokens / total * 100:4.1f}%" if total else "   - "
        print(f"  {r.tokens:>{width},}  {share}  {r.path}")

    if top and len(rows) > top:
        rest = sum(r.tokens for r in rows[top:])
        print(f"  {rest:>{width},}  {rest / total * 100:4.1f}%  "
              f"({len(rows) - top} more files)")

    print(f"  {'-' * (width + 8)}")
    noun = "file" if len(counted) == 1 else "files"
    print(f"  {total:>{width},}         {len(counted)} {noun}")

    if want_budget:
        limit = context_window(model, workspace)
        if limit:
            print(f"\n  {total / limit * 100:.1f}% of {model} input context "
                  f"({limit:,} tokens)")

    for r in failed:
        print(f"  ! {r.path}: {r.error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
