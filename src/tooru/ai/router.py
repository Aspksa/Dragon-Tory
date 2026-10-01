from dataclasses import dataclass
from typing import Any

from tooru.ai.base import AIProvider, AIRequest, AIResponse


class AIRoutingError(RuntimeError):
    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        details = "; ".join(
            f"{name}: {message}" for name, message in errors.items()
        )
        super().__init__(details or "No AI provider is available.")


@dataclass(slots=True)
class AIRouteResult:
    response: AIResponse
    preferred_provider: str
    selected_provider: str
    attempted_providers: list[str]
    fallback_used: bool
    reason: str


class AIRouter:
    """Routes AI requests and provides resilient fallback between providers."""

    COMPLEX_KEYWORDS = (
        "проанализ",
        "архитектур",
        "рефактор",
        "сравни",
        "документ",
        "план реализации",
        "найди ошиб",
        "объясни подробно",
        "код",
        "design",
        "architecture",
        "debug",
        "refactor",
        "compare",
    )

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        self._last_route: dict[str, Any] | None = None

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.name] = provider
        self._stats.setdefault(
            provider.name,
            {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "last_error": None,
            },
        )

    def has_provider(self, provider_name: str) -> bool:
        return provider_name in self._providers

    def available_providers(self) -> list[str]:
        return sorted(self._providers)

    def routing_status(self) -> dict[str, Any]:
        return {
            "providers": {
                name: dict(self._stats.get(name, {}))
                for name in self.available_providers()
            },
            "last_route": dict(self._last_route) if self._last_route else None,
        }

    async def generate(
        self,
        provider_name: str,
        request: AIRequest,
    ) -> AIResponse:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise LookupError(f"AI provider is not registered: {provider_name}")
        return await self._call(provider_name, provider, request)

    async def route(
        self,
        request: AIRequest,
        *,
        preferred: str = "auto",
        allow_fallback: bool = True,
    ) -> AIRouteResult:
        order, reason = self._route_order(request, preferred)
        if not order:
            raise AIRoutingError({"router": "No AI provider is configured."})
        if not allow_fallback:
            order = order[:1]

        attempted: list[str] = []
        errors: dict[str, str] = {}
        for provider_name in order:
            provider = self._providers[provider_name]
            attempted.append(provider_name)
            try:
                response = await self._call(
                    provider_name,
                    provider,
                    request,
                )
                result = AIRouteResult(
                    response=response,
                    preferred_provider=preferred,
                    selected_provider=provider_name,
                    attempted_providers=attempted,
                    fallback_used=len(attempted) > 1,
                    reason=reason,
                )
                self._last_route = {
                    "preferred": preferred,
                    "selected": provider_name,
                    "attempted": list(attempted),
                    "fallback_used": result.fallback_used,
                    "reason": reason,
                }
                return result
            except Exception as exc:  # noqa: BLE001 - provider boundary
                errors[provider_name] = (
                    f"{type(exc).__name__}: {exc}"
                )

        self._last_route = {
            "preferred": preferred,
            "selected": None,
            "attempted": list(attempted),
            "fallback_used": len(attempted) > 1,
            "reason": reason,
            "errors": errors,
        }
        raise AIRoutingError(errors)

    async def _call(
        self,
        provider_name: str,
        provider: AIProvider,
        request: AIRequest,
    ) -> AIResponse:
        stats = self._stats.setdefault(
            provider_name,
            {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "last_error": None,
            },
        )
        stats["requests"] += 1
        try:
            response = await provider.generate(request)
        except Exception as exc:
            stats["failures"] += 1
            stats["last_error"] = (
                f"{type(exc).__name__}: {exc}"[:500]
            )
            raise
        stats["successes"] += 1
        stats["last_error"] = None
        return response

    def _route_order(
        self,
        request: AIRequest,
        preferred: str,
    ) -> tuple[list[str], str]:
        available = self.available_providers()
        if not available:
            return [], "Нет настроенных ИИ-провайдеров."

        if preferred != "auto":
            primary = [preferred] if preferred in self._providers else []
            fallback = [
                name
                for name in ("deepseek", "claude")
                if name in available and name not in primary
            ]
            fallback.extend(
                name
                for name in available
                if name not in primary and name not in fallback
            )
            return primary + fallback, f"Пользователь выбрал: {preferred}."

        score = self._complexity_score(request)
        if score >= 2 and "claude" in self._providers:
            first = "claude"
            reason = f"Автовыбор Клода: сложность запроса {score}."
        elif "deepseek" in self._providers:
            first = "deepseek"
            reason = f"Автовыбор DeepSeek: сложность запроса {score}."
        elif "claude" in self._providers:
            first = "claude"
            reason = "DeepSeek недоступен, выбран Клод."
        else:
            first = available[0]
            reason = f"Выбран доступный провайдер: {first}."

        order = [first]
        for name in ("deepseek", "claude"):
            if name in self._providers and name not in order:
                order.append(name)
        order.extend(name for name in available if name not in order)
        return order, reason

    def _complexity_score(self, request: AIRequest) -> int:
        content = " ".join(
            message.get("content", "")
            for message in request.messages
        ).lower()
        score = 0
        if len(content) >= 1_200:
            score += 1
        if len(request.messages) >= 8:
            score += 1
        if request.system_prompt and len(request.system_prompt) >= 8_000:
            score += 1
        if any(keyword in content for keyword in self.COMPLEX_KEYWORDS):
            score += 1
        return score
