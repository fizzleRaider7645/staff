from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sdlc.config import SDLCConfig
from sdlc.phases import architect
from sdlc.state import SDLCState


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    (d / "spec.md").write_text("Build a REST API")
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
    provider.stream.return_value = iter(["# Architecture\n", "Components\n"])
    return provider


class TestArchitectRun:
    def test_writes_output_file(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.architect.get_provider", return_value=mock_provider):
            result = architect.run(sdlc_dir, config, state)

        assert result == sdlc_dir / "architecture.md"
        assert result.exists()
        assert "# Architecture" in result.read_text()

    def test_updates_state_on_success(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.architect.get_provider", return_value=mock_provider):
            architect.run(sdlc_dir, config, state)

        assert state.is_phase_complete("architect")
        assert state.data["phases"]["architect"]["output_file"] == "architecture.md"

    def test_marks_failed_on_error(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.stream.side_effect = RuntimeError("Network error")

        with patch("sdlc.phases.architect.get_provider", return_value=provider):
            with pytest.raises(RuntimeError):
                architect.run(sdlc_dir, config, state)

        assert state.phase_status("architect") == "failed"

    def test_includes_plan_when_exists(self, sdlc_dir, config, state, mock_provider):
        (sdlc_dir / "plan.md").write_text("# Plan\nDo this and that")

        with patch("sdlc.phases.architect.get_provider", return_value=mock_provider):
            architect.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "Do this and that" in user_prompt

    def test_works_without_plan(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.architect.get_provider", return_value=mock_provider):
            result = architect.run(sdlc_dir, config, state)

        assert result.exists()

    def test_uses_model_override(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.architect.get_provider", return_value=mock_provider):
            architect.run(sdlc_dir, config, state, model="gpt-4o")

        model_arg = mock_provider.stream.call_args[0][2]
        assert model_arg == "gpt-4o"
