import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from tooru.memory.models import (
    MemoryCreate,
    MemoryDelete,
    MemoryFeedback,
    MemoryItem,
    MemoryKind,
    MemoryLink,
    MemoryLinkType,
    MemoryRevision,
    MemoryScope,
    MemorySearch,
    MemoryStatus,
    MemorySyncRequest,
    MemorySyncResponse,
    MemoryUpdate,
)


class MemoryNotFoundError(LookupError):
    pass


class MemoryConflictError(RuntimeError):
    pass


class SQLiteMemoryStore:
    SELECT_COLUMNS = """
        id, owner_id, scope, project_id, kind, memory_key, content,
        source, source_ref, confidence, importance, tags_json, pinned,
        expires_at, status, access_count, helpful_count, unhelpful_count,
        last_accessed_at, reinforced_at, archived_at,
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
                    pinned INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    access_count INTEGER NOT NULL DEFAULT 0,
                    helpful_count INTEGER NOT NULL DEFAULT 0,
                    unhelpful_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT,
                    reinforced_at TEXT,
                    archived_at TEXT,
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
                CREATE TABLE IF NOT EXISTS memory_vectors (
                    memory_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_links (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_id, target_id, relation),
                    FOREIGN KEY(source_id) REFERENCES memory_items(id) ON DELETE CASCADE,
                    FOREIGN KEY(target_id) REFERENCES memory_items(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_history (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(memory_id, revision),
                    FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_maintenance_runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    report_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_owner_scope_project
                ON memory_items(owner_id, scope, project_id, status, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_retrieval
                ON memory_items(
                    owner_id, scope, project_id, status, importance DESC,
                    confidence DESC, access_count DESC, updated_at DESC
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
            status=MemoryStatus.ACTIVE,
            revision=1,
            access_count=0,
            helpful_count=0,
            unhelpful_count=0,
            last_accessed_at=None,
            reinforced_at=None,
            archived_at=None,
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
                    source, source_ref, confidence, importance, tags_json, pinned,
                    expires_at, status, access_count, helpful_count, unhelpful_count,
                    last_accessed_at, reinforced_at, archived_at,
                    device_id, session_id, client_mutation_id, revision,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._item_values(item),
            )
            self._record_history(conn, item, "created")
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
        kind = changes.get("kind", current.kind)
        if isinstance(kind, MemoryKind):
            kind = kind.value

        values = {
            "content": changes.get("content", current.content),
            "kind": kind,
            "key": changes.get("key", current.key),
            "source": changes.get("source", current.source),
            "source_ref": changes.get("source_ref", current.source_ref),
            "confidence": changes.get("confidence", current.confidence),
            "importance": changes.get("importance", current.importance),
            "tags": changes.get("tags", current.tags),
            "pinned": changes.get("pinned", current.pinned),
            "expires_at": changes.get("expires_at", current.expires_at),
            "device_id": changes.get("device_id", current.device_id),
            "session_id": changes.get("session_id", current.session_id),
        }
        now = self._now()
        next_revision = current.revision + 1

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET kind = ?, memory_key = ?, content = ?, source = ?,
                    source_ref = ?, confidence = ?, importance = ?,
                    tags_json = ?, pinned = ?, expires_at = ?,
                    device_id = ?, session_id = ?,
                    revision = ?, updated_at = ?
                WHERE id = ? AND owner_id = ? AND revision = ?
                  AND deleted_at IS NULL
                """,
                (
                    values["kind"], values["key"], values["content"],
                    values["source"], values["source_ref"], values["confidence"],
                    values["importance"], self._dump_tags(values["tags"]),
                    int(values["pinned"]), values["expires_at"],
                    values["device_id"], values["session_id"], next_revision,
                    now, memory_id, owner_id, current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryConflictError("memory changed during update")
            item = self._get_in_connection(conn, memory_id, owner_id)
            self._record_history(conn, item, "updated")
        return item

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
                SET deleted_at = ?, updated_at = ?, device_id = ?,
                    revision = revision + 1
                WHERE id = ? AND owner_id = ? AND revision = ?
                  AND deleted_at IS NULL
                """,
                (
                    now, now, payload.device_id, memory_id,
                    payload.owner_id, current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryConflictError("memory changed during delete")
            item = self._get_in_connection(
                conn, memory_id, payload.owner_id, include_deleted=True
            )
            self._record_history(conn, item, "deleted")
        return item

    def mark_superseded(self, memory_id: str, owner_id: str) -> MemoryItem:
        current = self.get(memory_id, owner_id)
        if current.status is MemoryStatus.SUPERSEDED:
            return current
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_items
                SET status = 'superseded', archived_at = ?, updated_at = ?,
                    revision = revision + 1
                WHERE id = ? AND owner_id = ? AND deleted_at IS NULL
                """,
                (now, now, memory_id, owner_id),
            )
            item = self._get_in_connection(conn, memory_id, owner_id)
            self._record_history(conn, item, "superseded")
        return item

    def record_feedback(self, memory_id: str, feedback: MemoryFeedback) -> MemoryItem:
        self.get(memory_id, feedback.owner_id)
        now = self._now()
        column = "helpful_count" if feedback.helpful else "unhelpful_count"
        reinforcement = feedback.strength * (0.04 if feedback.helpful else -0.03)
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE memory_items
                SET {column} = {column} + 1,
                    importance = MIN(1.0, MAX(0.0, importance + ?)),
                    reinforced_at = ?, updated_at = ?,
                    revision = revision + 1
                WHERE id = ? AND owner_id = ? AND deleted_at IS NULL
                """,
                (
                    reinforcement, now, now, memory_id, feedback.owner_id
                ),
            )
            item = self._get_in_connection(conn, memory_id, feedback.owner_id)
            self._record_history(conn, item, "feedback")
        return item

    def touch_recall(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        now = self._now()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE memory_items
                SET access_count = access_count + 1,
                    last_accessed_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                [(now, memory_id) for memory_id in memory_ids],
            )

    def candidates(self, request: MemorySearch, limit: int = 500) -> list[MemoryItem]:
        params: list[object] = [request.owner_id, request.scope.value]
        clauses = ["owner_id = ?", "scope = ?", "deleted_at IS NULL"]

        if request.scope is MemoryScope.PROJECT:
            clauses.append("project_id = ?")
            params.append(request.project_id)
        else:
            clauses.append("project_id IS NULL")

        if not request.include_archived:
            clauses.append("status = 'active'")
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(self._now())

        if request.kind is not None:
            clauses.append("kind = ?")
            params.append(request.kind.value)

        clauses.append("importance >= ?")
        params.append(request.min_importance)

        for tag in request.tags:
            clauses.append("tags_json LIKE ?")
            params.append(f'%"{tag}"%')

        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                ORDER BY pinned DESC, importance DESC, confidence DESC,
                         access_count DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def pinned_items(
        self,
        owner_id: str,
        scope: MemoryScope,
        project_id: str | None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        params: list[object] = [owner_id, scope.value]
        project_clause = "project_id IS NULL"
        if scope is MemoryScope.PROJECT:
            project_clause = "project_id = ?"
            params.append(project_id)

        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE owner_id = ?
                  AND scope = ?
                  AND {project_clause}
                  AND pinned = 1
                  AND status = 'active'
                  AND deleted_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
                """,
                params[:-1] + [self._now(), params[-1]],
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def search(self, request: MemorySearch) -> list[MemoryItem]:
        query = request.query.lower()
        matches = [
            item
            for item in self.candidates(request, limit=max(request.limit * 20, 100))
            if query in item.content.lower()
            or (item.key and query in item.key.lower())
        ]
        return matches[: request.limit]

    def find_exact(self, memory: MemoryCreate) -> MemoryItem | None:
        normalized = " ".join(memory.content.lower().split())
        request = MemorySearch(
            owner_id=memory.owner_id,
            scope=memory.scope,
            project_id=memory.project_id,
            query=memory.content,
            kind=memory.kind,
            include_archived=False,
            limit=100,
        )
        for item in self.candidates(request, limit=200):
            if " ".join(item.content.lower().split()) == normalized:
                return item
        return None

    def find_same_key(self, memory: MemoryCreate) -> list[MemoryItem]:
        if not memory.key:
            return []
        params: list[object] = [
            memory.owner_id, memory.scope.value, memory.key
        ]
        project_clause = "project_id IS NULL"
        if memory.scope is MemoryScope.PROJECT:
            project_clause = "project_id = ?"
            params.append(memory.project_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE owner_id = ? AND scope = ?
                  AND memory_key = ? AND {project_clause}
                  AND status = 'active' AND deleted_at IS NULL
                ORDER BY updated_at DESC
                """,
                params,
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def upsert_vector(
        self,
        memory_id: str,
        vector: list[float],
        provider: str,
        model: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_vectors (
                    memory_id, provider, model, dimensions,
                    vector_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    dimensions = excluded.dimensions,
                    vector_json = excluded.vector_json,
                    updated_at = excluded.updated_at
                """,
                (
                    memory_id, provider, model, len(vector),
                    json.dumps(vector, separators=(",", ":")), self._now(),
                ),
            )

    def vectors_for(
        self,
        memory_ids: list[str],
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, list[float]]:
        if not memory_ids:
            return {}
        placeholders = ",".join("?" for _ in memory_ids)
        params: list[object] = list(memory_ids)
        provider_clause = ""
        if provider is not None and model is not None:
            provider_clause = "AND provider = ? AND model = ?"
            params.extend([provider, model])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT memory_id, vector_json
                FROM memory_vectors
                WHERE memory_id IN ({placeholders})
                  {provider_clause}
                """,
                params,
            ).fetchall()
        return {
            row["memory_id"]: json.loads(row["vector_json"])
            for row in rows
        }

    def stale_vector_items(
        self,
        provider: str,
        model: str,
        limit: int = 500,
    ) -> list[MemoryItem]:
        select_columns = ", ".join(
            f"m.{column.strip()}"
            for column in self.SELECT_COLUMNS.replace("\n", " ").split(",")
        )
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {select_columns}
                FROM memory_items m
                LEFT JOIN memory_vectors v ON v.memory_id = m.id
                WHERE m.deleted_at IS NULL
                  AND m.status = 'active'
                  AND (
                    v.memory_id IS NULL
                    OR v.provider != ?
                    OR v.model != ?
                  )
                ORDER BY m.updated_at DESC
                LIMIT ?
                """,
                (provider, model, limit),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def add_link(
        self,
        source_id: str,
        target_id: str,
        relation: MemoryLinkType,
        weight: float = 1.0,
    ) -> MemoryLink:
        if source_id == target_id:
            raise ValueError("memory cannot link to itself")
        now = self._now()
        link = MemoryLink(
            id=str(uuid4()),
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            weight=max(0.0, min(1.0, weight)),
            created_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_links (
                    id, source_id, target_id, relation, weight, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation)
                DO UPDATE SET weight = excluded.weight
                """,
                (
                    link.id, source_id, target_id, relation.value,
                    link.weight, link.created_at,
                ),
            )
            row = conn.execute(
                """
                SELECT id, source_id, target_id, relation, weight, created_at
                FROM memory_links
                WHERE source_id = ? AND target_id = ? AND relation = ?
                """,
                (source_id, target_id, relation.value),
            ).fetchone()
        return self._row_to_link(row)

    def links_for(
        self,
        memory_id: str,
        relation: MemoryLinkType | None = None,
    ) -> list[MemoryLink]:
        params: list[object] = [memory_id, memory_id]
        relation_clause = ""
        if relation is not None:
            relation_clause = "AND relation = ?"
            params.append(relation.value)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, source_id, target_id, relation, weight, created_at
                FROM memory_links
                WHERE (source_id = ? OR target_id = ?)
                  {relation_clause}
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        return [self._row_to_link(row) for row in rows]

    def history_for(self, memory_id: str, owner_id: str) -> list[MemoryRevision]:
        self.get(memory_id, owner_id, include_deleted=True)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_id, revision, reason, snapshot_json, created_at
                FROM memory_history
                WHERE memory_id = ?
                ORDER BY revision DESC
                """,
                (memory_id,),
            ).fetchall()
        return [
            MemoryRevision(
                memory_id=row["memory_id"],
                revision=row["revision"],
                reason=row["reason"],
                snapshot=json.loads(row["snapshot_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

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
                clauses.append("(updated_at > ? OR (updated_at = ? AND id > ?))")
                params.extend([
                    request.cursor_updated_at,
                    request.cursor_updated_at,
                    request.cursor_id,
                ])
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
        items = [self._row_to_item(row) for row in rows[: request.limit]]
        return MemorySyncResponse(
            items=items,
            next_updated_at=items[-1].updated_at if items else request.cursor_updated_at,
            next_id=items[-1].id if items else request.cursor_id,
            has_more=has_more,
        )

    def archive_expired(self) -> int:
        now = self._now()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE status = 'active'
                  AND pinned = 0
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                  AND deleted_at IS NULL
                """,
                (now,),
            ).fetchall()
            count = 0
            for row in rows:
                item = self._row_to_item(row)
                conn.execute(
                    """
                    UPDATE memory_items
                    SET status = 'archived', archived_at = ?, updated_at = ?,
                        revision = revision + 1
                    WHERE id = ?
                    """,
                    (now, now, item.id),
                )
                archived = self._get_in_connection(conn, item.id, item.owner_id)
                self._record_history(conn, archived, "expired")
                count += 1
        return count

    def archive_stale(
        self,
        older_than_days: int,
        max_importance: float,
        max_access_count: int,
        limit: int = 500,
    ) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        now = self._now()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE status = 'active'
                  AND pinned = 0
                  AND kind IN ('note', 'event', 'episode')
                  AND importance <= ?
                  AND access_count <= ?
                  AND updated_at < ?
                  AND deleted_at IS NULL
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (max_importance, max_access_count, cutoff, limit),
            ).fetchall()
            count = 0
            for row in rows:
                item = self._row_to_item(row)
                conn.execute(
                    """
                    UPDATE memory_items
                    SET status = 'archived', archived_at = ?, updated_at = ?,
                        revision = revision + 1
                    WHERE id = ?
                    """,
                    (now, now, item.id),
                )
                archived = self._get_in_connection(conn, item.id, item.owner_id)
                self._record_history(conn, archived, "auto-archived")
                count += 1
        return count

    def maintenance_scopes(self) -> list[tuple[str, MemoryScope, str | None, int, str | None]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT owner_id, scope, project_id,
                       SUM(CASE WHEN kind != 'summary' AND status = 'active' THEN 1 ELSE 0 END)
                           AS active_count,
                       MAX(CASE WHEN kind = 'summary' THEN created_at ELSE NULL END)
                           AS last_summary_at
                FROM memory_items
                WHERE deleted_at IS NULL
                GROUP BY owner_id, scope, project_id
                """
            ).fetchall()
        return [
            (
                row["owner_id"],
                MemoryScope(row["scope"]),
                row["project_id"],
                int(row["active_count"] or 0),
                row["last_summary_at"],
            )
            for row in rows
        ]

    def status_counts(self) -> dict[str, int]:
        counts = {
            MemoryStatus.ACTIVE.value: 0,
            MemoryStatus.ARCHIVED.value: 0,
            MemoryStatus.SUPERSEDED.value: 0,
        }
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM memory_items
                WHERE deleted_at IS NULL
                GROUP BY status
                """
            ).fetchall()
        for row in rows:
            counts[row["status"]] = int(row["count"])
        return counts

    def save_maintenance_report(self, report: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_maintenance_runs (
                    id, started_at, completed_at, report_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    report["started_at"],
                    report["completed_at"],
                    json.dumps(report, ensure_ascii=False),
                ),
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

    def _get_in_connection(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        owner_id: str,
        include_deleted: bool = False,
    ) -> MemoryItem:
        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
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

    def _record_history(
        self,
        conn: sqlite3.Connection,
        item: MemoryItem,
        reason: str,
    ) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_history (
                id, memory_id, revision, reason, snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                item.id,
                item.revision,
                reason,
                item.model_dump_json(),
                self._now(),
            ),
        )

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()
        }
        migrations = {
            "owner_id": "TEXT NOT NULL DEFAULT 'local-user'",
            "kind": "TEXT NOT NULL DEFAULT 'note'",
            "source_ref": "TEXT",
            "importance": "REAL NOT NULL DEFAULT 0.5",
            "tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "pinned": "INTEGER NOT NULL DEFAULT 0",
            "expires_at": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "access_count": "INTEGER NOT NULL DEFAULT 0",
            "helpful_count": "INTEGER NOT NULL DEFAULT 0",
            "unhelpful_count": "INTEGER NOT NULL DEFAULT 0",
            "last_accessed_at": "TEXT",
            "reinforced_at": "TEXT",
            "archived_at": "TEXT",
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
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _item_values(item: MemoryItem) -> tuple:
        return (
            item.id, item.owner_id, item.scope.value, item.project_id,
            item.kind.value, item.key, item.content, item.source, item.source_ref,
            item.confidence, item.importance,
            SQLiteMemoryStore._dump_tags(item.tags), int(item.pinned),
            item.expires_at, item.status.value, item.access_count,
            item.helpful_count, item.unhelpful_count, item.last_accessed_at,
            item.reinforced_at, item.archived_at, item.device_id, item.session_id,
            item.client_mutation_id, item.revision, item.created_at,
            item.updated_at, item.deleted_at,
        )

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
            pinned=bool(row["pinned"]),
            expires_at=row["expires_at"],
            status=MemoryStatus(row["status"]),
            access_count=row["access_count"],
            helpful_count=row["helpful_count"],
            unhelpful_count=row["unhelpful_count"],
            last_accessed_at=row["last_accessed_at"],
            reinforced_at=row["reinforced_at"],
            archived_at=row["archived_at"],
            device_id=row["device_id"],
            session_id=row["session_id"],
            client_mutation_id=row["client_mutation_id"],
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )

    @staticmethod
    def _row_to_link(row: sqlite3.Row) -> MemoryLink:
        return MemoryLink(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation=MemoryLinkType(row["relation"]),
            weight=row["weight"],
            created_at=row["created_at"],
        )
