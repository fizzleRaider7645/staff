from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from sdlc.config import SDLCConfig
from sdlc.state import SDLCState

console = Console()

VERIFY_PROMPT = (
    "Run the project's test suite, linter, and type checker. "
    "Fix any issues you find. Report what you ran and the results."
)


def run(sdlc_dir: Path, config: SDLCConfig, state: SDLCState,
        model: str | None = None, **kwargs) -> Path:
    resolved_model = config.resolve_model("verify", model)
    project_dir = sdlc_dir.parent

    state.start_phase("verify", resolved_model, config.provider)

    cmd = [config.claude_code_path, "-p", VERIFY_PROMPT, "--model", resolved_model]

    try:
        console.print(f"  [dim]Running: claude -p ... --model {resolved_model}[/]")
        result = subprocess.run(cmd, cwd=project_dir, capture_output=True,
                                text=True, check=True)

        output_path = sdlc_dir / "verification.md"
        output_path.write_text(f"# Verification Results\n\n{result.stdout}")

        state.complete_phase("verify", "verification.md")
        return output_path
    except FileNotFoundError:
        state.fail_phase("verify", "claude CLI not found")
        console.print("[red]Error:[/] 'claude' CLI not found. Install Claude Code first.")
        raise
    except subprocess.CalledProcessError as e:
        state.fail_phase("verify", f"Verification failed: {e.returncode}")
        output_path = sdlc_dir / "verification.md"
        output_path.write_text(f"# Verification Results (FAILED)\n\n{e.stdout or ''}\n\n{e.stderr or ''}")
        raise
