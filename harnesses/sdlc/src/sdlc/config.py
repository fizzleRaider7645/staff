from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

MODEL_TIERS: dict[str, dict[str, str]] = {
    "anthropic": {
        "strongest": "claude-opus-4",
        "mid": "claude-sonnet-5",
        "fast": "claude-haiku-4-5",
    },
    "openai": {
        "strongest": "gpt-4o",
        "mid": "gpt-4o-mini",
        "fast": "gpt-4o-mini",
    },
    "google": {
        "strongest": "gemini-2.5-pro",
        "mid": "gemini-2.5-flash",
        "fast": "gemini-2.5-flash",
    },
}

PHASE_TIERS: dict[str, str] = {
    "plan": "strongest",
    "architect": "strongest",
    "tasks": "mid",
    "implement": "mid",
    "verify": "fast",
    "review": "strongest",
    "refine": "strongest",
}

PROVIDERS = list(MODEL_TIERS.keys())


@dataclass
class SDLCConfig:
    provider: str = "anthropic"
    models: dict[str, str] = field(default_factory=dict)
    claude_code_path: str = "claude"
    project_context: dict = field(default_factory=lambda: {
        "include_file_tree": True,
        "max_context_files": 20,
    })

    @classmethod
    def load(cls, sdlc_dir: Path) -> SDLCConfig:
        config_path = sdlc_dir / "config.json"
        if config_path.exists():
            data = json.loads(config_path.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        return cls()

    def save(self, sdlc_dir: Path) -> None:
        config_path = sdlc_dir / "config.json"
        config_path.write_text(json.dumps({
            "provider": self.provider,
            "models": self.models,
            "claude_code_path": self.claude_code_path,
            "project_context": self.project_context,
        }, indent=2) + "\n")

    def resolve_model(self, phase: str, cli_override: str | None = None) -> str:
        if cli_override:
            return cli_override
        if phase in self.models:
            return self.models[phase]
        tier = PHASE_TIERS[phase]
        return MODEL_TIERS[self.provider][tier]
