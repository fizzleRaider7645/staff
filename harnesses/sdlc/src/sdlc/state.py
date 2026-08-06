from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PHASE_ORDER = ["plan", "architect", "tasks", "implement", "verify", "review", "refine"]


class SDLCState:
    def __init__(self, sdlc_dir: Path):
        self.sdlc_dir = sdlc_dir
        self.state_file = sdlc_dir / "state.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {"current_phase": None, "phases": {}}

    def save(self) -> None:
        self.state_file.write_text(json.dumps(self.data, indent=2) + "\n")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def start_phase(self, phase: str, model: str, provider: str) -> None:
        self.data["current_phase"] = phase
        self.data["phases"][phase] = {
            "status": "in_progress",
            "started_at": self._now(),
            "model": model,
            "provider": provider,
        }
        self.save()

    def complete_phase(self, phase: str, output_file: str) -> None:
        self.data["phases"][phase]["status"] = "complete"
        self.data["phases"][phase]["completed_at"] = self._now()
        self.data["phases"][phase]["output_file"] = output_file
        self.save()

    def fail_phase(self, phase: str, error: str) -> None:
        self.data["phases"][phase]["status"] = "failed"
        self.data["phases"][phase]["error"] = error
        self.save()

    def phase_status(self, phase: str) -> str:
        return self.data.get("phases", {}).get(phase, {}).get("status", "pending")

    def is_phase_complete(self, phase: str) -> bool:
        return self.phase_status(phase) == "complete"

    def reset_phase(self, phase: str) -> None:
        if phase not in PHASE_ORDER:
            raise ValueError(f"Unknown phase: {phase}")
        idx = PHASE_ORDER.index(phase)
        for p in PHASE_ORDER[idx:]:
            self.data["phases"].pop(p, None)
        if idx > 0 and self.is_phase_complete(PHASE_ORDER[idx - 1]):
            self.data["current_phase"] = PHASE_ORDER[idx - 1]
        else:
            self.data["current_phase"] = None
        self.save()

    def reset_all(self) -> None:
        self.data = {"current_phase": None, "phases": {}}
        self.save()
