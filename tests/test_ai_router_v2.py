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
async def test_router_prefers_deepseek_for_simple_request() -> None:
    router = AIRouter()
    router.register(FakeProvider("deepseek"))
    router.register(FakeProvider("claude"))

    result = await router.route(
        AIRequest(
            messages=[{"role": "user", "content": "Привет"}],
        ),
        preferred="auto",
    )

    assert result.selected_provider == "deepseek"
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_router_prefers_claude_for_complex_request() -> None:
    router = AIRouter()
    router.register(FakeProvider("deepseek"))
    router.register(FakeProvider("claude"))

    result = await router.route(
        AIRequest(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Проанализируй архитектуру и сделай подробный "
                        + ("план " * 300)
                    ),
                }
            ],
        ),
        preferred="auto",
    )

    assert result.selected_provider == "claude"


@pytest.mark.asyncio
async def test_router_falls_back_to_second_provider() -> None:
    router = AIRouter()
    router.register(FakeProvider("deepseek", fail=True))
    router.register(FakeProvider("claude"))

    result = await router.route(
        AIRequest(
            messages=[{"role": "user", "content": "Привет"}],
        ),
        preferred="auto",
    )

    assert result.selected_provider == "claude"
    assert result.fallback_used is True
    assert result.attempted_providers == ["deepseek", "claude"]
    status = router.routing_status()
    assert status["providers"]["deepseek"]["failures"] == 1
    assert status["providers"]["claude"]["successes"] == 1
