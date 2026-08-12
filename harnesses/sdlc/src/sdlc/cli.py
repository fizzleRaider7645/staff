from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from sdlc.config import SDLCConfig, PROVIDERS
from sdlc.state import SDLCState, PHASE_ORDER

console = Console()


def find_sdlc_dir() -> Path:
    return Path.cwd() / ".sdlc"


def require_sdlc_dir() -> Path:
    sdlc_dir = find_sdlc_dir()
    if not sdlc_dir.exists():
        console.print("[red]Error:[/] No .sdlc/ directory. Run [bold]sdlc init[/] first.")
        raise SystemExit(1)
    return sdlc_dir


@click.group()
@click.version_option(package_name="sdlc")
def main():
    """SDLC — AI-powered development lifecycle orchestration."""


@main.command()
@click.option("--spec", type=click.Path(exists=True), help="Path to a markdown spec file")
@click.option("--prompt", type=str, help="Natural language description")
@click.option("--issue", type=str, help="GitHub issue URL")
@click.option("--provider", type=click.Choice(PROVIDERS), default="anthropic",
              help="AI provider (default: anthropic)")
@click.option("--force", is_flag=True, help="Overwrite existing .sdlc/")
def init(spec: str | None, prompt: str | None, issue: str | None,
         provider: str, force: bool):
    """Initialize a new SDLC cycle in the current directory."""
    sdlc_dir = find_sdlc_dir()

    if sdlc_dir.exists() and not force:
        console.print("[yellow]Warning:[/] .sdlc/ already exists. Use --force to reinitialize.")
        return

    sdlc_dir.mkdir(parents=True, exist_ok=True)

    spec_content = _resolve_spec(spec, prompt, issue)
    (sdlc_dir / "spec.md").write_text(spec_content)

    config = SDLCConfig(provider=provider)
    config.save(sdlc_dir)

    state = SDLCState(sdlc_dir)
    state.save()

    console.print(f"[green]Initialized[/] .sdlc/ with [bold]{provider}[/] provider")
    console.print(f"  Spec: .sdlc/spec.md ({len(spec_content.splitlines())} lines)")


def _resolve_spec(spec_path: str | None, prompt: str | None, issue_url: str | None) -> str:
    if spec_path:
        return Path(spec_path).read_text()
    if prompt:
        return f"# Requirements\n\n{prompt}\n"
    if issue_url:
        return _fetch_github_issue(issue_url)
    content = click.edit("# Requirements\n\n<!-- Describe what you want to build -->\n")
    return content or ""


def _fetch_github_issue(url: str) -> str:
    import json
    import subprocess

    parts = url.rstrip("/").split("/")
    issue_num = parts[-1]
    repo = f"{parts[-4]}/{parts[-3]}"

    result = subprocess.run(
        ["gh", "issue", "view", issue_num, "--repo", repo,
         "--json", "title,body"],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    return f"# {data['title']}\n\n{data['body']}\n"


@main.command()
def status():
    """Show current SDLC state."""
    sdlc_dir = find_sdlc_dir()
    if not sdlc_dir.exists():
        console.print("No .sdlc/ directory found. Run [bold]sdlc init[/] to start.")
        return

    config = SDLCConfig.load(sdlc_dir)
    state = SDLCState(sdlc_dir)

    console.print(f"[bold]SDLC Status[/]  (provider: {config.provider})\n")

    status_icons = {
        "complete": "[green]✓[/]",
        "in_progress": "[yellow]→[/]",
        "failed": "[red]✗[/]",
        "pending": "[dim]○[/]",
    }

    for phase in PHASE_ORDER:
        info = state.data.get("phases", {}).get(phase, {})
        s = info.get("status", "pending")
        icon = status_icons.get(s, "[dim]○[/]")
        model_info = f"  [dim]({info['model']})[/]" if "model" in info else ""
        console.print(f"  {icon} {phase}{model_info}")


@main.command()
@click.argument("phase", required=False)
def reset(phase: str | None):
    """Reset a phase (and subsequent phases) to re-run it."""
    sdlc_dir = require_sdlc_dir()
    state = SDLCState(sdlc_dir)

    if phase:
        if phase not in PHASE_ORDER:
            console.print(f"[red]Error:[/] Unknown phase: {phase}")
            console.print(f"  Valid phases: {', '.join(PHASE_ORDER)}")
            raise SystemExit(1)
        state.reset_phase(phase)
        console.print(f"[green]Reset[/] {phase} and all subsequent phases")
    else:
        state.reset_all()
        console.print("[green]Reset[/] all phases")


# --- Phase commands ---

THINKING_PHASES = {
    "plan": "Generate a development plan from the spec",
    "architect": "Design the technical architecture",
    "tasks": "Break the architecture into implementation tasks",
    "review": "Review the implementation against the spec",
    "refine": "Generate refinement suggestions from review + feedback",
}


def _run_phase_safe(phase_name: str, sdlc_dir: Path, config: SDLCConfig,
                    state: SDLCState, model: str | None = None, **kwargs) -> Path | None:
    from sdlc.phases import run_phase
    try:
        return run_phase(phase_name, sdlc_dir, config, state, model, **kwargs)
    except Exception as e:
        console.print(f"\n[red]Error in {phase_name}:[/] {e}")
        raise SystemExit(1)


def _make_phase_command(phase_name: str, help_text: str):
    @main.command(name=phase_name, help=help_text)
    @click.option("--model", type=str, default=None, help="Override the model for this phase")
    def phase_cmd(model):
        sdlc_dir = require_sdlc_dir()
        config = SDLCConfig.load(sdlc_dir)
        state = SDLCState(sdlc_dir)

        console.print(f"\n[bold]Phase: {phase_name}[/]")
        output = _run_phase_safe(phase_name, sdlc_dir, config, state, model)
        console.print(f"\n[green]Done.[/] Output: {output.relative_to(Path.cwd())}")

    return phase_cmd


for _name, _help in THINKING_PHASES.items():
    _make_phase_command(_name, _help)


@main.command()
@click.option("--model", type=str, default=None, help="Override the model")
@click.option("--task", "task_num", type=int, default=None,
              help="Run a specific task number")
def implement(model, task_num):
    """Implement tasks using Claude Code."""
    sdlc_dir = require_sdlc_dir()
    config = SDLCConfig.load(sdlc_dir)
    state = SDLCState(sdlc_dir)

    console.print("\n[bold]Phase: implement[/]")
    _run_phase_safe("implement", sdlc_dir, config, state, model, task_num=task_num)
    console.print("\n[green]Done.[/]")


@main.command()
@click.option("--model", type=str, default=None, help="Override the model")
def verify(model):
    """Run tests, linter, and type checker via Claude Code."""
    sdlc_dir = require_sdlc_dir()
    config = SDLCConfig.load(sdlc_dir)
    state = SDLCState(sdlc_dir)

    console.print("\n[bold]Phase: verify[/]")
    output = _run_phase_safe("verify", sdlc_dir, config, state, model)
    console.print(f"\n[green]Done.[/] Output: {output.relative_to(Path.cwd())}")


@main.command(name="run")
@click.option("--model", type=str, default=None, help="Override the model for all phases")
def run_all(model):
    """Run full SDLC sequence with approval gates between phases."""
    sdlc_dir = require_sdlc_dir()
    config = SDLCConfig.load(sdlc_dir)
    state = SDLCState(sdlc_dir)

    for phase in PHASE_ORDER:
        if state.is_phase_complete(phase):
            console.print(f"[dim]Skipping {phase} (already complete)[/]")
            continue

        console.print(f"\n[bold]Phase: {phase}[/]")
        if not click.confirm(f"  Proceed with {phase}?", default=True):
            console.print("[yellow]Stopped.[/] Resume later with [bold]sdlc run[/].")
            return

        _run_phase_safe(phase, sdlc_dir, config, state, model)

    console.print("\n[bold green]All phases complete![/]")
