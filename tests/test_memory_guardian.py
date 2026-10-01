import json
from pathlib import Path

import pytest

from tooru.ai.base import AIRequest, AIResponse
from tooru.ai.router import AIRouter
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import (
    ConversationMessage,
    MemoryCreate,
    MemoryGuardianOutcome,
    MemoryGuardianRequest,
    MemoryGuardianRisk,
    MemoryKind,
    MemoryScope,
)
from tooru.memory.store import SQLiteMemoryStore


class FakeProvider:
    def __init__(self, name: str, payload: dict | list[dict]):
        self.name = name
        self.payloads = payload if isinstance(payload, list) else [payload]
        self.calls = 0

    async def generate(self, request: AIRequest) -> AIResponse:
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return AIResponse(
            text=json.dumps(payload, ensure_ascii=False),
            provider=self.name,
            model=f"fake-{self.name}",
        )


def make_guardian(
    tmp_path: Path,
    router: AIRouter | None = None,
) -> tuple[MemoryEngine, MemoryGuardian]:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    engine = MemoryEngine(store, HashEmbeddingProvider(128))
    engine.initialize()
    router = router or AIRouter()
    intelligence = MemoryIntelligence(
        engine,
        router,
        IntelligenceConfig(
            primary_provider="deepseek",
            reviewer_provider="deepseek",
        ),
    )
    guardian = MemoryGuardian(
        intelligence,
        store,
        GuardianConfig(),
    )
    return engine, guardian


@pytest.mark.asyncio
async def test_low_medium_safe_memory_can_apply_with_local_fallback(
    tmp_path: Path,
) -> None:
    engine, guardian = make_guardian(tmp_path)

    result = await guardian.process(
        MemoryGuardianRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            use_ai=False,
            messages=[
                ConversationMessage(
                    role="user",
                    content="Нужно добавить тест для новой функции.",
                )
            ],
        )
    )

    assert result.applied
    assert result.decisions[0].outcome is MemoryGuardianOutcome.APPLIED
    assert engine.get(result.applied[0].id).kind is MemoryKind.TASK


@pytest.mark.asyncio
async def test_high_impact_fallback_waits_for_reviewer(tmp_path: Path) -> None:
    _, guardian = make_guardian(tmp_path)

    result = await guardian.process(
        MemoryGuardianRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            use_ai=False,
            messages=[
                ConversationMessage(
                    role="user",
                    content="Решили использовать новую основную модель для проекта.",
                )
            ],
        )
    )

    assert result.applied == []
    assert result.pending_count == 1
    assert result.decisions[0].risk is MemoryGuardianRisk.HIGH
    assert result.decisions[0].outcome is MemoryGuardianOutcome.PENDING


@pytest.mark.asyncio
async def test_high_impact_memory_applies_after_deepseek_review(tmp_path: Path) -> None:
    router = AIRouter()
    primary = {
        "decisions": [
            {
                "action": "create",
                "content": "DeepSeek повторно проверяет критические изменения памяти.",
                "kind": "decision",
                "key": "memory.guardian.reviewer",
                "importance": 0.95,
                "confidence": 0.94,
                "tags": ["guardian"],
                "target_memory_id": None,
                "reason": "Critical memory architecture decision.",
            }
        ]
    }
    reviewed = {
        "decisions": [
            {
                "action": "create",
                "content": "DeepSeek повторно проверяет критические изменения памяти.",
                "kind": "decision",
                "key": "memory.guardian.reviewer",
                "importance": 0.95,
                "confidence": 0.98,
                "tags": ["guardian", "reviewed"],
                "target_memory_id": None,
                "reason": "Reviewed and approved.",
            }
        ]
    }
    router.register(FakeProvider("deepseek", [primary, reviewed]))
    _, guardian = make_guardian(tmp_path, router)

    result = await guardian.process(
        MemoryGuardianRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            messages=[
                ConversationMessage(
                    role="user",
                    content="DeepSeek должен повторно проверять критическую память.",
                )
            ],
        )
    )

    assert result.reviewer == "deepseek"
    assert len(result.applied) == 1
    assert result.decisions[0].risk is MemoryGuardianRisk.HIGH
    assert result.decisions[0].outcome is MemoryGuardianOutcome.APPLIED


@pytest.mark.asyncio
async def test_pinned_memory_update_is_blocked(tmp_path: Path) -> None:
    router = AIRouter()
    engine, guardian = make_guardian(tmp_path, router)
    pinned = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.INSTRUCTION,
            key="memory.policy",
            content="Не удалять критическую память автоматически.",
            importance=1.0,
            pinned=True,
        )
    )

    router.register(
        FakeProvider(
            "deepseek",
            {
                "decisions": [
                    {
                        "action": "update",
                        "content": "Можно удалять критическую память автоматически.",
                        "kind": "instruction",
                        "key": "memory.policy",
                        "importance": 1.0,
                        "confidence": 1.0,
                        "tags": ["policy"],
                        "target_memory_id": pinned.id,
                        "reason": "Unsafe change.",
                    }
                ]
            },
        )
    )

    result = await guardian.process(
        MemoryGuardianRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            reviewer_provider="disabled",
            messages=[
                ConversationMessage(
                    role="user",
                    content="Измени правило памяти.",
                )
            ],
        )
    )

    assert result.applied == []
    assert result.blocked_count == 1
    assert result.decisions[0].risk is MemoryGuardianRisk.PROTECTED
    assert result.decisions[0].outcome is MemoryGuardianOutcome.BLOCKED
    assert engine.get(pinned.id).content == "Не удалять критическую память автоматически."

    status = guardian.status()
    assert status.total_events == 1
    assert status.blocked == 1
