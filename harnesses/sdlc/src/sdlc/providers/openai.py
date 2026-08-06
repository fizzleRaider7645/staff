from __future__ import annotations

from typing import Iterator

from openai import OpenAI


class OpenAIProvider:
    def __init__(self):
        self.client = OpenAI()

    def generate(self, system: str, user: str, model: str) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def stream(self, system: str, user: str, model: str) -> Iterator[str]:
        stream = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
