from pathlib import Path

from tooru.memory.models import MemoryCreate, MemoryScope, MemorySearch
from tooru.memory.store import SQLiteMemoryStore


def test_personal_and_project_memory_are_isolated(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    store.initialize()

    store.add(
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            key="assistant_language",
            content="Отвечать пользователю на русском языке.",
        )
    )
    store.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            key="ai_primary",
            content="Основная модель проекта: DeepSeek V4 Flash.",
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
