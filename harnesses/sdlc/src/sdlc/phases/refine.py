from __future__ import annotations

from pathlib import Path

import click

from sdlc.config import SDLCConfig
from sdlc.phases import stream_to_file
from sdlc.phases._prompts import render_prompt
from sdlc.providers import get_provider
from sdlc.state import SDLCState


def run(sdlc_dir: Path, config: SDLCConfig, state: SDLCState,
        model: str | None = None, **kwargs) -> Path:
    resolved_model = config.resolve_model("refine", model)
    provider = get_provider(config.provider)

    spec = (sdlc_dir / "spec.md").read_text()

    architecture = None
    arch_path = sdlc_dir / "architecture.md"
    if arch_path.exists():
        architecture = arch_path.read_text()

    review = _latest_review(sdlc_dir)

    feedback = click.edit(
        "# Feedback\n\n"
        "<!-- Describe what you observed when running the product.\n"
        "     What works? What doesn't? What needs to change? -->\n"
    )
    if not feedback or feedback.strip().startswith("# Feedback\n\n<!--"):
        feedback = None

    system, user = render_prompt(
        "refine", spec=spec, architecture=architecture,
        review=review, feedback=feedback,
    )

    state.start_phase("refine", resolved_model, config.provider)

    refinements_dir = sdlc_dir / "refinements"
    refinements_dir.mkdir(exist_ok=True)
    refine_num = len(list(refinements_dir.glob("refinement-*.md"))) + 1
    output_path = refinements_dir / f"refinement-{refine_num:03d}.md"

    try:
        stream_to_file(provider, system, user, resolved_model, output_path)
        state.complete_phase("refine", f"refinements/refinement-{refine_num:03d}.md")
        return output_path
    except Exception as e:
        state.fail_phase("refine", str(e))
        raise


def _latest_review(sdlc_dir: Path) -> str | None:
    reviews_dir = sdlc_dir / "reviews"
    if not reviews_dir.exists():
        return None
    reviews = sorted(reviews_dir.glob("review-*.md"))
    if reviews:
        return reviews[-1].read_text()
    return None
