import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from tooru.memory.engine import MemoryEngine
from tooru.memory.models import MemoryAutomationStatus, MemoryMaintenanceReport

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
        grey_matter=None,
    ):
        self.engine = engine
        self.interval_seconds = max(60, interval_seconds)
        self.archive_after_days = archive_after_days
        self.archive_max_importance = archive_max_importance
        self.archive_max_access_count = archive_max_access_count
        self.auto_consolidate_threshold = auto_consolidate_threshold
        self.consolidate_cooldown_hours = consolidate_cooldown_hours
        self.grey_matter = grey_matter

        self.latest_report: MemoryMaintenanceReport | None = None
        self.run_count = 0
        self.failure_count = 0
        self.last_started_at: str | None = None
        self.last_completed_at: str | None = None
        self.last_error: str | None = None
        self.running = False

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._run_lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.started:
            return
        if self._stop.is_set():
            self._stop = asyncio.Event()
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
        async with self._run_lock:
            self.running = True
            self.last_started_at = datetime.now(UTC).isoformat()
            self.last_error = None
            try:
                report = await asyncio.to_thread(
                    self.engine.maintain,
                    self.archive_after_days,
                    self.archive_max_importance,
                    self.archive_max_access_count,
                    self.auto_consolidate_threshold,
                    self.consolidate_cooldown_hours,
                )
                if self.grey_matter is not None:
                    for (
                        owner_id,
                        scope,
                        project_id,
                        _count,
                        _last_summary_at,
                    ) in self.engine.store.maintenance_scopes():
                        try:
                            await asyncio.to_thread(
                                self.grey_matter.consolidate_scope,
                                owner_id=owner_id,
                                scope=scope,
                                project_id=project_id,
                                limit=500,
                                create_summary=False,
                            )
                        except Exception as exc:  # noqa: BLE001 - sleep cycle is best-effort
                            logger.warning(
                                "Grey Matter sleep consolidation skipped for "
                                "%s/%s/%s: %s",
                                owner_id,
                                scope.value,
                                project_id,
                                exc,
                            )
                self.latest_report = report
                self.run_count += 1
                return report
            except Exception as exc:
                self.failure_count += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Memory maintenance cycle failed")
                raise
            finally:
                self.last_completed_at = datetime.now(UTC).isoformat()
                self.running = False

    def status(self) -> MemoryAutomationStatus:
        return MemoryAutomationStatus(
            started=self.started,
            running=self.running,
            interval_seconds=self.interval_seconds,
            run_count=self.run_count,
            failure_count=self.failure_count,
            last_started_at=self.last_started_at,
            last_completed_at=self.last_completed_at,
            last_error=self.last_error,
            latest_report=self.latest_report,
        )

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
            except Exception as exc:  # noqa: BLE001 - daemon must survive one failed cycle
                logger.warning(
                    "Memory maintenance will retry on the next cycle: %s",
                    exc,
                )
