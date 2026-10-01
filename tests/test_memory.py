from pathlib import Path

import pytest

from tooru.chat.pipeline import route_user_memory
from tooru.memory.models import (
    MemoryCreate,
    MemoryEvidenceCreate,
    MemoryKind,
    MemoryScope,
    MemorySearch,
    MemorySyncRequest,
    MemoryUpdate,
)
from tooru.memory.store import MemoryConflictError, SQLiteMemoryStore


def make_store(tmp_path: Path) -> SQLiteMemoryStore:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    store.initialize()
    return store


def test_personal_and_project_memory_are_isolated(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    store.add(
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            kind=MemoryKind.PREFERENCE,
            key="assistant_language",
            content="Отвечать пользователю на русском языке.",
            importance=0.9,
        )
    )
    store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.DECISION,
            key="ai_primary",
            content="Основная модель проекта: DeepSeek V4 Flash.",
            importance=1.0,
        )
    )

    personal = store.search(
        MemorySearch(scope=MemoryScope.PERSONAL, query="модель")
    )
    project = store.search(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="модель",
        )
    )

    assert personal == []
    assert len(project) == 1
    assert project[0].project_id == "dragon-tory"
    assert project[0].kind is MemoryKind.DECISION


def test_fts_lexical_search_is_scope_isolated_and_tracks_updates(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    item = store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.NOTE,
            content="Уникальная диагностическая метка альбатрос.",
            importance=0.2,
        )
    )
    store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="other-project",
            kind=MemoryKind.NOTE,
            content="Альбатрос относится к другому проекту.",
            importance=1.0,
        )
    )

    found = store.lexical_candidates(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="альбатрос",
        ),
        limit=20,
    )
    assert [memory.id for memory in found] == [item.id]

    store.update(
        item.id,
        item.owner_id,
        MemoryUpdate(
            content="Уникальная диагностическая метка феникс.",
            expected_revision=item.revision,
        ),
    )
    assert store.lexical_candidates(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="альбатрос",
        )
    ) == []
    updated = store.lexical_candidates(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="феникс",
        )
    )
    assert len(updated) == 1
    assert updated[0].id == item.id


def test_mobile_retry_is_idempotent(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    payload = MemoryCreate(
        scope=MemoryScope.PERSONAL,
        kind=MemoryKind.FACT,
        content="Запись создана с телефона.",
        device_id="android-phone",
        client_mutation_id="mobile-op-001",
    )

    first = store.add(payload)
    second = store.add(payload)

    assert first.id == second.id
    assert first.revision == second.revision == 1


def test_revision_conflict_prevents_lost_update(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    item = store.add(
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            kind=MemoryKind.NOTE,
            content="Первая версия",
        )
    )

    updated = store.update(
        item.id,
        item.owner_id,
        MemoryUpdate(content="Вторая версия", expected_revision=1),
    )
    assert updated.revision == 2

    with pytest.raises(MemoryConflictError):
        store.update(
            item.id,
            item.owner_id,
            MemoryUpdate(content="Устаревшая запись", expected_revision=1),
        )


def test_sync_returns_changes_for_one_project_only(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            content="Память Dragon Tory",
            device_id="pc",
        )
    )
    store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="other-project",
            content="Память другого проекта",
            device_id="phone",
        )
    )

    result = store.sync(
        MemorySyncRequest(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
        )
    )

    assert len(result.items) == 1
    assert result.items[0].project_id == "dragon-tory"


def test_memory_health_report_checks_real_sqlite_structure(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    health = store.health_report(deep=True)

    assert health["status"] == "ok"
    assert health["integrity"].casefold() == "ok"
    assert health["foreign_key_errors"] == 0
    assert health["missing_tables"] == []
    assert health["invalid_scope_rows"] == 0
    assert health["orphan_vectors"] == 0
    assert health["orphan_links"] == 0
    assert health["orphan_history"] == 0
    assert health["fts_available"] is True
    assert health["fts_entries"] == 0


def test_chat_memory_routing_separates_personal_and_project() -> None:
    routed = route_user_memory(
        "У меня ноутбук с 16 ГБ памяти. "
        "В проект Тоору надо добавить новый модуль договоров."
    )

    assert [item.content for item in routed[MemoryScope.PERSONAL]] == [
        "У меня ноутбук с 16 ГБ памяти."
    ]
    assert [item.content for item in routed[MemoryScope.PROJECT]] == [
        "В проект Тоору надо добавить новый модуль договоров."
    ]


def test_chat_memory_routing_keeps_project_preference_in_project() -> None:
    routed = route_user_memory(
        "Мне нравится белый интерфейс проекта Тоору."
    )

    assert routed[MemoryScope.PERSONAL] == []
    assert len(routed[MemoryScope.PROJECT]) == 1

def test_temporal_memory_and_evidence_persist(tmp_path: Path) -> None:
    path = tmp_path / "temporal.sqlite3"
    store = SQLiteMemoryStore(path)
    store.initialize()
    item = store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Петров назначен водителем автомобиля.",
            source="service-memo",
            source_ref="document:memo-1",
            observed_at="2026-10-01T10:00:00+00:00",
            event_at="2026-10-01T09:00:00+00:00",
            valid_from="2026-10-01T00:00:00+00:00",
            valid_to="2026-12-31T23:59:59+00:00",
        )
    )
    evidence = store.add_evidence(
        item.id,
        MemoryEvidenceCreate(
            source_type="document",
            source_ref="document:memo-1",
            document_id="memo-1",
            page=2,
            table_ref="Таблица 1",
            cell_ref="B4:D4",
            chunk_no=7,
            evidence_hash="abc123",
            excerpt="Назначить Петрова водителем.",
            extraction_method="service-memo-parser",
            confidence=0.98,
        ),
    )

    reopened = SQLiteMemoryStore(path)
    reopened.initialize()
    loaded = reopened.get(item.id)
    proof = reopened.evidence_for(item.id)

    assert loaded.event_at == "2026-10-01T09:00:00+00:00"
    assert loaded.valid_from == "2026-10-01T00:00:00+00:00"
    assert loaded.valid_to == "2026-12-31T23:59:59+00:00"
    assert proof[0].id == evidence.id
    assert proof[0].document_id == "memo-1"
    assert proof[0].page == 2
    assert proof[0].table_ref == "Таблица 1"
    assert proof[0].cell_ref == "B4:D4"
    assert proof[0].chunk_no == 7
    assert proof[0].evidence_hash == "abc123"
    assert reopened.health_report(deep=True)["orphan_evidence"] == 0


def test_temporal_memory_rejects_reversed_interval() -> None:
    with pytest.raises(ValueError):
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            content="Некорректный период.",
            valid_from="2026-12-31T00:00:00+00:00",
            valid_to="2026-01-01T00:00:00+00:00",
        )

