import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tooru.memory.models import MemoryCreate, MemoryItem, MemoryScope, MemorySearch


class SQLiteMemoryStore:
    """Persistent memory with hard isolation between personal and project scopes."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL CHECK(scope IN ('personal', 'project')),
                    project_id TEXT,
                    memory_key TEXT,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(
                        (scope = 'personal' AND project_id IS NULL)
                        OR
                        (scope = 'project' AND project_id IS NOT NULL)
                    )
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_scope_project
                ON memory_items(scope, project_id, updated_at DESC)
                """
            )

    def add(self, memory: MemoryCreate) -> MemoryItem:
        now = datetime.now(UTC).isoformat()
        item = MemoryItem(
            id=str(uuid4()),
            created_at=now,
            updated_at=now,
            **memory.model_dump(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    id, scope, project_id, memory_key, content,
                    source, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.scope.value,
                    item.project_id,
                    item.key,
                    item.content,
                    item.source,
                    item.confidence,
                    item.created_at,
                    item.updated_at,
                ),
            )
        return item

    def search(self, request: MemorySearch) -> list[MemoryItem]:
        like = f"%{request.query}%"
        params: list[object] = [request.scope.value]
        project_filter = "project_id IS NULL"

        if request.scope is MemoryScope.PROJECT:
            project_filter = "project_id = ?"
            params.append(request.project_id)

        params.extend([like, like, request.limit])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, scope, project_id, memory_key, content,
                       source, confidence, created_at, updated_at
                FROM memory_items
                WHERE scope = ?
                  AND {project_filter}
                  AND (content LIKE ? OR COALESCE(memory_key, '') LIKE ?)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [self._row_to_item(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            scope=MemoryScope(row["scope"]),
            project_id=row["project_id"],
            key=row["memory_key"],
            content=row["content"],
            source=row["source"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
