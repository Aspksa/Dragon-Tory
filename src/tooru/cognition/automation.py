from __future__ import annotations

import asyncio


class CognitionAutomation:
    """Periodic and event-driven cognition with serialized local cycles."""

    def __init__(
        self,
        service,
        *,
        interval_seconds: int = 900,
    ) -> None:
        self.service = service
        self.interval_seconds = max(60, int(interval_seconds))
        self._task: asyncio.Task | None = None
        self._trigger_task: asyncio.Task | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
        self.running = False
        self.failure_count = 0
        self.last_error: str | None = None
        self.last_result: dict | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._event_loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        tasks = [
            task
            for task in (self._task, self._trigger_task)
            if task is not None and not task.done()
        ]
        self._task = None
        self._trigger_task = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._event_loop = None

    async def run_once(self) -> dict:
        async with self._lock:
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

    def trigger(self, *, delay_seconds: float = 0.35) -> bool:
        """Debounce a cognition cycle from async or FastAPI worker threads."""
        loop = self._event_loop
        if loop is None or loop.is_closed() or not loop.is_running():
            return False
        delay = max(0.05, min(float(delay_seconds), 5.0))
        loop.call_soon_threadsafe(self._schedule_trigger, delay)
        return True

    def _schedule_trigger(self, delay_seconds: float) -> None:
        current = self._trigger_task
        if current is not None and not current.done():
            current.cancel()
        self._trigger_task = asyncio.create_task(
            self._trigger_after(delay_seconds)
        )

    async def _trigger_after(self, delay_seconds: float) -> None:
        current = asyncio.current_task()
        try:
            await asyncio.sleep(delay_seconds)
            await self.run_once()
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 - next trigger/periodic cycle may recover
            self.last_error = self.last_error or "Cognition trigger failed."
        finally:
            if self._trigger_task is current:
                self._trigger_task = None

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
            "trigger_pending": (
                self._trigger_task is not None
                and not self._trigger_task.done()
            ),
            "interval_seconds": self.interval_seconds,
        }
