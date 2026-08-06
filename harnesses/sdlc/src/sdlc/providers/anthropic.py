from __future__ import annotations

from typing import Iterator

from anthropic import Anthropic


class AnthropicProvider:
    def __init__(self):
        self.client = Anthropic()

    def generate(self, system: str, user: str, model: str) -> str:
        response = self.client.messages.create(
            model=model,
            max_tokens=16384,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    def stream(self, system: str, user: str, model: str) -> Iterator[str]:
        with self.client.messages.stream(
            model=model,
            max_tokens=16384,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            yield from stream.text_stream
