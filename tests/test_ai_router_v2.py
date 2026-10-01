import pytest

from tooru.ai.base import AIRequest, AIResponse
from tooru.ai.router import AIRouter


class FakeProvider:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail

    async def generate(self, request: AIRequest) -> AIResponse:
        if self.fail:
            raise RuntimeError(f"{self.name} unavailable")
        return AIResponse(
            text=f"answer-{self.name}",
            provider=self.name,
            model=f"model-{self.name}",
        )


@pytest.mark.asyncio
async def test_router_generates_with_deepseek() -> None:
    router = AIRouter()
    router.register(FakeProvider("deepseek"))

    result = await router.generate(
        "deepseek",
        AIRequest(messages=[{"role": "user", "content": "Привет"}]),
    )

    assert result.provider == "deepseek"
    status = router.provider_status("deepseek")
    assert status["requests"] == 1
    assert status["successes"] == 1
    assert status["failures"] == 0


@pytest.mark.asyncio
async def test_router_records_deepseek_failure() -> None:
    router = AIRouter()
    router.register(FakeProvider("deepseek", fail=True))

    with pytest.raises(RuntimeError):
        await router.generate(
            "deepseek",
            AIRequest(messages=[{"role": "user", "content": "Привет"}]),
        )

    status = router.provider_status("deepseek")
    assert status["requests"] == 1
    assert status["successes"] == 0
    assert status["failures"] == 1
    assert "unavailable" in status["last_error"]
