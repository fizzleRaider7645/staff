from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdlc.config import SDLCConfig
from sdlc.phases import plan
from sdlc.state import SDLCState


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    (d / "spec.md").write_text("Build a todo app")
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
    provider.stream.return_value = iter(["# Plan\n", "Step 1\n", "Step 2\n"])
    return provider


class TestPlanRun:
    def test_writes_output_file(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.plan.get_provider", return_value=mock_provider):
            result = plan.run(sdlc_dir, config, state)

        assert result == sdlc_dir / "plan.md"
        assert result.exists()
        assert "# Plan" in result.read_text()

    def test_streams_to_file(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.plan.get_provider", return_value=mock_provider):
            plan.run(sdlc_dir, config, state)

        assert mock_provider.stream.call_count == 1
        args = mock_provider.stream.call_args
        assert isinstance(args[0][0], str)  # system
        assert isinstance(args[0][1], str)  # user
        assert isinstance(args[0][2], str)  # model

    def test_updates_state_on_success(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.plan.get_provider", return_value=mock_provider):
            plan.run(sdlc_dir, config, state)

        assert state.is_phase_complete("plan")
        assert state.data["phases"]["plan"]["output_file"] == "plan.md"

    def test_marks_failed_on_error(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.stream.side_effect = RuntimeError("API timeout")

        with patch("sdlc.phases.plan.get_provider", return_value=provider):
            with pytest.raises(RuntimeError, match="API timeout"):
                plan.run(sdlc_dir, config, state)

        assert state.phase_status("plan") == "failed"
        assert "API timeout" in state.data["phases"]["plan"]["error"]

    def test_uses_model_override(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.plan.get_provider", return_value=mock_provider):
            plan.run(sdlc_dir, config, state, model="custom-model")

        model_arg = mock_provider.stream.call_args[0][2]
        assert model_arg == "custom-model"

    def test_includes_spec_in_prompt(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.plan.get_provider", return_value=mock_provider):
            plan.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "Build a todo app" in user_prompt

    def test_includes_project_context(self, sdlc_dir, config, state, mock_provider):
        (sdlc_dir.parent / "README.md").write_text("# My Project")

        with patch("sdlc.phases.plan.get_provider", return_value=mock_provider):
            plan.run(sdlc_dir, config, state)

        user_prompt = mock_provider.stream.call_args[0][1]
        assert "My Project" in user_prompt

    def test_returns_output_path(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.plan.get_provider", return_value=mock_provider):
            result = plan.run(sdlc_dir, config, state)

        assert result == sdlc_dir / "plan.md"
