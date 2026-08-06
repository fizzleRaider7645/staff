from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from sdlc.config import SDLCConfig
from sdlc.phases._prompts import render_prompt
from sdlc.providers import get_provider
from sdlc.state import SDLCState

console = Console()


def run(sdlc_dir: Path, config: SDLCConfig, state: SDLCState,
        model: str | None = None, **kwargs) -> Path:
    resolved_model = config.resolve_model("tasks", model)
    provider = get_provider(config.provider)

    spec = (sdlc_dir / "spec.md").read_text()

    plan = None
    plan_path = sdlc_dir / "plan.md"
    if plan_path.exists():
        plan = plan_path.read_text()

    architecture = None
    arch_path = sdlc_dir / "architecture.md"
    if arch_path.exists():
        architecture = arch_path.read_text()

    system, user = render_prompt("tasks", spec=spec, plan=plan,
                                 architecture=architecture)

    state.start_phase("tasks", resolved_model, config.provider)
    output_path = sdlc_dir / "tasks.json"

    try:
        result = provider.generate(system, user, resolved_model)

        # Strip markdown fences if the model wraps output
        cleaned = result.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        tasks_data = json.loads(cleaned)
        output_path.write_text(json.dumps(tasks_data, indent=2) + "\n")

        task_count = len(tasks_data.get("tasks", []))
        console.print(f"  Generated {task_count} tasks")

        state.complete_phase("tasks", "tasks.json")
        return output_path
    except json.JSONDecodeError as e:
        state.fail_phase("tasks", f"Invalid JSON from model: {e}")
        # Save raw output for debugging
        (sdlc_dir / "tasks_raw.txt").write_text(result)
        console.print(f"[red]Error:[/] Model returned invalid JSON. Raw output saved to .sdlc/tasks_raw.txt")
        raise
    except Exception as e:
        state.fail_phase("tasks", str(e))
        raise
