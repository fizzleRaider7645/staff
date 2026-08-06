from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    keep_trailing_newline=True,
)


def render_prompt(phase: str, **context) -> tuple[str, str]:
    """Render a phase prompt template. Returns (system_prompt, user_prompt).

    Templates use a --- separator between system and user sections.
    """
    template = _env.get_template(f"{phase}.md")
    rendered = template.render(**context)

    if "\n---\n" in rendered:
        system, user = rendered.split("\n---\n", 1)
    else:
        system = ""
        user = rendered

    return system.strip(), user.strip()
