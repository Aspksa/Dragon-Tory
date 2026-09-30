from pathlib import Path

import pytest

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
