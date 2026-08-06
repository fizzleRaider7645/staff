from __future__ import annotations

from typing import Iterator, Protocol


class LLMProvider(Protocol):
    """Thin protocol for text generation. No tool use, no chat history."""

    def generate(self, system: str, user: str, model: str) -> str: ...

    def stream(self, system: str, user: str, model: str) -> Iterator[str]: ...


def get_provider(name: str) -> LLMProvider:
    match name:
        case "anthropic":
            from .anthropic import AnthropicProvider
            return AnthropicProvider()
        case "openai":
            from .openai import OpenAIProvider
            return OpenAIProvider()
        case "google":
            from .google import GoogleProvider
            return GoogleProvider()
        case _:
            raise ValueError(f"Unknown provider: {name}")
