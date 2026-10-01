from __future__ import annotations

from typing import Any

from tooru.ai.base import AIProvider, AIRequest, AIResponse


class AIRouter:
    """Provider registry with lightweight runtime telemetry."""

    def __init__(self, *, observability=None) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        self.observability = observability

    @staticmethod
    def _empty_stats() -> dict[str, Any]:
        return {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "last_error": None,
            "last_duration_ms": None,
            "last_retry_count": 0,
            "total_retries": 0,
        }

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.name] = provider
        self._stats.setdefault(provider.name, self._empty_stats())

    def has_provider(self, provider_name: str) -> bool:
        return provider_name in self._providers

    def available_providers(self) -> list[str]:
        return sorted(self._providers)

    def provider_status(self, provider_name: str) -> dict[str, Any]:
        return dict(
            self._stats.get(
                provider_name,
                self._empty_stats(),
            )
        )

    async def generate(
        self,
        provider_name: str,
        request: AIRequest,
        *,
        module: str | None = None,
        operation: str = "generate",
        source_type: str | None = None,
        source_id: str | None = None,
        document_id: str | None = None,
    ) -> AIResponse:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise LookupError(
                f"AI provider is not registered: {provider_name}"
            )

        stats = self._stats.setdefault(
            provider_name,
            self._empty_stats(),
        )
        stats["requests"] += 1

        span_id = None
        if self.observability is not None:
            span_id = self.observability.start_span(
                category="ai",
                stage="analysis",
                operation=operation,
                module=module,
                source_type=source_type,
                source_id=source_id,
                document_id=document_id,
                provider=provider_name,
                model=getattr(provider, "model", None),
                message=f"{provider_name}: {operation}",
            )

        try:
            response = await provider.generate(request)
        except Exception as exc:
            retry_count = int(getattr(exc, "retry_count", 0) or 0)
            duration_ms = getattr(exc, "duration_ms", None)
            stats["failures"] += 1
            stats["last_error"] = (
                f"{type(exc).__name__}: {exc}"[:500]
            )
            stats["last_retry_count"] = retry_count
            stats["total_retries"] += retry_count
            if duration_ms is not None:
                stats["last_duration_ms"] = round(float(duration_ms), 1)
            if span_id is not None:
                self.observability.finish_span(
                    span_id,
                    status="error",
                    retry_count=retry_count,
                    duration_ms=duration_ms,
                    message=f"{type(exc).__name__}: {str(exc)[:300]}",
                )
            raise

        stats["successes"] += 1
        stats["last_error"] = None
        stats["last_retry_count"] = int(response.retry_count or 0)
        stats["total_retries"] += int(response.retry_count or 0)
        if response.duration_ms is not None:
            stats["last_duration_ms"] = round(
                float(response.duration_ms),
                1,
            )

        if span_id is not None:
            self.observability.finish_span(
                span_id,
                status="success",
                retry_count=int(response.retry_count or 0),
                duration_ms=response.duration_ms,
                provider=response.provider,
                model=response.model,
                message="AI-запрос завершён.",
            )
        return response
