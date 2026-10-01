from __future__ import annotations

import asyncio
import time
from typing import Any

from openai import AsyncOpenAI

from tooru.ai.base import AIRequest, AIResponse


class AICircuitOpenError(RuntimeError):
    """Raised while a provider circuit breaker is cooling down."""


class OpenAICompatibleProvider:
    """Resilient adapter for OpenAI-compatible chat-completions APIs."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        client: Any | None = None,
        timeout_seconds: float = 45.0,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.6,
        retry_max_seconds: float = 5.0,
        circuit_breaker_failures: int = 5,
        circuit_breaker_cooldown_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.model = model
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self.retry_max_seconds = max(
            self.retry_base_seconds,
            float(retry_max_seconds),
        )
        self.circuit_breaker_failures = max(
            1,
            int(circuit_breaker_failures),
        )
        self.circuit_breaker_cooldown_seconds = max(
            1.0,
            float(circuit_breaker_cooldown_seconds),
        )
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    def _ensure_circuit_available(self) -> None:
        now = time.monotonic()
        if now < self._circuit_open_until:
            remaining = max(0.0, self._circuit_open_until - now)
            raise AICircuitOpenError(
                f"{self.name} circuit breaker is open for "
                f"{remaining:.1f}s"
            )
        if self._circuit_open_until:
            self._circuit_open_until = 0.0
            self._consecutive_failures = 0

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.circuit_breaker_failures:
            self._circuit_open_until = (
                time.monotonic()
                + self.circuit_breaker_cooldown_seconds
            )

    async def _request(self, messages: list[dict[str, str]], request: AIRequest):
        return await asyncio.wait_for(
            self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=request.max_tokens,
            ),
            timeout=self.timeout_seconds,
        )

    async def generate(self, request: AIRequest) -> AIResponse:
        started = time.perf_counter()
        self._ensure_circuit_available()

        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": request.system_prompt,
                }
            )
        messages.extend(request.messages)

        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                response = await self._request(messages, request)
            except Exception as exc:
                last_error = exc
                self._record_failure()
                if (
                    attempt + 1 >= self.max_attempts
                    or self._circuit_open_until > time.monotonic()
                ):
                    try:
                        setattr(exc, "retry_count", attempt)
                        setattr(
                            exc,
                            "duration_ms",
                            (time.perf_counter() - started) * 1000,
                        )
                    except (AttributeError, TypeError):
                        pass
                    raise
                delay = min(
                    self.retry_max_seconds,
                    self.retry_base_seconds * (2**attempt),
                )
                if delay:
                    await asyncio.sleep(delay)
                continue

            self._record_success()
            content = response.choices[0].message.content or ""
            return AIResponse(
                text=content,
                provider=self.name,
                model=self.model,
                retry_count=attempt,
                duration_ms=(time.perf_counter() - started) * 1000,
            )

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{self.name} returned no response")
