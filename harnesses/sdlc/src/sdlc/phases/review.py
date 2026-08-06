from __future__ import annotations

import subprocess
from pathlib import Path

from sdlc.config import SDLCConfig
from sdlc.context import gather_project_context
from sdlc.phases import stream_to_file
from sdlc.phases._prompts import render_prompt
from sdlc.providers import get_provider
from sdlc.state import SDLCState


def run(sdlc_dir: Path, config: SDLCConfig, state: SDLCState,
        model: str | None = None, **kwargs) -> Path:
    resolved_model = config.resolve_model("review", model)
    provider = get_provider(config.provider)

    spec = (sdlc_dir / "spec.md").read_text()
    project_context = gather_project_context(sdlc_dir.parent, config)

    architecture = None
    arch_path = sdlc_dir / "architecture.md"
    if arch_path.exists():
        architecture = arch_path.read_text()

    changes = _get_git_changes(sdlc_dir.parent)

    verification = None
    verify_path = sdlc_dir / "verification.md"
    if verify_path.exists():
        verification = verify_path.read_text()

    system, user = render_prompt(
        "review", spec=spec, architecture=architecture,
        changes=changes, verification=verification,
        project_context=project_context,
    )

    state.start_phase("review", resolved_model, config.provider)

    reviews_dir = sdlc_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    review_num = len(list(reviews_dir.glob("review-*.md"))) + 1
    output_path = reviews_dir / f"review-{review_num:03d}.md"

    try:
        stream_to_file(provider, system, user, resolved_model, output_path)
        state.complete_phase("review", f"reviews/review-{review_num:03d}.md")
        return output_path
    except Exception as e:
        state.fail_phase("review", str(e))
        raise


def _get_git_changes(project_dir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=project_dir, capture_output=True, text=True, check=True,
        )
        if not result.stdout.strip():
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                cwd=project_dir, capture_output=True, text=True, check=True,
            )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
