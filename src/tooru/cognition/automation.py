from __future__ import annotations

import asyncio


class CognitionAutomation:
    """Periodic local cognition cycle: adapt policy, rebuild graph, scan anomalies."""

    def __init__(
        self,
        service,
        *,
        interval_seconds: int = 900,
    ) -> None:
        self.service = service
        self.interval_seconds = max(60, int(interval_seconds))
        self._task: asyncio.Task | None = None
        self.running = False
        self.failure_count = 0
        self.last_error: str | None = None
        self.last_result: dict | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def run_once(self) -> dict:
        self.running = True
        try:
            result = await asyncio.to_thread(self.service.run_cycle)
            self.last_result = result
            self.last_error = None
            return result
        except Exception as exc:
            self.failure_count += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.running = False

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - next cycle may recover
                self.last_error = self.last_error or "Cognition cycle failed."
            await asyncio.sleep(self.interval_seconds)

    def status(self) -> dict:
        return {
            "started": self._task is not None and not self._task.done(),
            "running": self.running,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
            "last_result": self.last_result,
            "interval_seconds": self.interval_seconds,
        }
