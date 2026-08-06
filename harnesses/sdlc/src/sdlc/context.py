from __future__ import annotations

from pathlib import Path

from sdlc.config import SDLCConfig

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".sdlc", "venv", ".venv",
               "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache"}

KEY_FILENAMES = [
    "README.md", "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
    "Makefile", "Dockerfile", "docker-compose.yml", ".env.example",
    "CLAUDE.md", "tsconfig.json", "setup.py", "setup.cfg",
]


def gather_project_context(project_dir: Path, config: SDLCConfig) -> str:
    parts: list[str] = []

    if config.project_context.get("include_file_tree", True):
        tree = _file_tree(project_dir, max_depth=3)
        if tree:
            parts.append(f"### File Tree\n```\n{tree}\n```")

    max_files = config.project_context.get("max_context_files", 20)
    for path in _find_key_files(project_dir)[:max_files]:
        try:
            content = path.read_text()
            if len(content) > 10_000:
                content = content[:10_000] + "\n... (truncated)"
            rel = path.relative_to(project_dir)
            parts.append(f"### {rel}\n```\n{content}\n```")
        except (UnicodeDecodeError, PermissionError):
            continue

    return "\n\n".join(parts) if parts else ""


def _file_tree(root: Path, max_depth: int = 3) -> str:
    lines: list[str] = []

    def walk(path: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        entries = [e for e in entries if e.name not in IGNORE_DIRS and not e.name.startswith(".")]
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                walk(entry, prefix + extension, depth + 1)

    walk(root, "", 0)
    return "\n".join(lines)


def _find_key_files(project_dir: Path) -> list[Path]:
    found: list[Path] = []
    for name in KEY_FILENAMES:
        p = project_dir / name
        if p.exists():
            found.append(p)
    return found
