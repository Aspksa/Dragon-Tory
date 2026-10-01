from types import SimpleNamespace

import pytest

from tooru.ai.base import AIRequest
from tooru.ai.openai_compatible import OpenAICompatibleProvider


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Привет от DeepSeek")
                )
            ]
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.mark.asyncio
async def test_openai_compatible_provider_builds_chat_request() -> None:
    client = FakeClient()
    provider = OpenAICompatibleProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://foundation-models.api.cloud.ru/v1/",
        model="deepseek-ai/DeepSeek-V4-Flash",
        client=client,
    )

    result = await provider.generate(
        AIRequest(
            system_prompt="Ты внутренний AI памяти.",
            messages=[{"role": "user", "content": "Проверь память"}],
            max_tokens=321,
        )
    )

    assert result.text == "Привет от DeepSeek"
    assert result.provider == "deepseek"
    assert result.model == "deepseek-ai/DeepSeek-V4-Flash"

    call = client.completions.calls[0]
    assert call["model"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert call["max_tokens"] == 321
    assert call["messages"] == [
        {"role": "system", "content": "Ты внутренний AI памяти."},
        {"role": "user", "content": "Проверь память"},
    ]
