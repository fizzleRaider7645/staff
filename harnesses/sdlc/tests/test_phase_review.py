from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdlc.config import SDLCConfig
from sdlc.phases import review
from sdlc.phases.review import _get_git_changes
from sdlc.state import SDLCState


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    (d / "spec.md").write_text("Build a web app")
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
    provider.stream.return_value = iter(["# Review\n", "Looks good\n"])
    return provider


class TestReviewRun:
    def test_writes_numbered_review(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.review.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.review._get_git_changes", return_value=None):
            result = review.run(sdlc_dir, config, state)

        assert result == sdlc_dir / "reviews" / "review-001.md"
        assert result.exists()

    def test_creates_reviews_dir(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.review.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.review._get_git_changes", return_value=None):
            review.run(sdlc_dir, config, state)

        assert (sdlc_dir / "reviews").is_dir()

    def test_increments_review_number(self, sdlc_dir, config, state, mock_provider):
        reviews_dir = sdlc_dir / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "review-001.md").write_text("first")
        (reviews_dir / "review-002.md").write_text("second")

        with patch("sdlc.phases.review.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.review._get_git_changes", return_value=None):
            result = review.run(sdlc_dir, config, state)

        assert result.name == "review-003.md"

    def test_updates_state_on_success(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.review.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.review._get_git_changes", return_value=None):
            review.run(sdlc_dir, config, state)

        assert state.is_phase_complete("review")
        assert "review-001.md" in state.data["phases"]["review"]["output_file"]

    def test_marks_failed_on_error(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.stream.side_effect = RuntimeError("API error")

        with patch("sdlc.phases.review.get_provider", return_value=provider), \
             patch("sdlc.phases.review._get_git_changes", return_value=None):
            with pytest.raises(RuntimeError):
                review.run(sdlc_dir, config, state)

        assert state.phase_status("review") == "failed"

    def test_includes_architecture(self, sdlc_dir, config, state, mock_provider):
        (sdlc_dir / "architecture.md").write_text("Use microservices")

        with patch("sdlc.phases.review.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.review._get_git_changes", return_value=None):
            review.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "microservices" in user_prompt

    def test_includes_verification(self, sdlc_dir, config, state, mock_provider):
        (sdlc_dir / "verification.md").write_text("All tests pass")

        with patch("sdlc.phases.review.get_provider", return_value=mock_provider), \
             patch("sdlc.phases.review._get_git_changes", return_value=None):
            review.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "All tests pass" in user_prompt


class TestGetGitChanges:
    def test_returns_diff_stat(self):
        with patch("sdlc.phases.review.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=" 2 files changed, 10 insertions(+)", returncode=0
            )
            result = _get_git_changes(Path("/tmp"))

        assert "2 files changed" in result

    def test_falls_back_to_log(self):
        with patch("sdlc.phases.review.subprocess.run") as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "diff" in cmd:
                    return MagicMock(stdout="", returncode=0)
                return MagicMock(stdout="abc1234 initial commit", returncode=0)

            mock_run.side_effect = side_effect
            result = _get_git_changes(Path("/tmp"))

        assert "initial commit" in result

    def test_returns_none_on_error(self):
        with patch("sdlc.phases.review.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = _get_git_changes(Path("/tmp"))

        assert result is None

    def test_returns_none_when_empty(self):
        with patch("sdlc.phases.review.subprocess.run") as mock_run:
            def side_effect(*args, **kwargs):
                return MagicMock(stdout="", returncode=0)

            mock_run.side_effect = side_effect
            result = _get_git_changes(Path("/tmp"))

        assert result is None
