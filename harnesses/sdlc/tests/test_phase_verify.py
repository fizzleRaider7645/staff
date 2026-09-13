from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdlc.config import SDLCConfig
from sdlc.phases import verify
from sdlc.state import SDLCState


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    return d


@pytest.fixture
def state(sdlc_dir: Path) -> SDLCState:
    return SDLCState(sdlc_dir)


@pytest.fixture
def config() -> SDLCConfig:
    return SDLCConfig()


class TestVerifyRun:
    def test_calls_claude_cli(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="All tests pass")
            result = verify.run(sdlc_dir, config, state)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd

    def test_writes_verification_output(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="All 42 tests pass")
            result = verify.run(sdlc_dir, config, state)

        assert result == sdlc_dir / "verification.md"
        content = result.read_text()
        assert "Verification Results" in content
        assert "All 42 tests pass" in content

    def test_updates_state_on_success(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            verify.run(sdlc_dir, config, state)

        assert state.is_phase_complete("verify")

    def test_marks_failed_on_cli_not_found(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with pytest.raises(FileNotFoundError):
                verify.run(sdlc_dir, config, state)

        assert state.phase_status("verify") == "failed"
        assert "not found" in state.data["phases"]["verify"]["error"]

    def test_marks_failed_on_nonzero_exit(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "claude", output="FAIL: test_x", stderr="error details"
            )
            with pytest.raises(subprocess.CalledProcessError):
                verify.run(sdlc_dir, config, state)

        assert state.phase_status("verify") == "failed"

    def test_saves_output_on_failure(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "claude", output="FAIL: test_x", stderr="traceback"
            )
            with pytest.raises(subprocess.CalledProcessError):
                verify.run(sdlc_dir, config, state)

        output = (sdlc_dir / "verification.md").read_text()
        assert "FAILED" in output
        assert "FAIL: test_x" in output

    def test_uses_model_override(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            verify.run(sdlc_dir, config, state, model="claude-haiku-4-5")

        cmd = mock_run.call_args[0][0]
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-haiku-4-5"

    def test_captures_output(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            verify.run(sdlc_dir, config, state)

        assert mock_run.call_args[1]["capture_output"] is True

    def test_uses_verify_prompt(self, sdlc_dir, config, state):
        with patch("sdlc.phases.verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            verify.run(sdlc_dir, config, state)

        cmd = mock_run.call_args[0][0]
        prompt_idx = cmd.index("-p")
        prompt = cmd[prompt_idx + 1]
        assert "test suite" in prompt.lower()
