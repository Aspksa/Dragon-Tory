import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tooru.memory.models import (
    MemoryCreate,
    MemoryDelete,
    MemoryItem,
    MemoryKind,
    MemoryScope,
    MemorySearch,
    MemorySyncRequest,
    MemorySyncResponse,
    MemoryUpdate,
)


class MemoryNotFoundError(LookupError):
    pass


class MemoryConflictError(RuntimeError):
    pass


class SQLiteMemoryStore:
    """Persistent, versioned memory with personal/project isolation and mobile sync."""

    SELECT_COLUMNS = """
        id, owner_id, scope, project_id, kind, memory_key, content,
        source, source_ref, confidence, importance, tags_json,
        device_id, session_id, client_mutation_id, revision,
        created_at, updated_at, deleted_at
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL DEFAULT 'local-user',
                    scope TEXT NOT NULL CHECK(scope IN ('personal', 'project')),
                    project_id TEXT,
                    kind TEXT NOT NULL DEFAULT 'note',
                    memory_key TEXT,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_ref TEXT,
                    confidence REAL NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    device_id TEXT,
                    session_id TEXT,
                    client_mutation_id TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    CHECK(
                        (scope = 'personal' AND project_id IS NULL)
                        OR
                        (scope = 'project' AND project_id IS NOT NULL)
                    )
                )
                """
            )
            self._migrate_legacy_schema(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_owner_scope_project
                ON memory_items(owner_id, scope, project_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_retrieval
                ON memory_items(
                    owner_id, scope, project_id, importance DESC,
                    confidence DESC, updated_at DESC
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_client_mutation
                ON memory_items(owner_id, client_mutation_id)
                WHERE client_mutation_id IS NOT NULL
                """
            )

    def add(self, memory: MemoryCreate) -> MemoryItem:
        if memory.client_mutation_id:
            existing = self._get_by_mutation_id(
                memory.owner_id, memory.client_mutation_id
            )
            if existing is not None:
                return existing

        now = self._now()
        item = MemoryItem(
            id=str(uuid4()),
            revision=1,
            created_at=now,
            updated_at=now,
            deleted_at=None,
            **memory.model_dump(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    id, owner_id, scope, project_id, kind, memory_key, content,
                    source, source_ref, confidence, importance, tags_json,
                    device_id, session_id, client_mutation_id, revision,
                    created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.owner_id,
                    item.scope.value,
                    item.project_id,
                    item.kind.value,
                    item.key,
                    item.content,
                    item.source,
                    item.source_ref,
                    item.confidence,
                    item.importance,
                    self._dump_tags(item.tags),
                    item.device_id,
                    item.session_id,
                    item.client_mutation_id,
                    item.revision,
                    item.created_at,
                    item.updated_at,
                    item.deleted_at,
                ),
            )
        return item

    def get(
        self, memory_id: str, owner_id: str = "local-user", include_deleted: bool = False
    ) -> MemoryItem:
        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE id = ? AND owner_id = ? {deleted_filter}
                """,
                (memory_id, owner_id),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError(memory_id)
        return self._row_to_item(row)

    def update(
        self, memory_id: str, owner_id: str, payload: MemoryUpdate
    ) -> MemoryItem:
        current = self.get(memory_id, owner_id)
        if current.revision != payload.expected_revision:
            raise MemoryConflictError(
                f"revision conflict: current={current.revision}, "
                f"expected={payload.expected_revision}"
            )

        changes = payload.model_dump(exclude_unset=True)
        changes.pop("expected_revision", None)

        content = changes.get("content", current.content)
        kind = changes.get("kind", current.kind)
        key = changes.get("key", current.key)
        source = changes.get("source", current.source)
        source_ref = changes.get("source_ref", current.source_ref)
        confidence = changes.get("confidence", current.confidence)
        importance = changes.get("importance", current.importance)
        tags = changes.get("tags", current.tags)
        device_id = changes.get("device_id", current.device_id)
        session_id = changes.get("session_id", current.session_id)
        updated_at = self._now()
        next_revision = current.revision + 1

        if isinstance(kind, MemoryKind):
            kind = kind.value

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET kind = ?, memory_key = ?, content = ?, source = ?,
                    source_ref = ?, confidence = ?, importance = ?,
                    tags_json = ?, device_id = ?, session_id = ?,
                    revision = ?, updated_at = ?
                WHERE id = ? AND owner_id = ? AND revision = ?
                  AND deleted_at IS NULL
                """,
                (
                    kind,
                    key,
                    content,
                    source,
                    source_ref,
                    confidence,
                    importance,
                    self._dump_tags(tags),
                    device_id,
                    session_id,
                    next_revision,
                    updated_at,
                    memory_id,
                    owner_id,
                    current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryConflictError("memory changed during update")

        return self.get(memory_id, owner_id)

    def delete(self, memory_id: str, payload: MemoryDelete) -> MemoryItem:
        current = self.get(memory_id, payload.owner_id)
        if current.revision != payload.expected_revision:
            raise MemoryConflictError(
                f"revision conflict: current={current.revision}, "
                f"expected={payload.expected_revision}"
            )

        now = self._now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET deleted_at = ?, updated_at = ?, device_id = ?, revision = revision + 1
                WHERE id = ? AND owner_id = ? AND revision = ?
                  AND deleted_at IS NULL
                """,
                (
                    now,
                    now,
                    payload.device_id,
                    memory_id,
                    payload.owner_id,
                    current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryConflictError("memory changed during delete")

        return self.get(memory_id, payload.owner_id, include_deleted=True)

    def search(self, request: MemorySearch) -> list[MemoryItem]:
        params: list[object] = [request.owner_id, request.scope.value]
        clauses = [
            "owner_id = ?",
            "scope = ?",
            "deleted_at IS NULL",
        ]

        if request.scope is MemoryScope.PROJECT:
            clauses.append("project_id = ?")
            params.append(request.project_id)
        else:
            clauses.append("project_id IS NULL")

        clauses.append("(content LIKE ? OR COALESCE(memory_key, '') LIKE ?)")
        like = f"%{request.query}%"
        params.extend([like, like])

        if request.kind is not None:
            clauses.append("kind = ?")
            params.append(request.kind.value)

        clauses.append("importance >= ?")
        params.append(request.min_importance)

        for tag in request.tags:
            clauses.append("tags_json LIKE ?")
            params.append(f'%"{tag}"%')

        params.append(request.limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                ORDER BY importance DESC, confidence DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [self._row_to_item(row) for row in rows]

    def sync(self, request: MemorySyncRequest) -> MemorySyncResponse:
        params: list[object] = [request.owner_id, request.scope.value]
        clauses = ["owner_id = ?", "scope = ?"]

        if request.scope is MemoryScope.PROJECT:
            clauses.append("project_id = ?")
            params.append(request.project_id)
        else:
            clauses.append("project_id IS NULL")

        if request.cursor_updated_at:
            if request.cursor_id:
                clauses.append(
                    "(updated_at > ? OR (updated_at = ? AND id > ?))"
                )
                params.extend(
                    [
                        request.cursor_updated_at,
                        request.cursor_updated_at,
                        request.cursor_id,
                    ]
                )
            else:
                clauses.append("updated_at > ?")
                params.append(request.cursor_updated_at)

        params.append(request.limit + 1)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()

        has_more = len(rows) > request.limit
        visible_rows = rows[: request.limit]
        items = [self._row_to_item(row) for row in visible_rows]

        if items:
            next_updated_at = items[-1].updated_at
            next_id = items[-1].id
        else:
            next_updated_at = request.cursor_updated_at
            next_id = request.cursor_id

        return MemorySyncResponse(
            items=items,
            next_updated_at=next_updated_at,
            next_id=next_id,
            has_more=has_more,
        )

    def _get_by_mutation_id(
        self, owner_id: str, client_mutation_id: str
    ) -> MemoryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE owner_id = ? AND client_mutation_id = ?
                """,
                (owner_id, client_mutation_id),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()
        }
        migrations = {
            "owner_id": "TEXT NOT NULL DEFAULT 'local-user'",
            "kind": "TEXT NOT NULL DEFAULT 'note'",
            "source_ref": "TEXT",
            "importance": "REAL NOT NULL DEFAULT 0.5",
            "tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "device_id": "TEXT",
            "session_id": "TEXT",
            "client_mutation_id": "TEXT",
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "deleted_at": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE memory_items ADD COLUMN {column} {definition}"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _dump_tags(tags: list[str]) -> str:
        normalized = sorted({tag.strip() for tag in tags if tag.strip()})
        return json.dumps(normalized, ensure_ascii=False)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            owner_id=row["owner_id"],
            scope=MemoryScope(row["scope"]),
            project_id=row["project_id"],
            kind=MemoryKind(row["kind"]),
            key=row["memory_key"],
            content=row["content"],
            source=row["source"],
            source_ref=row["source_ref"],
            confidence=row["confidence"],
            importance=row["importance"],
            tags=json.loads(row["tags_json"] or "[]"),
            device_id=row["device_id"],
            session_id=row["session_id"],
            client_mutation_id=row["client_mutation_id"],
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )
