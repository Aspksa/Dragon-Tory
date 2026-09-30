import sqlite3
from pathlib import Path

from tooru.memory.models import MemoryKind, MemoryStatus
from tooru.memory.store import SQLiteMemoryStore


def test_legacy_v1_database_migrates_without_losing_memory(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_items (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                project_id TEXT,
                memory_key TEXT,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memory_items (
                id, scope, project_id, memory_key, content,
                source, confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                "personal",
                None,
                "language",
                "Отвечать на русском языке.",
                "user",
                1.0,
                "2026-09-01T00:00:00+00:00",
                "2026-09-01T00:00:00+00:00",
            ),
        )

    store = SQLiteMemoryStore(db_path)
    store.initialize()

    item = store.get("legacy-1")
    assert item.content == "Отвечать на русском языке."
    assert item.kind is MemoryKind.NOTE
    assert item.status is MemoryStatus.ACTIVE
    assert item.revision == 1
    assert item.pinned is False

    with sqlite3.connect(db_path) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal"
