"""Token counting against Claude models.

Counts come from the Anthropic API's count_tokens endpoint, which is the only
accurate source: token counts are model-specific, and OpenAI tokenizers like
tiktoken undercount Claude by roughly 15-20% on prose and considerably more on
code.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

DEFAULT_MODEL = "claude-opus-5"

# Directories that are never worth counting: dependency trees, build output,
# and version-control internals dwarf the source they sit next to.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "target",
    ".next", ".nuxt", ".tox", ".eggs", ".sdlc",
}

AUTH_FAILED = "authentication failed"
AUTH_ABORTED = "skipped after authentication failure"

SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dylib", ".dll", ".a", ".o", ".class"}


class TokenCounter(Protocol):
    """Counts the tokens in a string for a given model."""

    def __call__(self, text: str, model: str) -> int: ...


@dataclass
class FileCount:
    path: Path
    tokens: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class CredentialsMissing(RuntimeError):
    """No usable Anthropic credentials were found."""


def is_auth_error(exc: BaseException) -> bool:
    """Whether a failure means the credentials are bad, not the input.

    Bad credentials fail identically for every file, so this is the difference
    between one clear message and one doomed request per file.
    """
    if type(exc).__name__ in ("AuthenticationError", "PermissionDeniedError"):
        return True
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    return "authentication_error" in str(exc)


def api_counter() -> TokenCounter:
    """A TokenCounter backed by the Anthropic API.

    Credentials resolve the way the SDK resolves them — ANTHROPIC_API_KEY, then
    ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile — so a bare client is
    correct and an unset API key does not imply no credentials.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "the anthropic package is required: pip install anthropic"
        ) from exc

    client = anthropic.Anthropic()

    def count(text: str, model: str) -> int:
        response = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return response.input_tokens

    return count


def context_window(model: str) -> int | None:
    """The model's input limit, or None if it can't be determined.

    Read live from the Models API rather than hardcoded: context windows change
    between models and a stale table silently misreports the budget.
    """
    try:
        import anthropic

        client = anthropic.Anthropic()
        info = client.models.retrieve(model)
    except Exception:
        return None
    return getattr(info, "max_input_tokens", None)


def readable_text(path: Path) -> str | None:
    """File contents, or None if it isn't text worth counting."""
    if path.suffix in SKIP_SUFFIXES:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def collect_paths(targets: Iterable[str | Path], include_all: bool = False) -> list[Path]:
    """Expand files and directories into a sorted list of candidate files."""
    found: list[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file():
                    continue
                parts = set(child.parts)
                if not include_all and parts & SKIP_DIRS:
                    continue
                # "." and ".." are path navigation, not hidden directories —
                # treating them as hidden discards every relative path.
                if not include_all and any(
                    p.startswith(".") and p not in (".", "..")
                    for p in child.parts[:-1]
                ):
                    continue
                found.append(child)
    # Preserve first-seen order while dropping duplicates
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def count_text(text: str, model: str, counter: TokenCounter) -> int:
    """Count one string, skipping the round trip when there is nothing to count."""
    if not text.strip():
        return 0
    return counter(text, model)


def count_paths(
    paths: Iterable[Path],
    model: str,
    counter: TokenCounter,
    workers: int = 8,
    on_result: Callable[[FileCount], None] | None = None,
) -> list[FileCount]:
    """Count a set of files concurrently.

    One API call per file: counts are reported per file, and concatenating them
    would give a single number that hides which file is expensive.
    """
    paths = list(paths)
    if not paths:
        return []

    # Once credentials are rejected, every remaining file would fail the same
    # way; stop rather than firing a doomed request per file.
    auth_failed = threading.Event()

    def one(path: Path) -> FileCount:
        if auth_failed.is_set():
            return FileCount(path, 0, error=AUTH_ABORTED)
        text = readable_text(path)
        if text is None:
            return FileCount(path, 0, error="not text")
        try:
            return FileCount(path, count_text(text, model, counter))
        except Exception as exc:
            if is_auth_error(exc):
                auth_failed.set()
                return FileCount(path, 0, error=AUTH_FAILED)
            return FileCount(path, 0, error=_short_error(exc))

    results: list[FileCount] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(paths)))) as pool:
        for result in pool.map(one, paths):
            results.append(result)
            if on_result:
                on_result(result)
    return results


def _short_error(exc: Exception) -> str:
    name = type(exc).__name__
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return f"{name}: {message}" if message else name


def credentials_present() -> bool:
    """Whether any credential source the SDK understands is configured."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    config = Path.home() / ".config" / "anthropic"
    return config.is_dir() and any(config.iterdir())
