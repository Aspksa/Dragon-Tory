from types import SimpleNamespace

import pytest

from tooru.ai.base import AIRequest
from tooru.ai.openai_compatible import AICircuitOpenError, OpenAICompatibleProvider


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



class FlakyCompletions:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary provider failure")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="recovered")
                )
            ]
        )


class FlakyClient:
    def __init__(self, failures: int) -> None:
        self.completions = FlakyCompletions(failures)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.mark.asyncio
async def test_provider_retries_transient_failure() -> None:
    client = FlakyClient(failures=1)
    provider = OpenAICompatibleProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="deepseek-test",
        client=client,
        max_attempts=2,
        retry_base_seconds=0,
        circuit_breaker_failures=5,
    )

    result = await provider.generate(
        AIRequest(messages=[{"role": "user", "content": "test"}])
    )

    assert result.text == "recovered"
    assert client.completions.calls == 2


@pytest.mark.asyncio
async def test_provider_circuit_breaker_stops_repeat_failures() -> None:
    client = FlakyClient(failures=10)
    provider = OpenAICompatibleProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="deepseek-test",
        client=client,
        max_attempts=1,
        retry_base_seconds=0,
        circuit_breaker_failures=1,
        circuit_breaker_cooldown_seconds=60,
    )

    with pytest.raises(RuntimeError):
        await provider.generate(
            AIRequest(messages=[{"role": "user", "content": "first"}])
        )

    with pytest.raises(AICircuitOpenError):
        await provider.generate(
            AIRequest(messages=[{"role": "user", "content": "second"}])
        )

    assert client.completions.calls == 1

class PermanentHTTPError(RuntimeError):
    status_code = 401


class PermanentFailureCompletions:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        raise PermanentHTTPError("invalid api key")


class PermanentFailureClient:
    def __init__(self) -> None:
        self.completions = PermanentFailureCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.mark.asyncio
async def test_provider_does_not_retry_permanent_http_error() -> None:
    client = PermanentFailureClient()
    provider = OpenAICompatibleProvider(
        name="deepseek",
        api_key="bad-key",
        base_url="https://example.invalid/v1",
        model="deepseek-test",
        client=client,
        max_attempts=3,
        retry_base_seconds=0,
        circuit_breaker_failures=5,
    )

    with pytest.raises(PermanentHTTPError):
        await provider.generate(
            AIRequest(messages=[{"role": "user", "content": "test"}])
        )

    assert client.completions.calls == 1

