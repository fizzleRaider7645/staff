from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdlc.config import SDLCConfig
from sdlc.phases import refine
from sdlc.phases.refine import _latest_review
from sdlc.state import SDLCState


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    (d / "spec.md").write_text("Build a dashboard")
    return d


@pytest.fixture
def state(sdlc_dir: Path) -> SDLCState:
    return SDLCState(sdlc_dir)


@pytest.fixture
def config() -> SDLCConfig:
    return SDLCConfig()


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.stream.return_value = iter(["# Refinement\n", "Changes needed\n"])
    return provider


class TestLatestReview:
    def test_returns_latest(self, sdlc_dir):
        reviews_dir = sdlc_dir / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "review-001.md").write_text("first review")
        (reviews_dir / "review-002.md").write_text("second review")

        result = _latest_review(sdlc_dir)
        assert result == "second review"

    def test_returns_none_when_no_reviews_dir(self, sdlc_dir):
        assert _latest_review(sdlc_dir) is None

    def test_returns_none_when_empty_reviews_dir(self, sdlc_dir):
        (sdlc_dir / "reviews").mkdir()
        assert _latest_review(sdlc_dir) is None


class TestRefineRun:
    def test_writes_numbered_refinement(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value="Fix the header"):
            result = refine.run(sdlc_dir, config, state)

        assert result == sdlc_dir / "refinements" / "refinement-001.md"
        assert result.exists()

    def test_creates_refinements_dir(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value=None):
            refine.run(sdlc_dir, config, state)

        assert (sdlc_dir / "refinements").is_dir()

    def test_increments_refinement_number(self, sdlc_dir, config, state, mock_provider):
        refinements_dir = sdlc_dir / "refinements"
        refinements_dir.mkdir()
        (refinements_dir / "refinement-001.md").write_text("first")

        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value=None):
            result = refine.run(sdlc_dir, config, state)

        assert result.name == "refinement-002.md"

    def test_updates_state_on_success(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value=None):
            refine.run(sdlc_dir, config, state)

        assert state.is_phase_complete("refine")

    def test_marks_failed_on_error(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.stream.side_effect = RuntimeError("timeout")

        with patch("sdlc.phases.refine.get_provider", return_value=provider), \
             patch("sdlc.phases.refine.click.edit", return_value=None):
            with pytest.raises(RuntimeError):
                refine.run(sdlc_dir, config, state)

        assert state.phase_status("refine") == "failed"

    def test_includes_feedback_in_prompt(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value="The button is broken"):
            refine.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "button is broken" in user_prompt

    def test_skips_empty_feedback(self, sdlc_dir, config, state, mock_provider):
        template = (
            "# Feedback\n\n"
            "<!-- Describe what you observed when running the product.\n"
            "     What works? What doesn't? What needs to change? -->\n"
        )
        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value=template):
            refine.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "Describe what you observed" not in user_prompt

    def test_skips_none_feedback(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value=None):
            result = refine.run(sdlc_dir, config, state)

        assert result.exists()

    def test_includes_latest_review(self, sdlc_dir, config, state, mock_provider):
        reviews_dir = sdlc_dir / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "review-001.md").write_text("Needs error handling")

        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value=None):
            refine.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "error handling" in user_prompt

    def test_includes_architecture(self, sdlc_dir, config, state, mock_provider):
        (sdlc_dir / "architecture.md").write_text("REST + PostgreSQL")

        with patch("sdlc.phases.refine.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.refine.click.edit", return_value=None):
            refine.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "PostgreSQL" in user_prompt
