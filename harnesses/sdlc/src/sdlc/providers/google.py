from __future__ import annotations

from typing import Iterator

from google import genai


class GoogleProvider:
    def __init__(self):
        self.client = genai.Client()

    def generate(self, system: str, user: str, model: str) -> str:
        response = self.client.models.generate_content(
            model=model,
            contents=user,
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
            ),
        )
        return response.text or ""

    def stream(self, system: str, user: str, model: str) -> Iterator[str]:
        response = self.client.models.generate_content_stream(
            model=model,
            contents=user,
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
            ),
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text
