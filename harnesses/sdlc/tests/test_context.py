from __future__ import annotations

from pathlib import Path

from sdlc.config import SDLCConfig
from sdlc.context import (
    IGNORE_DIRS,
    KEY_FILENAMES,
    _file_tree,
    _find_key_files,
    gather_project_context,
)


class TestFileTree:
    def test_basic_structure(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()
        (tmp_path / "README.md").touch()

        tree = _file_tree(tmp_path)
        assert "src" in tree
        assert "main.py" in tree
        assert "README.md" in tree

    def test_dirs_sorted_before_files(self, tmp_path: Path):
        (tmp_path / "zebra.txt").touch()
        (tmp_path / "alpha_dir").mkdir()
        (tmp_path / "alpha_dir" / "file.txt").touch()

        tree = _file_tree(tmp_path)
        lines = tree.splitlines()
        dir_line = next(l for l in lines if "alpha_dir" in l)
        file_line = next(l for l in lines if "zebra.txt" in l)
        assert lines.index(dir_line) < lines.index(file_line)

    def test_ignores_dirs(self, tmp_path: Path):
        for d in ["node_modules", "__pycache__", ".git"]:
            (tmp_path / d).mkdir()
            (tmp_path / d / "file.txt").touch()
        (tmp_path / "src").mkdir()

        tree = _file_tree(tmp_path)
        assert "node_modules" not in tree
        assert "__pycache__" not in tree
        assert ".git" not in tree
        assert "src" in tree

    def test_ignores_dotfiles(self, tmp_path: Path):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".env").touch()
        (tmp_path / "visible").mkdir()

        tree = _file_tree(tmp_path)
        assert ".hidden" not in tree
        assert ".env" not in tree
        assert "visible" in tree

    def test_max_depth(self, tmp_path: Path):
        d = tmp_path
        for i in range(5):
            d = d / f"level{i}"
            d.mkdir()
            (d / "file.txt").touch()

        tree = _file_tree(tmp_path, max_depth=2)
        assert "level0" in tree
        assert "level1" in tree
        assert "level2" in tree
        assert "level3" not in tree

    def test_empty_dir(self, tmp_path: Path):
        tree = _file_tree(tmp_path)
        assert tree == ""

    def test_tree_connectors(self, tmp_path: Path):
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()

        tree = _file_tree(tmp_path)
        assert "├── " in tree
        assert "└── " in tree


class TestFindKeyFiles:
    def test_finds_existing_key_files(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "pyproject.toml").write_text("[project]")

        found = _find_key_files(tmp_path)
        names = [f.name for f in found]
        assert "README.md" in names
        assert "pyproject.toml" in names

    def test_preserves_key_filename_order(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "README.md").write_text("# Hi")

        found = _find_key_files(tmp_path)
        names = [f.name for f in found]
        assert names.index("README.md") < names.index("package.json")

    def test_returns_empty_for_no_matches(self, tmp_path: Path):
        (tmp_path / "random.txt").touch()
        assert _find_key_files(tmp_path) == []

    def test_does_not_search_subdirs(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "README.md").write_text("nested")

        assert _find_key_files(tmp_path) == []


class TestGatherProjectContext:
    def test_includes_file_tree(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()
        config = SDLCConfig()

        ctx = gather_project_context(tmp_path, config)
        assert "### File Tree" in ctx
        assert "main.py" in ctx

    def test_includes_key_file_content(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# My Project")
        config = SDLCConfig()

        ctx = gather_project_context(tmp_path, config)
        assert "### README.md" in ctx
        assert "# My Project" in ctx

    def test_truncates_large_files(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("x" * 15_000)
        config = SDLCConfig()

        ctx = gather_project_context(tmp_path, config)
        assert "... (truncated)" in ctx

    def test_respects_max_context_files(self, tmp_path: Path):
        for name in KEY_FILENAMES:
            (tmp_path / name).write_text(f"content of {name}")
        config = SDLCConfig(project_context={
            "include_file_tree": False,
            "max_context_files": 2,
        })

        ctx = gather_project_context(tmp_path, config)
        section_count = ctx.count("### ")
        assert section_count == 2

    def test_disables_file_tree(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        config = SDLCConfig(project_context={
            "include_file_tree": False,
            "max_context_files": 20,
        })

        ctx = gather_project_context(tmp_path, config)
        assert "### File Tree" not in ctx

    def test_empty_project(self, tmp_path: Path):
        config = SDLCConfig(project_context={
            "include_file_tree": True,
            "max_context_files": 20,
        })
        ctx = gather_project_context(tmp_path, config)
        assert ctx == ""

    def test_skips_binary_files(self, tmp_path: Path):
        (tmp_path / "README.md").write_bytes(b"\x80\x81\x82\x83")
        config = SDLCConfig(project_context={"include_file_tree": False, "max_context_files": 20})

        ctx = gather_project_context(tmp_path, config)
        assert "README.md" not in ctx
