import asyncio
import logging
from contextlib import suppress

from tooru.memory.engine import MemoryEngine
from tooru.memory.models import MemoryMaintenanceReport

logger = logging.getLogger(__name__)


class MemoryAutomation:
    """Periodic maintenance for the local Memory Engine only."""

    def __init__(
        self,
        engine: MemoryEngine,
        *,
        interval_seconds: int,
        archive_after_days: int,
        archive_max_importance: float,
        archive_max_access_count: int,
        auto_consolidate_threshold: int,
        consolidate_cooldown_hours: int,
    ):
        self.engine = engine
        self.interval_seconds = max(60, interval_seconds)
        self.archive_after_days = archive_after_days
        self.archive_max_importance = archive_max_importance
        self.archive_max_access_count = archive_max_access_count
        self.auto_consolidate_threshold = auto_consolidate_threshold
        self.consolidate_cooldown_hours = consolidate_cooldown_hours
        self.latest_report: MemoryMaintenanceReport | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._loop(),
                name="tooru-memory-maintenance",
            )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self) -> MemoryMaintenanceReport:
        report = await asyncio.to_thread(
            self.engine.maintain,
            self.archive_after_days,
            self.archive_max_importance,
            self.archive_max_access_count,
            self.auto_consolidate_threshold,
            self.consolidate_cooldown_hours,
        )
        self.latest_report = report
        return report

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.interval_seconds,
                )
                break
            except TimeoutError:
                pass

            try:
                await self.run_once()
            except Exception:
                logger.exception("Memory maintenance cycle failed")
