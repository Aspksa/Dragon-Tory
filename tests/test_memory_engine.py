from pathlib import Path

from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.models import (
    ConversationMessage,
    MemoryConsolidateRequest,
    MemoryCreate,
    MemoryExtractRequest,
    MemoryKind,
    MemoryLinkType,
    MemoryScope,
    MemorySearch,
)
from tooru.memory.store import SQLiteMemoryStore


def make_engine(tmp_path: Path) -> MemoryEngine:
    engine = MemoryEngine(
        store=SQLiteMemoryStore(tmp_path / "memory.sqlite3"),
        embedder=HashEmbeddingProvider(128),
        related_threshold=0.65,
    )
    engine.initialize()
    return engine


def test_duplicate_memory_returns_existing_item(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    memory = MemoryCreate(
        scope=MemoryScope.PERSONAL,
        kind=MemoryKind.FACT,
        content="Ноутбук имеет 16 ГБ оперативной памяти.",
    )

    first = engine.add(memory)
    second = engine.add(memory)

    assert first.id == second.id


def test_same_key_creates_contradiction_link(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    first = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.DECISION,
            key="primary_model",
            content="Основная модель — Model A.",
        )
    )
    second = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.DECISION,
            key="primary_model",
            content="Основная модель — Model B.",
        )
    )

    links = engine.links_for(second.id, MemoryLinkType.CONTRADICTS)

    assert any(link.target_id == first.id for link in links)


def test_hybrid_recall_prefers_relevant_memory(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.DECISION,
            content="Для проекта используем Claude и DeepSeek.",
            importance=1.0,
        )
    )
    engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.NOTE,
            content="Белый фон интерфейса.",
            importance=0.4,
        )
    )

    hits = engine.recall(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="какие модели ИИ используются",
            limit=2,
        )
    )

    assert hits
    assert "Claude" in hits[0].memory.content


def test_conversation_extraction_and_consolidation(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)

    result = engine.extract(
        MemoryExtractRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            messages=[
                ConversationMessage(
                    role="user",
                    content=(
                        "Решили использовать DeepSeek как основную модель. "
                        "Нужно добавить сильную память."
                    ),
                )
            ],
        )
    )

    assert len(result.saved) >= 1

    engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Проект называется Dragon Tory.",
            importance=0.8,
        )
    )

    consolidated = engine.consolidate(
        MemoryConsolidateRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
        )
    )

    assert consolidated.memory is not None
    assert consolidated.memory.kind is MemoryKind.SUMMARY
    assert consolidated.source_ids
