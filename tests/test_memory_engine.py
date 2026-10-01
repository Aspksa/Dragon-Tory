from datetime import UTC, datetime, timedelta
from pathlib import Path

from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.models import (
    ConversationMessage,
    MemoryConsolidateRequest,
    MemoryContextRequest,
    MemoryCreate,
    MemoryExtractRequest,
    MemoryFeedback,
    MemoryKind,
    MemoryLinkType,
    MemoryScope,
    MemorySearch,
    MemoryStatus,
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


def test_same_key_supersedes_old_memory(tmp_path: Path) -> None:
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
    links = engine.links_for(second.id, MemoryLinkType.SUPERSEDES)
    old = engine.get(first.id)
    assert any(link.target_id == first.id for link in links)
    assert old.status is MemoryStatus.SUPERSEDED


def test_hybrid_recall_tracks_usage_and_feedback(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    important = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.DECISION,
            content="Для проекта используем DeepSeek V4 Flash.",
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
    assert "DeepSeek V4 Flash" in hits[0].memory.content

    touched = engine.get(important.id)
    assert touched.access_count >= 1

    reinforced = engine.feedback(
        important.id,
        MemoryFeedback(helpful=True, strength=1.0),
    )
    assert reinforced.helpful_count == 1
    assert reinforced.reinforced_at is not None


def test_history_is_written_for_updates_and_feedback(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    item = engine.add(
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            kind=MemoryKind.PREFERENCE,
            key="ui.theme",
            content="Светлая тема.",
        )
    )
    engine.feedback(item.id, MemoryFeedback(helpful=True))
    history = engine.history(item.id, item.owner_id)
    assert len(history) >= 2
    assert history[0].revision > history[-1].revision


def test_expired_memory_is_archived_by_maintenance(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    expired = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    item = engine.add(
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            kind=MemoryKind.NOTE,
            content="Временная заметка.",
            expires_at=expired,
        )
    )

    report = engine.maintain(
        archive_after_days=180,
        archive_max_importance=0.3,
        archive_max_access_count=1,
        auto_consolidate_threshold=100,
        consolidate_cooldown_hours=24,
    )

    archived = engine.get(item.id)
    assert report.expired_archived == 1
    assert archived.status is MemoryStatus.ARCHIVED


def test_recall_recovers_old_low_priority_lexical_memory(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    target = engine.store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.NOTE,
            content="Редкая метка северный-альбатрос относится к старому решению.",
            importance=0.05,
            confidence=0.5,
        )
    )
    for index in range(520):
        engine.store.add(
            MemoryCreate(
                scope=MemoryScope.PROJECT,
                project_id="dragon-tory",
                kind=MemoryKind.NOTE,
                content=f"Свежая высокоприоритетная запись номер {index}.",
                importance=1.0,
                confidence=1.0,
            )
        )

    hits = engine.recall(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="северный альбатрос",
            limit=5,
        ),
        track_usage=False,
    )

    assert target.id in {hit.memory.id for hit in hits}


def test_context_pack_keeps_projects_isolated_and_includes_pinned_personal(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path)
    pinned = engine.add(
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            kind=MemoryKind.INSTRUCTION,
            content="Всегда отвечать на русском языке.",
            importance=1.0,
            pinned=True,
        )
    )
    engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.DECISION,
            content="Dragon Tory использует DeepSeek V4 Flash.",
            importance=1.0,
        )
    )
    engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="other-project",
            kind=MemoryKind.DECISION,
            content="Другой проект использует Model X.",
            importance=1.0,
        )
    )

    pack = engine.context_pack(
        MemoryContextRequest(
            query="Какие модели использует проект?",
            project_id="dragon-tory",
        )
    )

    assert any(item.id == pinned.id for item in pack.pinned_personal)
    assert "Dragon Tory" in pack.rendered_context
    assert "Другой проект" not in pack.rendered_context
    assert "PERSONAL_MEMORY" in pack.rendered_context
    assert "PROJECT_MEMORY:dragon-tory" in pack.rendered_context


def test_extractor_recognizes_goal_and_episode(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    result = engine.extract(
        MemoryExtractRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            auto_save=False,
            messages=[
                ConversationMessage(
                    role="user",
                    content=(
                        "Моя цель — сделать Тоору сильным помощником. "
                        "Сегодня сделали новую систему памяти."
                    ),
                )
            ],
        )
    )
    kinds = {item.kind for item in result.candidates}
    assert MemoryKind.GOAL in kinds
    assert MemoryKind.EPISODE in kinds


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
