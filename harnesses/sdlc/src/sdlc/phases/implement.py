from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rich.console import Console

from sdlc.config import SDLCConfig
from sdlc.phases._prompts import render_prompt
from sdlc.state import SDLCState

console = Console()


def run(sdlc_dir: Path, config: SDLCConfig, state: SDLCState,
        model: str | None = None, *, task_num: int | None = None, **kwargs) -> Path:
    resolved_model = config.resolve_model("implement", model)
    project_dir = sdlc_dir.parent

    prompt = _build_prompt(sdlc_dir, task_num)

    state.start_phase("implement", resolved_model, config.provider)

    cmd = [config.claude_code_path, "-p", prompt, "--model", resolved_model]

    try:
        console.print(f"  [dim]Running: claude -p ... --model {resolved_model}[/]")
        result = subprocess.run(cmd, cwd=project_dir, check=True, text=True)

        if task_num is not None:
            _mark_task_done(sdlc_dir, task_num)

        state.complete_phase("implement", "tasks.json")
        return sdlc_dir / "tasks.json"
    except FileNotFoundError:
        state.fail_phase("implement", "claude CLI not found")
        console.print("[red]Error:[/] 'claude' CLI not found. Install Claude Code first.")
        raise
    except subprocess.CalledProcessError as e:
        state.fail_phase("implement", f"claude exited with code {e.returncode}")
        raise


def _build_prompt(sdlc_dir: Path, task_num: int | None) -> str:
    architecture = None
    arch_path = sdlc_dir / "architecture.md"
    if arch_path.exists():
        architecture = arch_path.read_text()

    tasks_path = sdlc_dir / "tasks.json"
    task = None
    tasks = []

    if tasks_path.exists():
        tasks_data = json.loads(tasks_path.read_text())
        all_tasks = tasks_data.get("tasks", [])

        if task_num is not None:
            task = all_tasks[task_num - 1]
        else:
            tasks = [t for t in all_tasks if t.get("status") != "done"]

    if not task and not tasks:
        spec = (sdlc_dir / "spec.md").read_text()
        return f"Implement the following requirements:\n\n{spec}"

    _, user = render_prompt("implement", architecture=architecture,
                            task=task, tasks=tasks)
    return user


def _mark_task_done(sdlc_dir: Path, task_num: int) -> None:
    tasks_path = sdlc_dir / "tasks.json"
    if not tasks_path.exists():
        return
    data = json.loads(tasks_path.read_text())
    if task_num <= len(data.get("tasks", [])):
        data["tasks"][task_num - 1]["status"] = "done"
        tasks_path.write_text(json.dumps(data, indent=2) + "\n")
