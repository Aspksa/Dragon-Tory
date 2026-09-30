import asyncio
import time

import pytest

from tooru.memory.maintenance import MemoryAutomation
from tooru.memory.models import MemoryMaintenanceReport


class FakeEngine:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def maintain(
        self,
        archive_after_days: int,
        archive_max_importance: float,
        archive_max_access_count: int,
        auto_consolidate_threshold: int,
        consolidate_cooldown_hours: int,
    ) -> MemoryMaintenanceReport:
        del (
            archive_after_days,
            archive_max_importance,
            archive_max_access_count,
            auto_consolidate_threshold,
            consolidate_cooldown_hours,
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls += 1
        try:
            time.sleep(0.05)
            return MemoryMaintenanceReport(
                started_at="2026-10-01T00:00:00+00:00",
                completed_at="2026-10-01T00:00:01+00:00",
            )
        finally:
            self.active -= 1


def make_automation(engine: FakeEngine) -> MemoryAutomation:
    return MemoryAutomation(
        engine,  # type: ignore[arg-type]
        interval_seconds=60,
        archive_after_days=180,
        archive_max_importance=0.3,
        archive_max_access_count=1,
        auto_consolidate_threshold=40,
        consolidate_cooldown_hours=24,
    )


@pytest.mark.asyncio
async def test_manual_maintenance_runs_are_serialized() -> None:
    engine = FakeEngine()
    automation = make_automation(engine)

    first, second = await asyncio.gather(
        automation.run_once(),
        automation.run_once(),
    )

    assert first.completed_at
    assert second.completed_at
    assert engine.calls == 2
    assert engine.max_active == 1

    status = automation.status()
    assert status.run_count == 2
    assert status.failure_count == 0
    assert status.running is False
    assert status.last_error is None


@pytest.mark.asyncio
async def test_automation_can_restart_cleanly() -> None:
    engine = FakeEngine()
    automation = make_automation(engine)

    automation.start()
    assert automation.status().started is True
    await automation.stop()
    assert automation.status().started is False

    automation.start()
    assert automation.status().started is True
    await automation.stop()
    assert automation.status().started is False
