from __future__ import annotations

from pathlib import Path
from typing import Iterator

from rich.console import Console

from sdlc.config import SDLCConfig
from sdlc.state import SDLCState

PHASES = {
    "plan": "sdlc.phases.plan",
    "architect": "sdlc.phases.architect",
    "tasks": "sdlc.phases.tasks",
    "implement": "sdlc.phases.implement",
    "verify": "sdlc.phases.verify",
    "review": "sdlc.phases.review",
    "refine": "sdlc.phases.refine",
}


def run_phase(name: str, sdlc_dir: Path, config: SDLCConfig,
              state: SDLCState, model: str | None = None, **kwargs) -> Path:
    import importlib
    mod = importlib.import_module(PHASES[name])
    return mod.run(sdlc_dir, config, state, model, **kwargs)


def stream_to_file(provider, system: str, user: str, model: str,
                   output_path: Path) -> str:
    """Stream response to terminal and write full text to file."""
    console = Console()
    chunks: list[str] = []
    for chunk in provider.stream(system, user, model):
        console.print(chunk, end="", highlight=False)
        chunks.append(chunk)
    console.print()
    full_text = "".join(chunks)
    output_path.write_text(full_text)
    return full_text
