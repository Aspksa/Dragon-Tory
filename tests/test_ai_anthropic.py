from types import SimpleNamespace

import pytest

from tooru.ai.anthropic_provider import AnthropicProvider
from tooru.ai.base import AIRequest


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text",
                    text="Привет от Клода",
                )
            ]
        )


class FakeClient:
    def __init__(self) -> None:
        self.messages = FakeMessages()


@pytest.mark.asyncio
async def test_anthropic_provider_builds_messages_request() -> None:
    client = FakeClient()
    provider = AnthropicProvider(
        api_key="test-key",
        model="claude-sonnet-5-5",
        client=client,
    )

    result = await provider.generate(
        AIRequest(
            system_prompt="Ты проверяющий памяти.",
            messages=[
                {
                    "role": "user",
                    "content": "Проверь решение.",
                }
            ],
            max_tokens=123,
        )
    )

    assert result.text == "Привет от Клода"
    assert result.provider == "claude"
    assert result.model == "claude-sonnet-5-5"

    call = client.messages.calls[0]
    assert call["system"] == "Ты проверяющий памяти."
    assert call["max_tokens"] == 123
    assert call["messages"] == [
        {
            "role": "user",
            "content": "Проверь решение.",
        }
    ]
