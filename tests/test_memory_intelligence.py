import json
from pathlib import Path

import pytest

from tooru.ai.base import AIRequest, AIResponse
from tooru.ai.router import AIRouter
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import (
    ConversationMessage,
    MemoryCreate,
    MemoryIntelligenceAction,
    MemoryIntelligenceRequest,
    MemoryKind,
    MemoryScope,
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


def make_engine(tmp_path: Path) -> MemoryEngine:
    engine = MemoryEngine(
        SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        HashEmbeddingProvider(128),
    )
    engine.initialize()
    return engine


@pytest.mark.asyncio
async def test_heuristic_fallback_saves_durable_decision(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    intelligence = MemoryIntelligence(
        engine,
        AIRouter(),
        IntelligenceConfig(),
    )

    result = await intelligence.process(
        MemoryIntelligenceRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            messages=[
                ConversationMessage(
                    role="user",
                    content="Решили использовать сильную проектную память.",
                )
            ],
        )
    )

    assert result.used_fallback is True
    assert result.applied
    assert result.applied[0].kind is MemoryKind.DECISION


@pytest.mark.asyncio
async def test_intelligence_context_lookup_does_not_reinforce_memory(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path)
    existing = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Dragon Tory использует сильную память.",
            importance=0.9,
        )
    )
    intelligence = MemoryIntelligence(
        engine,
        AIRouter(),
        IntelligenceConfig(),
    )

    await intelligence.process(
        MemoryIntelligenceRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            use_ai=False,
            auto_apply=False,
            messages=[
                ConversationMessage(
                    role="user",
                    content="Расскажи про память Dragon Tory.",
                )
            ],
        )
    )

    after = engine.get(existing.id)
    assert after.access_count == 0


@pytest.mark.asyncio
async def test_ai_can_create_memory_and_claude_can_review(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    router = AIRouter()
    primary = {
        "decisions": [
            {
                "action": "create",
                "content": "Проект использует DeepSeek как основную модель.",
                "kind": "decision",
                "key": "project.primary_model",
                "importance": 0.95,
                "confidence": 0.93,
                "tags": ["ai", "architecture"],
                "target_memory_id": None,
                "reason": "Long-term architecture decision.",
            }
        ]
    }
    reviewed = {
        "decisions": [
            {
                "action": "create",
                "content": "Проект использует DeepSeek как основную модель и Claude как экспертную.",
                "kind": "decision",
                "key": "project.ai_models",
                "importance": 0.98,
                "confidence": 0.97,
                "tags": ["ai", "architecture", "reviewed"],
                "target_memory_id": None,
                "reason": "Reviewer made the durable decision more complete.",
            }
        ]
    }
    router.register(FakeProvider("deepseek", primary))
    router.register(FakeProvider("claude", reviewed))
    intelligence = MemoryIntelligence(
        engine,
        router,
        IntelligenceConfig(
            primary_provider="deepseek",
            reviewer_provider="claude",
        ),
    )

    result = await intelligence.process(
        MemoryIntelligenceRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            messages=[
                ConversationMessage(
                    role="user",
                    content="Для проекта используем DeepSeek и Claude.",
                )
            ],
        )
    )

    assert result.analyzer == "deepseek"
    assert result.reviewer == "claude"
    assert result.used_fallback is False
    assert len(result.applied) == 1
    assert result.applied[0].key == "project.ai_models"


@pytest.mark.asyncio
async def test_ai_update_cannot_escape_active_project_scope(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    other = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="other-project",
            kind=MemoryKind.FACT,
            key="project.name",
            content="Другой проект.",
        )
    )
    router = AIRouter()
    router.register(
        FakeProvider(
            "deepseek",
            {
                "decisions": [
                    {
                        "action": "update",
                        "content": "Попытка изменить чужой проект.",
                        "kind": "fact",
                        "key": "project.name",
                        "importance": 1.0,
                        "confidence": 1.0,
                        "tags": [],
                        "target_memory_id": other.id,
                        "reason": "Bad target.",
                    }
                ]
            },
        )
    )
    intelligence = MemoryIntelligence(
        engine,
        router,
        IntelligenceConfig(primary_provider="deepseek"),
    )

    result = await intelligence.process(
        MemoryIntelligenceRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            reviewer_provider="disabled",
            messages=[
                ConversationMessage(
                    role="user",
                    content="Обнови название проекта.",
                )
            ],
        )
    )

    assert result.decisions[0].action is MemoryIntelligenceAction.CREATE
    unchanged = engine.get(other.id)
    assert unchanged.content == "Другой проект."
