from typing import Any

from anthropic import AsyncAnthropic

from tooru.ai.base import AIRequest, AIResponse


class AnthropicProvider:
    """Claude adapter backed by Anthropic's Messages API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        self.name = "claude"
        self.model = model
        self._client = client or AsyncAnthropic(api_key=api_key)

    async def generate(self, request: AIRequest) -> AIResponse:
        messages = [
            {
                "role": message["role"],
                "content": message["content"],
            }
            for message in request.messages
            if message.get("role") in {"user", "assistant"}
            and message.get("content")
        ]
        if not messages:
            messages = [{"role": "user", "content": "Продолжи."}]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }
        if request.system_prompt:
            kwargs["system"] = request.system_prompt

        response = await self._client.messages.create(**kwargs)
        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
            and isinstance(getattr(block, "text", None), str)
        )
        return AIResponse(
            text=text,
            provider=self.name,
            model=self.model,
        )
