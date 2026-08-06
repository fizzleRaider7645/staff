from __future__ import annotations

from pathlib import Path

from sdlc.config import SDLCConfig
from sdlc.context import gather_project_context
from sdlc.phases import stream_to_file
from sdlc.phases._prompts import render_prompt
from sdlc.providers import get_provider
from sdlc.state import SDLCState


def run(sdlc_dir: Path, config: SDLCConfig, state: SDLCState,
        model: str | None = None, **kwargs) -> Path:
    resolved_model = config.resolve_model("architect", model)
    provider = get_provider(config.provider)

    spec = (sdlc_dir / "spec.md").read_text()
    project_context = gather_project_context(sdlc_dir.parent, config)

    plan = None
    plan_path = sdlc_dir / "plan.md"
    if plan_path.exists():
        plan = plan_path.read_text()

    system, user = render_prompt("architect", spec=spec, plan=plan,
                                 project_context=project_context)

    state.start_phase("architect", resolved_model, config.provider)
    output_path = sdlc_dir / "architecture.md"

    try:
        stream_to_file(provider, system, user, resolved_model, output_path)
        state.complete_phase("architect", "architecture.md")
        return output_path
    except Exception as e:
        state.fail_phase("architect", str(e))
        raise
