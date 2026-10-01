from typing import Any

from openai import AsyncOpenAI

from tooru.ai.base import AIRequest, AIResponse


class OpenAICompatibleProvider:
    """Adapter for OpenAI-compatible chat-completions APIs."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
        )

    async def generate(self, request: AIRequest) -> AIResponse:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": request.system_prompt,
                }
            )
        messages.extend(request.messages)

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=request.max_tokens,
        )

        content = response.choices[0].message.content or ""
        return AIResponse(
            text=content,
            provider=self.name,
            model=self.model,
        )
