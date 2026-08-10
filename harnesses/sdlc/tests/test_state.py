from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdlc.state import SDLCState, PHASE_ORDER


class TestPhaseLifecycle:
    def test_start_phase(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")

        assert state.data["current_phase"] == "plan"
        phase = state.data["phases"]["plan"]
        assert phase["status"] == "in_progress"
        assert phase["model"] == "claude-opus-5"
        assert phase["provider"] == "anthropic"
        assert "started_at" in phase

    def test_complete_phase(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        state.complete_phase("plan", "plan.md")

        phase = state.data["phases"]["plan"]
        assert phase["status"] == "complete"
        assert phase["output_file"] == "plan.md"
        assert "completed_at" in phase

    def test_fail_phase(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        state.fail_phase("plan", "API timeout")

        phase = state.data["phases"]["plan"]
        assert phase["status"] == "failed"
        assert phase["error"] == "API timeout"

    def test_multiple_phases_sequential(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        state.complete_phase("plan", "plan.md")
        state.start_phase("architect", "claude-opus-5", "anthropic")

        assert state.data["current_phase"] == "architect"
        assert state.is_phase_complete("plan")
        assert not state.is_phase_complete("architect")


class TestPhaseStatus:
    def test_pending_by_default(self, state: SDLCState):
        assert state.phase_status("plan") == "pending"

    def test_in_progress(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        assert state.phase_status("plan") == "in_progress"

    def test_complete(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        state.complete_phase("plan", "plan.md")
        assert state.phase_status("plan") == "complete"

    def test_is_phase_complete_false_when_pending(self, state: SDLCState):
        assert not state.is_phase_complete("plan")

    def test_is_phase_complete_false_when_in_progress(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        assert not state.is_phase_complete("plan")

    def test_is_phase_complete_true(self, state: SDLCState):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        state.complete_phase("plan", "plan.md")
        assert state.is_phase_complete("plan")


class TestReset:
    def test_reset_phase_cascades(self, state: SDLCState):
        for phase in ["plan", "architect", "tasks"]:
            state.start_phase(phase, "model", "anthropic")
            state.complete_phase(phase, f"{phase}.md")

        state.reset_phase("architect")

        assert state.is_phase_complete("plan")
        assert state.phase_status("architect") == "pending"
        assert state.phase_status("tasks") == "pending"
        assert state.data["current_phase"] == "plan"

    def test_reset_first_phase(self, state: SDLCState):
        state.start_phase("plan", "model", "anthropic")
        state.complete_phase("plan", "plan.md")

        state.reset_phase("plan")

        assert state.phase_status("plan") == "pending"
        assert state.data["current_phase"] is None

    def test_reset_phase_never_started(self, state: SDLCState):
        state.reset_phase("plan")
        assert state.phase_status("plan") == "pending"
        assert state.data["current_phase"] is None

    def test_reset_unknown_phase_raises(self, state: SDLCState):
        with pytest.raises(ValueError, match="Unknown phase"):
            state.reset_phase("nonexistent")

    def test_reset_all(self, state: SDLCState):
        for phase in PHASE_ORDER[:3]:
            state.start_phase(phase, "model", "anthropic")
            state.complete_phase(phase, f"{phase}.md")

        state.reset_all()

        assert state.data["current_phase"] is None
        assert state.data["phases"] == {}

    def test_reset_phase_sets_current_to_previous_complete(self, state: SDLCState):
        state.start_phase("plan", "model", "anthropic")
        state.complete_phase("plan", "plan.md")
        state.start_phase("architect", "model", "anthropic")
        state.complete_phase("architect", "arch.md")
        state.start_phase("tasks", "model", "anthropic")
        state.complete_phase("tasks", "tasks.md")

        state.reset_phase("tasks")

        assert state.data["current_phase"] == "architect"


class TestPersistence:
    def test_auto_saves_on_start(self, state: SDLCState, sdlc_dir: Path):
        state.start_phase("plan", "claude-opus-5", "anthropic")

        on_disk = json.loads((sdlc_dir / "state.json").read_text())
        assert on_disk["current_phase"] == "plan"
        assert on_disk["phases"]["plan"]["status"] == "in_progress"

    def test_auto_saves_on_complete(self, state: SDLCState, sdlc_dir: Path):
        state.start_phase("plan", "claude-opus-5", "anthropic")
        state.complete_phase("plan", "plan.md")

        on_disk = json.loads((sdlc_dir / "state.json").read_text())
        assert on_disk["phases"]["plan"]["status"] == "complete"

    def test_auto_saves_on_reset(self, state: SDLCState, sdlc_dir: Path):
        state.start_phase("plan", "model", "anthropic")
        state.complete_phase("plan", "plan.md")
        state.reset_all()

        on_disk = json.loads((sdlc_dir / "state.json").read_text())
        assert on_disk["phases"] == {}

    def test_reload_from_disk(self, sdlc_dir: Path):
        state1 = SDLCState(sdlc_dir)
        state1.start_phase("plan", "claude-opus-5", "anthropic")
        state1.complete_phase("plan", "plan.md")

        state2 = SDLCState(sdlc_dir)
        assert state2.is_phase_complete("plan")
        assert state2.data["current_phase"] == "plan"

    def test_load_empty_dir(self, sdlc_dir: Path):
        state = SDLCState(sdlc_dir)
        assert state.data == {"current_phase": None, "phases": {}}

    def test_load_corrupt_json(self, sdlc_dir: Path):
        (sdlc_dir / "state.json").write_text("not valid json")
        with pytest.raises(json.JSONDecodeError):
            SDLCState(sdlc_dir)
