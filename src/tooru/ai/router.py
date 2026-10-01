from typing import Any

from tooru.ai.base import AIProvider, AIRequest, AIResponse


class AIRouter:
    """Small provider registry used by Dragon Tory memory and chat."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._stats: dict[str, dict[str, Any]] = {}

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

    def provider_status(self, provider_name: str) -> dict[str, Any]:
        return dict(
            self._stats.get(
                provider_name,
                {
                    "requests": 0,
                    "successes": 0,
                    "failures": 0,
                    "last_error": None,
                },
            )
        )

    async def generate(
        self,
        provider_name: str,
        request: AIRequest,
    ) -> AIResponse:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise LookupError(
                f"AI provider is not registered: {provider_name}"
            )

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
