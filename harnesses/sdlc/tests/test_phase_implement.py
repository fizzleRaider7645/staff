from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdlc.config import SDLCConfig
from sdlc.phases import implement
from sdlc.phases.implement import _build_prompt, _mark_task_done
from sdlc.state import SDLCState


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    (d / "spec.md").write_text("Build a widget")
    return d


@pytest.fixture
def state(sdlc_dir: Path) -> SDLCState:
    return SDLCState(sdlc_dir)


@pytest.fixture
def config() -> SDLCConfig:
    return SDLCConfig()


@pytest.fixture
def tasks_file(sdlc_dir: Path) -> Path:
    data = {
        "tasks": [
            {"id": 1, "title": "Setup", "status": "pending"},
            {"id": 2, "title": "Implement core", "status": "pending"},
            {"id": 3, "title": "Add tests", "status": "done"},
        ]
    }
    p = sdlc_dir / "tasks.json"
    p.write_text(json.dumps(data, indent=2))
    return p


class TestBuildPrompt:
    def test_falls_back_to_spec(self, sdlc_dir):
        prompt = _build_prompt(sdlc_dir, task_num=None)
        assert "Build a widget" in prompt

    def test_single_task_by_number(self, sdlc_dir, tasks_file):
        prompt = _build_prompt(sdlc_dir, task_num=2)
        assert "Implement core" in prompt

    def test_invalid_task_number_too_high(self, sdlc_dir, tasks_file):
        with pytest.raises(ValueError, match="Invalid task number 10"):
            _build_prompt(sdlc_dir, task_num=10)

    def test_invalid_task_number_zero(self, sdlc_dir, tasks_file):
        with pytest.raises(ValueError, match="Invalid task number 0"):
            _build_prompt(sdlc_dir, task_num=0)

    def test_invalid_task_number_negative(self, sdlc_dir, tasks_file):
        with pytest.raises(ValueError, match="Invalid task number -1"):
            _build_prompt(sdlc_dir, task_num=-1)

    def test_all_pending_tasks_when_no_number(self, sdlc_dir, tasks_file):
        prompt = _build_prompt(sdlc_dir, task_num=None)
        assert "Setup" in prompt
        assert "Implement core" in prompt

    def test_filters_done_tasks(self, sdlc_dir, tasks_file):
        prompt = _build_prompt(sdlc_dir, task_num=None)
        assert "Add tests" not in prompt

    def test_includes_architecture(self, sdlc_dir, tasks_file):
        (sdlc_dir / "architecture.md").write_text("# Arch\nUse SQLite")
        prompt = _build_prompt(sdlc_dir, task_num=1)
        assert "SQLite" in prompt

    def test_falls_back_to_spec_when_all_done(self, sdlc_dir):
        data = {"tasks": [{"id": 1, "title": "Done task", "status": "done"}]}
        (sdlc_dir / "tasks.json").write_text(json.dumps(data))
        prompt = _build_prompt(sdlc_dir, task_num=None)
        assert "Build a widget" in prompt


class TestMarkTaskDone:
    def test_marks_task_done(self, sdlc_dir, tasks_file):
        _mark_task_done(sdlc_dir, 1)

        data = json.loads(tasks_file.read_text())
        assert data["tasks"][0]["status"] == "done"

    def test_preserves_other_tasks(self, sdlc_dir, tasks_file):
        _mark_task_done(sdlc_dir, 1)

        data = json.loads(tasks_file.read_text())
        assert data["tasks"][1]["status"] == "pending"

    def test_invalid_task_number(self, sdlc_dir, tasks_file):
        with pytest.raises(ValueError, match="Invalid task number"):
            _mark_task_done(sdlc_dir, 99)

    def test_no_tasks_file(self, sdlc_dir):
        _mark_task_done(sdlc_dir, 1)  # should not raise


class TestImplementRun:
    def test_calls_claude_cli(self, sdlc_dir, config, state):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            implement.run(sdlc_dir, config, state)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--model" in cmd

    def test_updates_state_on_success(self, sdlc_dir, config, state):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            implement.run(sdlc_dir, config, state)

        assert state.is_phase_complete("implement")

    def test_marks_failed_on_cli_not_found(self, sdlc_dir, config, state):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with pytest.raises(FileNotFoundError):
                implement.run(sdlc_dir, config, state)

        assert state.phase_status("implement") == "failed"
        assert "not found" in state.data["phases"]["implement"]["error"]

    def test_marks_failed_on_nonzero_exit(self, sdlc_dir, config, state):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "claude")
            with pytest.raises(subprocess.CalledProcessError):
                implement.run(sdlc_dir, config, state)

        assert state.phase_status("implement") == "failed"

    def test_marks_task_done_on_success(self, sdlc_dir, config, state, tasks_file):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            implement.run(sdlc_dir, config, state, task_num=1)

        data = json.loads(tasks_file.read_text())
        assert data["tasks"][0]["status"] == "done"

    def test_does_not_mark_task_when_no_number(self, sdlc_dir, config, state, tasks_file):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            implement.run(sdlc_dir, config, state)

        data = json.loads(tasks_file.read_text())
        assert data["tasks"][0]["status"] == "pending"

    def test_uses_model_override(self, sdlc_dir, config, state):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            implement.run(sdlc_dir, config, state, model="custom-model")

        cmd = mock_run.call_args[0][0]
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "custom-model"

    def test_runs_in_project_dir(self, sdlc_dir, config, state):
        with patch("sdlc.phases.implement.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            implement.run(sdlc_dir, config, state)

        assert mock_run.call_args[1]["cwd"] == sdlc_dir.parent
