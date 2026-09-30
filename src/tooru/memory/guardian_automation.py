import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from tooru.memory.guardian import MemoryGuardian
from tooru.memory.models import (
    MemoryGuardianAutomationStatus,
    MemoryGuardianQueueStatus,
)

logger = logging.getLogger(__name__)


class MemoryGuardianAutomation:
    """Background worker that revisits durable Guardian pending decisions."""

    def __init__(
        self,
        guardian: MemoryGuardian,
        *,
        interval_seconds: int,
        batch_size: int,
    ):
        self.guardian = guardian
        self.interval_seconds = max(60, interval_seconds)
        self.batch_size = max(1, min(200, batch_size))

        self.processed_count = 0
        self.applied_count = 0
        self.rejected_count = 0
        self.dead_count = 0
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
            name="tooru-memory-guardian",
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self) -> MemoryGuardianAutomationStatus:
        async with self._run_lock:
            self.running = True
            self.last_started_at = datetime.now(UTC).isoformat()
            self.last_error = None
            try:
                pending = self.guardian.queue_items(
                    status=MemoryGuardianQueueStatus.PENDING,
                    due_only=True,
                    limit=self.batch_size,
                )
                for item in pending:
                    try:
                        updated = await self.guardian.retry_queue_item(item.id)
                        self.processed_count += 1
                        if updated.status is MemoryGuardianQueueStatus.APPLIED:
                            self.applied_count += 1
                        elif updated.status is MemoryGuardianQueueStatus.REJECTED:
                            self.rejected_count += 1
                        elif updated.status is MemoryGuardianQueueStatus.DEAD:
                            self.dead_count += 1
                    except Exception as exc:  # noqa: BLE001 - one item must not stop queue
                        self.failure_count += 1
                        self.last_error = f"{type(exc).__name__}: {exc}"
                        logger.exception(
                            "Guardian queue item %s failed",
                            item.id,
                        )
            finally:
                self.last_completed_at = datetime.now(UTC).isoformat()
                self.running = False
            return self.status()

    def status(self) -> MemoryGuardianAutomationStatus:
        return MemoryGuardianAutomationStatus(
            started=self.started,
            running=self.running,
            interval_seconds=self.interval_seconds,
            processed_count=self.processed_count,
            applied_count=self.applied_count,
            rejected_count=self.rejected_count,
            dead_count=self.dead_count,
            failure_count=self.failure_count,
            last_started_at=self.last_started_at,
            last_completed_at=self.last_completed_at,
            last_error=self.last_error,
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
            except Exception as exc:  # noqa: BLE001 - daemon must survive failed cycle
                self.failure_count += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Guardian automation cycle failed")
