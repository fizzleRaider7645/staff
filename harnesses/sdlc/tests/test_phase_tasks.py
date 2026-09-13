from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdlc.config import SDLCConfig
from sdlc.phases import tasks
from sdlc.state import SDLCState


VALID_TASKS_JSON = json.dumps({
    "tasks": [
        {"id": 1, "title": "Setup project", "status": "pending"},
        {"id": 2, "title": "Add API routes", "status": "pending"},
    ]
})


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    (d / "spec.md").write_text("Build a CLI tool")
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
    provider.generate.return_value = VALID_TASKS_JSON
    return provider


class TestTasksRun:
    def test_writes_tasks_json(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.tasks.get_provider", return_value=mock_provider):
            result = tasks.run(sdlc_dir, config, state)

        assert result == sdlc_dir / "tasks.json"
        data = json.loads(result.read_text())
        assert len(data["tasks"]) == 2

    def test_updates_state_on_success(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.tasks.get_provider", return_value=mock_provider):
            tasks.run(sdlc_dir, config, state)

        assert state.is_phase_complete("tasks")

    def test_marks_failed_on_api_error(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.generate.side_effect = RuntimeError("Rate limited")

        with patch("sdlc.phases.tasks.get_provider", return_value=provider):
            with pytest.raises(RuntimeError):
                tasks.run(sdlc_dir, config, state)

        assert state.phase_status("tasks") == "failed"

    def test_marks_failed_on_invalid_json(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.generate.return_value = "This is not JSON at all"

        with patch("sdlc.phases.tasks.get_provider", return_value=provider):
            with pytest.raises(json.JSONDecodeError):
                tasks.run(sdlc_dir, config, state)

        assert state.phase_status("tasks") == "failed"
        assert (sdlc_dir / "tasks_raw.txt").exists()

    def test_saves_raw_output_on_json_error(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.generate.return_value = "not json {broken"

        with patch("sdlc.phases.tasks.get_provider", return_value=provider):
            with pytest.raises(json.JSONDecodeError):
                tasks.run(sdlc_dir, config, state)

        raw = (sdlc_dir / "tasks_raw.txt").read_text()
        assert raw == "not json {broken"

    def test_includes_plan_when_exists(self, sdlc_dir, config, state, mock_provider):
        (sdlc_dir / "plan.md").write_text("# Plan\nPhase 1")

        with patch("sdlc.phases.tasks.get_provider", return_value=mock_provider):
            tasks.run(sdlc_dir, config, state)

        user_prompt = mock_provider.generate.call_args[0][1]
        assert "Phase 1" in user_prompt

    def test_includes_architecture_when_exists(self, sdlc_dir, config, state, mock_provider):
        (sdlc_dir / "architecture.md").write_text("# Arch\nMicroservices")

        with patch("sdlc.phases.tasks.get_provider", return_value=mock_provider):
            tasks.run(sdlc_dir, config, state)

        user_prompt = mock_provider.generate.call_args[0][1]
        assert "Microservices" in user_prompt

    def test_works_without_plan_or_architecture(self, sdlc_dir, config, state, mock_provider):
        with patch("sdlc.phases.tasks.get_provider", return_value=mock_provider):
            result = tasks.run(sdlc_dir, config, state)

        assert result.exists()


class TestFenceStripping:
    """Test the markdown fence stripping logic in tasks.run()."""

    def test_strips_json_fence(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.generate.return_value = '```json\n{"tasks": []}\n```'

        with patch("sdlc.phases.tasks.get_provider", return_value=provider):
            result = tasks.run(sdlc_dir, config, state)

        data = json.loads(result.read_text())
        assert data == {"tasks": []}

    def test_strips_plain_fence(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.generate.return_value = '```\n{"tasks": [{"id": 1}]}\n```'

        with patch("sdlc.phases.tasks.get_provider", return_value=provider):
            result = tasks.run(sdlc_dir, config, state)

        data = json.loads(result.read_text())
        assert len(data["tasks"]) == 1

    def test_handles_no_fence(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.generate.return_value = '{"tasks": []}'

        with patch("sdlc.phases.tasks.get_provider", return_value=provider):
            result = tasks.run(sdlc_dir, config, state)

        data = json.loads(result.read_text())
        assert data == {"tasks": []}

    def test_strips_fence_with_surrounding_whitespace(self, sdlc_dir, config, state):
        provider = MagicMock()
        provider.generate.return_value = '  \n```json\n{"tasks": []}\n```\n  '

        with patch("sdlc.phases.tasks.get_provider", return_value=provider):
            result = tasks.run(sdlc_dir, config, state)

        data = json.loads(result.read_text())
        assert data == {"tasks": []}
