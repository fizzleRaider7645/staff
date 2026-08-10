from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from jinja2 import TemplateNotFound

from sdlc.phases._prompts import PROMPTS_DIR, render_prompt


class TestRenderPrompt:
    def test_plan_splits_system_and_user(self):
        system, user = render_prompt("plan", spec="Build a CLI tool", project_context="")
        assert len(system) > 0
        assert "Build a CLI tool" in user

    def test_plan_includes_project_context(self):
        system, user = render_prompt(
            "plan", spec="Build a CLI", project_context="Has a README"
        )
        assert "Has a README" in user

    def test_plan_omits_context_section_when_empty(self):
        _, user = render_prompt("plan", spec="Build a CLI", project_context="")
        assert "Existing Project Context" not in user

    def test_all_templates_render(self):
        templates = [p.stem for p in PROMPTS_DIR.glob("*.md")]
        for name in templates:
            system, user = render_prompt(
                name,
                spec="test spec",
                project_context="test context",
                tasks="- task 1",
                architecture="arch doc",
                plan="plan doc",
                phase_outputs={},
            )
            assert isinstance(system, str)
            assert isinstance(user, str)

    def test_missing_template_raises(self):
        with pytest.raises(TemplateNotFound):
            render_prompt("nonexistent_phase", spec="test")

    def test_separator_splits_correctly(self):
        system, user = render_prompt("plan", spec="test", project_context="")
        assert "---" not in system
        assert "---" not in user

    def test_no_separator_returns_empty_system(self, tmp_path: Path):
        tmpl = tmp_path / "nosep.md"
        tmpl.write_text("Just user content with {{ spec }}")

        with patch("sdlc.phases._prompts.PROMPTS_DIR", tmp_path):
            from jinja2 import Environment, FileSystemLoader
            with patch("sdlc.phases._prompts._env", Environment(
                loader=FileSystemLoader(str(tmp_path)),
                keep_trailing_newline=True,
            )):
                system, user = render_prompt("nosep", spec="hello")
                assert system == ""
                assert "hello" in user
