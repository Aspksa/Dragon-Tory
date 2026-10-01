from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AIRequest:
    messages: list[dict[str, str]]
    system_prompt: str | None = None
    max_tokens: int = 2_000


@dataclass(slots=True)
class AIResponse:
    text: str
    provider: str
    model: str
    retry_count: int = 0
    duration_ms: float | None = None


class AIProvider(Protocol):
    name: str

    async def generate(self, request: AIRequest) -> AIResponse:
        ...
