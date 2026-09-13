from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdlc.config import SDLCConfig
from sdlc.phases import PHASES, run_phase, stream_to_file
from sdlc.state import SDLCState


@pytest.fixture
def sdlc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sdlc"
    d.mkdir()
    (d / "spec.md").write_text("test spec")
    return d


@pytest.fixture
def state(sdlc_dir: Path) -> SDLCState:
    return SDLCState(sdlc_dir)


@pytest.fixture
def config() -> SDLCConfig:
    return SDLCConfig()


class TestStreamToFile:
    def test_concatenates_chunks(self, tmp_path):
        provider = MagicMock()
        provider.stream.return_value = iter(["hello ", "world"])
        output = tmp_path / "out.md"

        result = stream_to_file(provider, "sys", "usr", "model", output)

        assert result == "hello world"
        assert output.read_text() == "hello world"

    def test_calls_provider_stream(self, tmp_path):
        provider = MagicMock()
        provider.stream.return_value = iter(["x"])
        output = tmp_path / "out.md"

        stream_to_file(provider, "system prompt", "user prompt", "model-1", output)

        provider.stream.assert_called_once_with("system prompt", "user prompt", "model-1")

    def test_handles_empty_stream(self, tmp_path):
        provider = MagicMock()
        provider.stream.return_value = iter([])
        output = tmp_path / "out.md"

        result = stream_to_file(provider, "sys", "usr", "model", output)

        assert result == ""
        assert output.read_text() == ""


class TestRunPhase:
    def test_dispatches_to_correct_module(self, sdlc_dir, config, state):
        mock_module = MagicMock()
        mock_module.run.return_value = sdlc_dir / "plan.md"

        with patch("importlib.import_module", return_value=mock_module) as mock_import:
            result = run_phase("plan", sdlc_dir, config, state)

        mock_import.assert_called_once_with("sdlc.phases.plan")
        mock_module.run.assert_called_once_with(sdlc_dir, config, state, None)

    def test_passes_model_override(self, sdlc_dir, config, state):
        mock_module = MagicMock()
        mock_module.run.return_value = sdlc_dir / "plan.md"

        with patch("importlib.import_module", return_value=mock_module):
            run_phase("plan", sdlc_dir, config, state, model="custom")

        mock_module.run.assert_called_once_with(sdlc_dir, config, state, "custom")

    def test_passes_kwargs(self, sdlc_dir, config, state):
        mock_module = MagicMock()
        mock_module.run.return_value = sdlc_dir / "tasks.json"

        with patch("importlib.import_module", return_value=mock_module):
            run_phase("implement", sdlc_dir, config, state, task_num=3)

        mock_module.run.assert_called_once_with(
            sdlc_dir, config, state, None, task_num=3
        )

    def test_unknown_phase_raises(self, sdlc_dir, config, state):
        with pytest.raises(KeyError):
            run_phase("nonexistent", sdlc_dir, config, state)

    def test_all_phases_have_modules(self):
        expected = {"plan", "architect", "tasks", "implement", "verify", "review", "refine"}
        assert set(PHASES.keys()) == expected
