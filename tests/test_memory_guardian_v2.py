import json
from pathlib import Path

import pytest

from tooru.ai.base import AIRequest, AIResponse
from tooru.ai.router import AIRouter
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.guardian_automation import MemoryGuardianAutomation
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import (
    ConversationMessage,
    MemoryGuardianQueueStatus,
    MemoryGuardianRequest,
    MemoryKind,
    MemoryScope,
    MemorySearch,
)
from tooru.memory.store import SQLiteMemoryStore


class FakeProvider:
    def __init__(self, name: str, payload: dict):
        self.name = name
        self.payload = payload

    async def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            text=json.dumps(self.payload, ensure_ascii=False),
            provider=self.name,
            model=f"fake-{self.name}",
        )


class FailingProvider:
    name = "claude"

    async def generate(self, request: AIRequest) -> AIResponse:
        raise RuntimeError("review service unavailable")


def build_guardian(
    tmp_path: Path,
    *,
    router: AIRouter | None = None,
    retry_delay_seconds: int = 0,
    max_attempts: int = 5,
) -> tuple[MemoryEngine, SQLiteMemoryStore, AIRouter, MemoryGuardian]:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    engine = MemoryEngine(store, HashEmbeddingProvider(128))
    engine.initialize()
    router = router or AIRouter()
    intelligence = MemoryIntelligence(
        engine,
        router,
        IntelligenceConfig(
            primary_provider="deepseek",
            reviewer_provider="claude",
        ),
    )
    guardian = MemoryGuardian(
        intelligence,
        store,
        GuardianConfig(
            retry_delay_seconds=retry_delay_seconds,
            max_attempts=max_attempts,
        ),
    )
    return engine, store, router, guardian


def high_impact_request() -> MemoryGuardianRequest:
    return MemoryGuardianRequest(
        scope=MemoryScope.PROJECT,
        project_id="dragon-tory",
        use_ai=False,
        messages=[
            ConversationMessage(
                role="user",
                content="Решили полностью изменить основную архитектуру памяти проекта.",
            )
        ],
    )


@pytest.mark.asyncio
async def test_pending_queue_is_deduplicated_and_persistent(tmp_path: Path) -> None:
    _, store, _, guardian = build_guardian(tmp_path)

    first = await guardian.process(high_impact_request())
    second = await guardian.process(high_impact_request())

    assert first.pending_count == 1
    assert second.pending_count == 1
    assert first.decisions[0].queue_id == second.decisions[0].queue_id

    pending = guardian.queue_items(status=MemoryGuardianQueueStatus.PENDING)
    assert len(pending) == 1

    reopened = SQLiteMemoryStore(store.db_path)
    reopened.initialize()
    persisted = reopened.guardian_queue_items(
        status=MemoryGuardianQueueStatus.PENDING
    )
    assert len(persisted) == 1
    assert persisted[0].id == pending[0].id


@pytest.mark.asyncio
async def test_pending_memory_retries_when_claude_becomes_available(
    tmp_path: Path,
) -> None:
    engine, _, router, guardian = build_guardian(tmp_path)

    initial = await guardian.process(high_impact_request())
    queue_id = initial.decisions[0].queue_id
    assert queue_id is not None

    router.register(
        FakeProvider(
            "claude",
            {
                "decisions": [
                    {
                        "action": "create",
                        "content": "Новая архитектура памяти проекта утверждена после проверки.",
                        "kind": "decision",
                        "key": "memory.architecture",
                        "importance": 0.95,
                        "confidence": 0.98,
                        "tags": ["guardian", "reviewed"],
                        "target_memory_id": None,
                        "reason": "Reviewed durable architecture decision.",
                    }
                ]
            },
        )
    )

    updated = await guardian.retry_queue_item(queue_id)

    assert updated.status is MemoryGuardianQueueStatus.APPLIED
    memories = engine.store.candidates(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="архитектура памяти",
            limit=10,
        )
    )
    assert any(item.key == "memory.architecture" for item in memories)


@pytest.mark.asyncio
async def test_manual_approve_and_reject_pending_items(tmp_path: Path) -> None:
    engine, _, _, guardian = build_guardian(tmp_path)

    first = await guardian.process(high_impact_request())
    approve_id = first.decisions[0].queue_id
    assert approve_id is not None

    approved = guardian.approve_queue_item(
        approve_id,
        reason="Approved locally by the user.",
    )
    assert approved.status is MemoryGuardianQueueStatus.APPLIED
    assert any(
        item.kind is MemoryKind.DECISION
        for item in engine.store.candidates(
            MemorySearch(
                scope=MemoryScope.PROJECT,
                project_id="dragon-tory",
                query="архитектуру памяти",
                limit=10,
            )
        )
    )

    second = await guardian.process(
        MemoryGuardianRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            use_ai=False,
            messages=[
                ConversationMessage(
                    role="user",
                    content="Решили заменить критическую политику резервных копий.",
                )
            ],
        )
    )
    reject_id = second.decisions[0].queue_id
    assert reject_id is not None

    rejected = guardian.reject_queue_item(
        reject_id,
        reason="Rejected during local review.",
    )
    assert rejected.status is MemoryGuardianQueueStatus.REJECTED


@pytest.mark.asyncio
async def test_guardian_automation_processes_due_queue(tmp_path: Path) -> None:
    _, _, router, guardian = build_guardian(
        tmp_path,
        retry_delay_seconds=0,
    )
    initial = await guardian.process(high_impact_request())
    assert initial.pending_count == 1

    router.register(
        FakeProvider(
            "claude",
            {
                "decisions": [
                    {
                        "action": "create",
                        "content": "Архитектура памяти подтверждена автоматической проверкой.",
                        "kind": "decision",
                        "key": "memory.architecture.auto",
                        "importance": 0.94,
                        "confidence": 0.99,
                        "tags": ["guardian", "automatic-review"],
                        "target_memory_id": None,
                        "reason": "Automatic reviewer approved.",
                    }
                ]
            },
        )
    )

    automation = MemoryGuardianAutomation(
        guardian,
        interval_seconds=60,
        batch_size=10,
    )
    status = await automation.run_once()

    assert status.running is False
    assert status.processed_count == 1
    assert status.applied_count == 1
    assert guardian.status().queued_pending == 0
    assert guardian.status().queued_applied == 1


@pytest.mark.asyncio
async def test_failed_reviewer_goes_to_dead_letter_at_max_attempts(
    tmp_path: Path,
) -> None:
    _, _, router, guardian = build_guardian(
        tmp_path,
        retry_delay_seconds=0,
        max_attempts=1,
    )
    initial = await guardian.process(high_impact_request())
    queue_id = initial.decisions[0].queue_id
    assert queue_id is not None

    router.register(FailingProvider())
    updated = await guardian.retry_queue_item(queue_id)

    assert updated.status is MemoryGuardianQueueStatus.DEAD
    assert updated.attempts == 1
    assert "RuntimeError" in (updated.last_error or "")
