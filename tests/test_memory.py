from pathlib import Path

import pytest

from tooru.chat.pipeline import route_user_memory
from tooru.memory.models import (
    MemoryCreate,
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
