import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from tooru.memory.models import (
    ConversationMessage,
    EntityAlias,
    MemoryCreate,
    MemoryDelete,
    MemoryEvidence,
    MemoryEvidenceCreate,
    MemoryFeedback,
    MemoryGuardianAuditEvent,
    MemoryGuardianDecision,
    MemoryGuardianOutcome,
    MemoryGuardianQueueItem,
    MemoryGuardianQueueStatus,
    MemoryGuardianRisk,
    MemoryGuardianStatus,
    MemoryIntelligenceDecision,
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
    SourceReliability,
)


class MemoryNotFoundError(LookupError):
    pass


class MemoryConflictError(RuntimeError):
    pass


class SQLiteMemoryStore:
    REQUIRED_TABLES: ClassVar[set[str]] = {
        "memory_items",
        "memory_vectors",
        "memory_links",
        "memory_history",
        "memory_evidence",
        "memory_maintenance_runs",
        "memory_guardian_events",
        "memory_guardian_queue",
        "memory_source_reliability",
        "memory_entity_aliases",
    }

    SELECT_COLUMNS = """
        id, owner_id, scope, project_id, kind, memory_key, content,
        source, source_ref, confidence, importance, tags_json, pinned,
        expires_at, observed_at, event_at, valid_from, valid_to,
        status, access_count, helpful_count, unhelpful_count,
        last_accessed_at, reinforced_at, archived_at,
        device_id, session_id, client_mutation_id, revision,
        created_at, updated_at, deleted_at
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
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
                    observed_at TEXT,
                    event_at TEXT,
                    valid_from TEXT,
                    valid_to TEXT,
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
                CREATE TABLE IF NOT EXISTS memory_evidence (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT,
                    document_id TEXT,
                    page INTEGER,
                    table_ref TEXT,
                    cell_ref TEXT,
                    chunk_no INTEGER,
                    evidence_hash TEXT,
                    excerpt TEXT,
                    extraction_method TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory
                ON memory_evidence(memory_id, created_at DESC)
                """
            )
            self._migrate_evidence_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_source_reliability (
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL DEFAULT '',
                    reliability REAL NOT NULL,
                    confirmations INTEGER NOT NULL DEFAULT 0,
                    contradictions INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_type, source_ref)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entity_aliases (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    project_id TEXT,
                    canonical_memory_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(
                        owner_id, scope, project_id,
                        canonical_memory_id, normalized_alias
                    ),
                    FOREIGN KEY(canonical_memory_id)
                        REFERENCES memory_items(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_entity_alias_lookup
                ON memory_entity_aliases(
                    owner_id, scope, project_id, normalized_alias
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
                CREATE TABLE IF NOT EXISTS memory_guardian_events (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    project_id TEXT,
                    risk TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    analyzer TEXT NOT NULL,
                    reviewer TEXT,
                    decision_json TEXT NOT NULL,
                    policy_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_guardian_events_scope
                ON memory_guardian_events(
                    owner_id, scope, project_id, outcome, created_at DESC
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_guardian_queue (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    project_id TEXT,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    analyzer TEXT NOT NULL,
                    reviewer TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_guardian_queue_pending_fingerprint
                ON memory_guardian_queue(fingerprint)
                WHERE status = 'pending'
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_guardian_queue_due
                ON memory_guardian_queue(status, next_attempt_at, created_at)
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
            self._initialize_fts(conn)

    def _initialize_fts(self, conn: sqlite3.Connection) -> None:
        """Create and backfill the optional FTS5 lexical index.

        FTS5 is available in normal CPython builds used by Dragon Tory. The
        fallback keeps the memory database usable on unusual SQLite builds
        where the extension is unavailable.
        """
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(
                    memory_key,
                    content,
                    tags,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memory_fts_ai
                AFTER INSERT ON memory_items
                BEGIN
                    INSERT INTO memory_fts(rowid, memory_key, content, tags)
                    VALUES (
                        new.rowid,
                        COALESCE(new.memory_key, ''),
                        new.content,
                        new.tags_json
                    );
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memory_fts_ad
                AFTER DELETE ON memory_items
                BEGIN
                    DELETE FROM memory_fts WHERE rowid = old.rowid;
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memory_fts_au
                AFTER UPDATE OF memory_key, content, tags_json ON memory_items
                BEGIN
                    DELETE FROM memory_fts WHERE rowid = old.rowid;
                    INSERT INTO memory_fts(rowid, memory_key, content, tags)
                    VALUES (
                        new.rowid,
                        COALESCE(new.memory_key, ''),
                        new.content,
                        new.tags_json
                    );
                END
                """
            )
            conn.execute(
                """
                INSERT INTO memory_fts(rowid, memory_key, content, tags)
                SELECT
                    m.rowid,
                    COALESCE(m.memory_key, ''),
                    m.content,
                    m.tags_json
                FROM memory_items AS m
                LEFT JOIN memory_fts AS f ON f.rowid = m.rowid
                WHERE f.rowid IS NULL
                """
            )
        except sqlite3.OperationalError as exc:
            if "fts5" not in str(exc).casefold():
                raise


    def add(self, memory: MemoryCreate) -> MemoryItem:
        if memory.client_mutation_id:
            existing = self._get_by_mutation_id(
                memory.owner_id, memory.client_mutation_id
            )
            if existing is not None:
                return existing

        now = self._now()
        payload = memory.model_dump()
        payload["observed_at"] = payload.get("observed_at") or now
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
            **payload,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    id, owner_id, scope, project_id, kind, memory_key, content,
                    source, source_ref, confidence, importance, tags_json, pinned,
                    expires_at, observed_at, event_at, valid_from, valid_to,
                    status, access_count, helpful_count, unhelpful_count,
                    last_accessed_at, reinforced_at, archived_at,
                    device_id, session_id, client_mutation_id, revision,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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
            "observed_at": changes.get("observed_at", current.observed_at),
            "event_at": changes.get("event_at", current.event_at),
            "valid_from": changes.get("valid_from", current.valid_from),
            "valid_to": changes.get("valid_to", current.valid_to),
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
                    observed_at = ?, event_at = ?, valid_from = ?, valid_to = ?,
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
                    values["observed_at"], values["event_at"],
                    values["valid_from"], values["valid_to"],
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

    @staticmethod
    def _fts_query(value: str) -> str:
        terms: list[str] = []
        seen: set[str] = set()
        for term in re.findall(r"[\w-]+", value.casefold(), flags=re.UNICODE):
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 20:
                break
        return " OR ".join(f'"{term}"' for term in terms)

    def lexical_candidates(
        self,
        request: MemorySearch,
        *,
        limit: int = 200,
    ) -> list[MemoryItem]:
        """Retrieve query-matching memories through SQLite FTS5.

        This channel is intentionally independent from the normal importance /
        recency candidate window so an older low-importance but textually
        relevant memory can still reach the hybrid reranker.
        """
        fts_query = self._fts_query(request.query)
        if not fts_query:
            return []

        params: list[object] = [fts_query, request.owner_id, request.scope.value]
        clauses = [
            "memory_fts MATCH ?",
            "m.owner_id = ?",
            "m.scope = ?",
            "m.deleted_at IS NULL",
        ]

        if request.scope is MemoryScope.PROJECT:
            clauses.append("m.project_id = ?")
            params.append(request.project_id)
        else:
            clauses.append("m.project_id IS NULL")

        if not request.include_archived:
            clauses.append("m.status = 'active'")
            clauses.append("(m.expires_at IS NULL OR m.expires_at > ?)")
            params.append(self._now())

        if request.kind is not None:
            clauses.append("m.kind = ?")
            params.append(request.kind.value)

        clauses.append("m.importance >= ?")
        params.append(request.min_importance)

        for tag in request.tags:
            clauses.append("m.tags_json LIKE ?")
            params.append(f'%"{tag}"%')

        params.append(max(1, min(1000, limit)))
        select_columns = ", ".join(
            f"m.{column.strip()}"
            for column in self.SELECT_COLUMNS.split(",")
        )
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT {select_columns}
                    FROM memory_fts
                    JOIN memory_items AS m ON m.rowid = memory_fts.rowid
                    WHERE {" AND ".join(clauses)}
                    ORDER BY bm25(memory_fts),
                             m.pinned DESC,
                             m.importance DESC,
                             m.updated_at DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "memory_fts" in str(exc).casefold() or "fts5" in str(exc).casefold():
                return []
            raise
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
            if " ".join(item.content.lower().split()) != normalized:
                continue
            if (
                item.valid_from == memory.valid_from
                and item.valid_to == memory.valid_to
                and item.event_at == memory.event_at
            ):
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

    def graph_candidates(
        self,
        request: MemorySearch,
        seed_ids: list[str],
        *,
        limit: int = 100,
    ) -> list[tuple[MemoryItem, float]]:
        if not seed_ids:
            return []

        allowed_relations = {
            MemoryLinkType.RELATED.value,
            MemoryLinkType.SUPPORTS.value,
            MemoryLinkType.SUMMARIZES.value,
            MemoryLinkType.TEMPORAL_SUCCESSOR.value,
            MemoryLinkType.TEMPORAL_PREDECESSOR.value,
            MemoryLinkType.SAME_ENTITY.value,
            MemoryLinkType.CAUSES.value,
            MemoryLinkType.DEPENDS_ON.value,
            MemoryLinkType.PART_OF.value,
            MemoryLinkType.CORRECTS.value,
            MemoryLinkType.DERIVED_FROM.value,
            MemoryLinkType.REQUIRES.value,
        }
        placeholders = ",".join("?" for _ in seed_ids)
        relation_placeholders = ",".join("?" for _ in allowed_relations)
        params: list[object] = [
            *seed_ids,
            *seed_ids,
            *sorted(allowed_relations),
        ]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT source_id, target_id, relation, weight
                FROM memory_links
                WHERE (
                    source_id IN ({placeholders})
                    OR target_id IN ({placeholders})
                )
                  AND relation IN ({relation_placeholders})
                """,
                params,
            ).fetchall()

        weights: dict[str, float] = {}
        seeds = set(seed_ids)
        for row in rows:
            source_id = str(row["source_id"])
            target_id = str(row["target_id"])
            weight = float(row["weight"])
            if source_id in seeds and target_id != source_id:
                weights[target_id] = max(
                    weights.get(target_id, 0.0),
                    weight,
                )
            if target_id in seeds and source_id != target_id:
                weights[source_id] = max(
                    weights.get(source_id, 0.0),
                    weight,
                )
        first_hop = dict(weights)
        if first_hop:
            hop_ids = list(first_hop)[:200]
            hop_placeholders = ",".join("?" for _ in hop_ids)
            hop_params: list[object] = [
                *hop_ids,
                *hop_ids,
                *sorted(allowed_relations),
            ]
            with self._connect() as conn:
                hop_rows = conn.execute(
                    f"""
                    SELECT source_id, target_id, relation, weight
                    FROM memory_links
                    WHERE (
                        source_id IN ({hop_placeholders})
                        OR target_id IN ({hop_placeholders})
                    )
                      AND relation IN ({relation_placeholders})
                    """,
                    hop_params,
                ).fetchall()
            first_ids = set(hop_ids)
            for row in hop_rows:
                source_id = str(row["source_id"])
                target_id = str(row["target_id"])
                edge_weight = float(row["weight"])
                if source_id in first_ids:
                    neighbor_id = target_id
                    parent_id = source_id
                elif target_id in first_ids:
                    neighbor_id = source_id
                    parent_id = target_id
                else:
                    continue
                if neighbor_id in seeds:
                    continue
                propagated = (
                    first_hop.get(parent_id, 0.0)
                    * edge_weight
                    * 0.65
                )
                if propagated <= 0:
                    continue
                weights[neighbor_id] = max(
                    weights.get(neighbor_id, 0.0),
                    propagated,
                )

        if not weights:
            return []

        ordered_ids = sorted(
            weights,
            key=lambda memory_id: weights[memory_id],
            reverse=True,
        )[: max(1, min(limit, 500))]
        id_placeholders = ",".join("?" for _ in ordered_ids)
        item_params: list[object] = [*ordered_ids, request.owner_id, request.scope.value]
        clauses = [
            f"id IN ({id_placeholders})",
            "owner_id = ?",
            "scope = ?",
            "deleted_at IS NULL",
        ]
        if request.scope is MemoryScope.PROJECT:
            clauses.append("project_id = ?")
            item_params.append(request.project_id)
        else:
            clauses.append("project_id IS NULL")
        if not request.include_archived:
            clauses.append("status = 'active'")
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            item_params.append(self._now())
        if request.kind is not None:
            clauses.append("kind = ?")
            item_params.append(request.kind.value)
        clauses.append("importance >= ?")
        item_params.append(request.min_importance)
        for tag in request.tags:
            clauses.append("tags_json LIKE ?")
            item_params.append(f'%"{tag}"%')

        with self._connect() as conn:
            item_rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                """,
                item_params,
            ).fetchall()

        items = {
            row["id"]: self._row_to_item(row)
            for row in item_rows
        }
        return [
            (items[memory_id], weights[memory_id])
            for memory_id in ordered_ids
            if memory_id in items
        ]

    def scope_items(
        self,
        *,
        owner_id: str,
        scope: MemoryScope,
        project_id: str | None,
        kinds: set[MemoryKind] | None = None,
        include_archived: bool = False,
        limit: int = 2000,
    ) -> list[MemoryItem]:
        params: list[object] = [owner_id, scope.value]
        clauses = [
            "owner_id = ?",
            "scope = ?",
            "deleted_at IS NULL",
        ]
        if scope is MemoryScope.PROJECT:
            clauses.append("project_id = ?")
            params.append(project_id)
        else:
            clauses.append("project_id IS NULL")
        if not include_archived:
            clauses.append("status = 'active'")
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(sorted(kind.value for kind in kinds))
        params.append(max(1, min(limit, 10_000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM memory_items
                WHERE {" AND ".join(clauses)}
                ORDER BY pinned DESC, importance DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def source_reliability(
        self,
        source_type: str,
        source_ref: str | None = None,
    ) -> SourceReliability | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT source_type, source_ref, reliability,
                       confirmations, contradictions, updated_at
                FROM memory_source_reliability
                WHERE source_type = ? AND source_ref = ?
                """,
                (source_type, source_ref or ""),
            ).fetchone()
        if row is None:
            return None
        return SourceReliability(
            source_type=row["source_type"],
            source_ref=row["source_ref"] or None,
            reliability=float(row["reliability"]),
            confirmations=int(row["confirmations"]),
            contradictions=int(row["contradictions"]),
            updated_at=row["updated_at"],
        )

    def update_source_reliability(
        self,
        source_type: str,
        *,
        source_ref: str | None = None,
        confirmed: bool,
        base_reliability: float = 0.5,
    ) -> SourceReliability:
        current = self.source_reliability(source_type, source_ref)
        confirmations = current.confirmations if current else 0
        contradictions = current.contradictions if current else 0
        if confirmed:
            confirmations += 1
        else:
            contradictions += 1
        total = confirmations + contradictions
        observed = confirmations / total if total else base_reliability
        reliability = max(
            0.05,
            min(
                0.99,
                (base_reliability * 2.0 + observed * total) / (2.0 + total),
            ),
        )
        updated_at = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_source_reliability (
                    source_type, source_ref, reliability,
                    confirmations, contradictions, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, source_ref) DO UPDATE SET
                    reliability = excluded.reliability,
                    confirmations = excluded.confirmations,
                    contradictions = excluded.contradictions,
                    updated_at = excluded.updated_at
                """,
                (
                    source_type,
                    source_ref or "",
                    reliability,
                    confirmations,
                    contradictions,
                    updated_at,
                ),
            )
        result = self.source_reliability(source_type, source_ref)
        if result is None:
            raise RuntimeError("failed to persist source reliability")
        return result

    def add_entity_alias(
        self,
        *,
        owner_id: str,
        scope: MemoryScope,
        project_id: str | None,
        canonical_memory_id: str,
        alias: str,
        normalized_alias: str,
        confidence: float,
    ) -> EntityAlias:
        canonical = self.get(canonical_memory_id, owner_id)
        if canonical.scope is not scope or canonical.project_id != project_id:
            raise MemoryConflictError(
                "entity alias scope does not match canonical memory"
            )
        item = EntityAlias(
            id=str(uuid4()),
            owner_id=owner_id,
            scope=scope,
            project_id=project_id,
            canonical_memory_id=canonical_memory_id,
            alias=alias,
            normalized_alias=normalized_alias,
            confidence=confidence,
            created_at=self._now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_entity_aliases (
                    id, owner_id, scope, project_id, canonical_memory_id,
                    alias, normalized_alias, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    owner_id, scope, project_id,
                    canonical_memory_id, normalized_alias
                ) DO UPDATE SET
                    alias = excluded.alias,
                    confidence = MAX(confidence, excluded.confidence)
                """,
                (
                    item.id,
                    item.owner_id,
                    item.scope.value,
                    item.project_id,
                    item.canonical_memory_id,
                    item.alias,
                    item.normalized_alias,
                    item.confidence,
                    item.created_at,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM memory_entity_aliases
                WHERE owner_id = ? AND scope = ?
                  AND project_id IS ?
                  AND canonical_memory_id = ?
                  AND normalized_alias = ?
                """,
                (
                    owner_id,
                    scope.value,
                    project_id,
                    canonical_memory_id,
                    normalized_alias,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to persist entity alias")
        return self._row_to_entity_alias(row)

    def entity_aliases(
        self,
        *,
        owner_id: str,
        scope: MemoryScope,
        project_id: str | None,
        normalized_alias: str | None = None,
        limit: int = 200,
    ) -> list[EntityAlias]:
        params: list[object] = [owner_id, scope.value]
        clauses = ["owner_id = ?", "scope = ?"]
        if scope is MemoryScope.PROJECT:
            clauses.append("project_id = ?")
            params.append(project_id)
        else:
            clauses.append("project_id IS NULL")
        if normalized_alias is not None:
            clauses.append("normalized_alias = ?")
            params.append(normalized_alias)
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM memory_entity_aliases
                WHERE {" AND ".join(clauses)}
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_entity_alias(row) for row in rows]

    def add_evidence(
        self,
        memory_id: str,
        evidence: MemoryEvidenceCreate,
        *,
        owner_id: str = "local-user",
    ) -> MemoryEvidence:
        self.get(memory_id, owner_id)
        item = MemoryEvidence(
            id=str(uuid4()),
            memory_id=memory_id,
            created_at=self._now(),
            **evidence.model_dump(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_evidence (
                    id, memory_id, source_type, source_ref, document_id,
                    page, table_ref, cell_ref, chunk_no, evidence_hash,
                    excerpt, extraction_method, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id, item.memory_id, item.source_type, item.source_ref,
                    item.document_id, item.page, item.table_ref, item.cell_ref,
                    item.chunk_no, item.evidence_hash, item.excerpt,
                    item.extraction_method, item.confidence, item.created_at,
                ),
            )
        return item

    def evidence_for(
        self,
        memory_id: str,
        *,
        owner_id: str = "local-user",
        limit: int = 100,
    ) -> list[MemoryEvidence]:
        self.get(memory_id, owner_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, memory_id, source_type, source_ref, document_id,
                       page, table_ref, cell_ref, chunk_no, evidence_hash,
                       excerpt, extraction_method, confidence, created_at
                FROM memory_evidence
                WHERE memory_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (memory_id, max(1, min(limit, 500))),
            ).fetchall()
        return [
            MemoryEvidence(
                id=row["id"],
                memory_id=row["memory_id"],
                source_type=row["source_type"],
                source_ref=row["source_ref"],
                document_id=row["document_id"],
                page=row["page"],
                table_ref=row["table_ref"],
                cell_ref=row["cell_ref"],
                chunk_no=row["chunk_no"],
                evidence_hash=row["evidence_hash"],
                excerpt=row["excerpt"],
                extraction_method=row["extraction_method"],
                confidence=row["confidence"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

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

    def record_guardian_event(
        self,
        *,
        owner_id: str,
        scope: MemoryScope,
        project_id: str | None,
        guardian_decision: MemoryGuardianDecision,
        analyzer: str,
        reviewer: str | None,
    ) -> MemoryGuardianAuditEvent:
        event = MemoryGuardianAuditEvent(
            id=str(uuid4()),
            owner_id=owner_id,
            scope=scope,
            project_id=project_id,
            risk=guardian_decision.risk,
            outcome=guardian_decision.outcome,
            analyzer=analyzer,
            reviewer=reviewer,
            decision=guardian_decision.decision,
            policy_reason=guardian_decision.policy_reason,
            created_at=self._now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_guardian_events (
                    id, owner_id, scope, project_id, risk, outcome,
                    analyzer, reviewer, decision_json, policy_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.owner_id,
                    event.scope.value,
                    event.project_id,
                    event.risk.value,
                    event.outcome.value,
                    event.analyzer,
                    event.reviewer,
                    event.decision.model_dump_json(),
                    event.policy_reason,
                    event.created_at,
                ),
            )
        return event

    def guardian_status(self) -> MemoryGuardianStatus:
        status = MemoryGuardianStatus()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT outcome, COUNT(*) AS count
                FROM memory_guardian_events
                GROUP BY outcome
                """
            ).fetchall()
            last = conn.execute(
                """
                SELECT created_at
                FROM memory_guardian_events
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()

        total = 0
        counts = {
            MemoryGuardianOutcome.APPLIED.value: 0,
            MemoryGuardianOutcome.PENDING.value: 0,
            MemoryGuardianOutcome.BLOCKED.value: 0,
            MemoryGuardianOutcome.IGNORED.value: 0,
        }
        for row in rows:
            counts[row["outcome"]] = int(row["count"])
            total += int(row["count"])

        with self._connect() as conn:
            queue_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM memory_guardian_queue
                GROUP BY status
                """
            ).fetchall()

        queue_counts = {
            MemoryGuardianQueueStatus.PENDING.value: 0,
            MemoryGuardianQueueStatus.APPLIED.value: 0,
            MemoryGuardianQueueStatus.REJECTED.value: 0,
            MemoryGuardianQueueStatus.DEAD.value: 0,
        }
        for row in queue_rows:
            queue_counts[row["status"]] = int(row["count"])

        status.total_events = total
        status.applied = counts[MemoryGuardianOutcome.APPLIED.value]
        status.pending = counts[MemoryGuardianOutcome.PENDING.value]
        status.blocked = counts[MemoryGuardianOutcome.BLOCKED.value]
        status.ignored = counts[MemoryGuardianOutcome.IGNORED.value]
        status.queued_pending = queue_counts[MemoryGuardianQueueStatus.PENDING.value]
        status.queued_applied = queue_counts[MemoryGuardianQueueStatus.APPLIED.value]
        status.queued_rejected = queue_counts[MemoryGuardianQueueStatus.REJECTED.value]
        status.queued_dead = queue_counts[MemoryGuardianQueueStatus.DEAD.value]
        status.last_event_at = last["created_at"] if last else None
        return status

    def guardian_events(
        self,
        *,
        outcome: MemoryGuardianOutcome | None = None,
        limit: int = 50,
    ) -> list[MemoryGuardianAuditEvent]:
        params: list[object] = []
        where = ""
        if outcome is not None:
            where = "WHERE outcome = ?"
            params.append(outcome.value)
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, owner_id, scope, project_id, risk, outcome,
                       analyzer, reviewer, decision_json, policy_reason, created_at
                FROM memory_guardian_events
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [
            MemoryGuardianAuditEvent(
                id=row["id"],
                owner_id=row["owner_id"],
                scope=MemoryScope(row["scope"]),
                project_id=row["project_id"],
                risk=MemoryGuardianRisk(row["risk"]),
                outcome=MemoryGuardianOutcome(row["outcome"]),
                analyzer=row["analyzer"],
                reviewer=row["reviewer"],
                decision=MemoryIntelligenceDecision.model_validate_json(
                    row["decision_json"]
                ),
                policy_reason=row["policy_reason"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def queue_guardian_decision(
        self,
        *,
        fingerprint: str,
        owner_id: str,
        scope: MemoryScope,
        project_id: str | None,
        risk: MemoryGuardianRisk,
        decision: MemoryIntelligenceDecision,
        messages: list[ConversationMessage],
        analyzer: str,
        reviewer: str | None,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> MemoryGuardianQueueItem:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        next_attempt_at = (now + timedelta(seconds=retry_delay_seconds)).isoformat()
        queue_id = str(uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_guardian_queue (
                    id, fingerprint, owner_id, scope, project_id, risk, status,
                    decision_json, messages_json, analyzer, reviewer, attempts,
                    max_attempts, next_attempt_at, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0, ?, ?, NULL, ?, ?)
                """,
                (
                    queue_id,
                    fingerprint,
                    owner_id,
                    scope.value,
                    project_id,
                    risk.value,
                    decision.model_dump_json(),
                    json.dumps(
                        [message.model_dump(mode="json") for message in messages],
                        ensure_ascii=False,
                    ),
                    analyzer,
                    reviewer,
                    max_attempts,
                    next_attempt_at,
                    now_iso,
                    now_iso,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM memory_guardian_queue
                WHERE fingerprint = ? AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (fingerprint,),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to create or load Guardian queue item")
        return self._row_to_guardian_queue_item(row)

    def get_guardian_queue_item(self, queue_id: str) -> MemoryGuardianQueueItem:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_guardian_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError(queue_id)
        return self._row_to_guardian_queue_item(row)

    def guardian_queue_items(
        self,
        *,
        status: MemoryGuardianQueueStatus | None = None,
        due_only: bool = False,
        limit: int = 50,
    ) -> list[MemoryGuardianQueueItem]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if due_only:
            clauses.append("(next_attempt_at IS NULL OR next_attempt_at <= ?)")
            params.append(self._now())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM memory_guardian_queue
                {where}
                ORDER BY created_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_guardian_queue_item(row) for row in rows]

    def update_guardian_queue(
        self,
        queue_id: str,
        *,
        status: MemoryGuardianQueueStatus | None = None,
        reviewer: str | None = None,
        last_error: str | None = None,
        increment_attempt: bool = False,
        retry_delay_seconds: int | None = None,
    ) -> MemoryGuardianQueueItem:
        current = self.get_guardian_queue_item(queue_id)
        next_status = status or current.status
        attempts = current.attempts + (1 if increment_attempt else 0)
        now = datetime.now(UTC)
        next_attempt_at = current.next_attempt_at
        if retry_delay_seconds is not None:
            next_attempt_at = (
                now + timedelta(seconds=retry_delay_seconds)
            ).isoformat()
        if next_status is not MemoryGuardianQueueStatus.PENDING:
            next_attempt_at = None

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_guardian_queue
                SET status = ?, reviewer = ?, attempts = ?, next_attempt_at = ?,
                    last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_status.value,
                    reviewer if reviewer is not None else current.reviewer,
                    attempts,
                    next_attempt_at,
                    last_error,
                    now.isoformat(),
                    queue_id,
                ),
            )
        return self.get_guardian_queue_item(queue_id)

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

    @staticmethod
    def _migrate_evidence_schema(conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(memory_evidence)"
            ).fetchall()
        }
        migrations = {
            "table_ref": "TEXT",
            "cell_ref": "TEXT",
            "chunk_no": "INTEGER",
            "evidence_hash": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE memory_evidence "
                    f"ADD COLUMN {column} {definition}"
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
            "observed_at": "TEXT",
            "event_at": "TEXT",
            "valid_from": "TEXT",
            "valid_to": "TEXT",
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

    def health_report(self, *, deep: bool = False) -> dict:
        report = {
            "status": "ok",
            "database_path": str(self.db_path),
            "database_exists": self.db_path.exists(),
            "integrity": "not_run",
            "foreign_key_errors": 0,
            "missing_tables": [],
            "invalid_scope_rows": 0,
            "orphan_vectors": 0,
            "orphan_links": 0,
            "orphan_history": 0,
            "orphan_evidence": 0,
            "orphan_entity_aliases": 0,
            "invalid_entity_alias_scope": 0,
            "entity_aliases": 0,
            "source_reliability_entries": 0,
            "active_memories": 0,
            "personal_memories": 0,
            "project_memories": 0,
            "active_vectors": 0,
            "vector_coverage_percent": 0.0,
            "fts_available": False,
            "fts_entries": 0,
            "guardian_pending": 0,
            "guardian_dead": 0,
            "journal_mode": None,
            "error": None,
        }
        try:
            with self._connect() as conn:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                        """
                    ).fetchall()
                }
                missing = sorted(self.REQUIRED_TABLES - tables)
                report["missing_tables"] = missing
                report["journal_mode"] = conn.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0]

                if "memory_items" in tables:
                    counts = conn.execute(
                        """
                        SELECT
                            SUM(CASE WHEN deleted_at IS NULL
                                AND status = 'active' THEN 1 ELSE 0 END)
                                AS active_memories,
                            SUM(CASE WHEN deleted_at IS NULL
                                AND scope = 'personal' THEN 1 ELSE 0 END)
                                AS personal_memories,
                            SUM(CASE WHEN deleted_at IS NULL
                                AND scope = 'project' THEN 1 ELSE 0 END)
                                AS project_memories,
                            SUM(CASE WHEN
                                (scope = 'personal' AND project_id IS NOT NULL)
                                OR
                                (scope = 'project' AND project_id IS NULL)
                                THEN 1 ELSE 0 END)
                                AS invalid_scope_rows
                        FROM memory_items
                        """
                    ).fetchone()
                    for key in (
                        "active_memories",
                        "personal_memories",
                        "project_memories",
                        "invalid_scope_rows",
                    ):
                        report[key] = int(counts[key] or 0)

                if {"memory_items", "memory_vectors"} <= tables:
                    report["active_vectors"] = int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM memory_vectors v
                            JOIN memory_items m ON m.id = v.memory_id
                            WHERE m.deleted_at IS NULL
                              AND m.status = 'active'
                            """
                        ).fetchone()[0]
                        or 0
                    )
                    report["orphan_vectors"] = int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM memory_vectors v
                            LEFT JOIN memory_items m ON m.id = v.memory_id
                            WHERE m.id IS NULL
                            """
                        ).fetchone()[0]
                        or 0
                    )

                if {"memory_items", "memory_links"} <= tables:
                    report["orphan_links"] = int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM memory_links l
                            LEFT JOIN memory_items s ON s.id = l.source_id
                            LEFT JOIN memory_items t ON t.id = l.target_id
                            WHERE s.id IS NULL OR t.id IS NULL
                            """
                        ).fetchone()[0]
                        or 0
                    )

                if {"memory_items", "memory_history"} <= tables:
                    report["orphan_history"] = int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM memory_history h
                            LEFT JOIN memory_items m ON m.id = h.memory_id
                            WHERE m.id IS NULL
                            """
                        ).fetchone()[0]
                        or 0
                    )

                if {"memory_items", "memory_evidence"} <= tables:
                    report["orphan_evidence"] = int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM memory_evidence e
                            LEFT JOIN memory_items m ON m.id = e.memory_id
                            WHERE m.id IS NULL
                            """
                        ).fetchone()[0]
                        or 0
                    )

                if "memory_entity_aliases" in tables:
                    report["entity_aliases"] = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM memory_entity_aliases"
                        ).fetchone()[0]
                        or 0
                    )
                    if "memory_items" in tables:
                        report["orphan_entity_aliases"] = int(
                            conn.execute(
                                """
                                SELECT COUNT(*)
                                FROM memory_entity_aliases a
                                LEFT JOIN memory_items m
                                  ON m.id = a.canonical_memory_id
                                WHERE m.id IS NULL
                                """
                            ).fetchone()[0]
                            or 0
                        )
                        report["invalid_entity_alias_scope"] = int(
                            conn.execute(
                                """
                                SELECT COUNT(*)
                                FROM memory_entity_aliases a
                                JOIN memory_items m
                                  ON m.id = a.canonical_memory_id
                                WHERE a.owner_id != m.owner_id
                                   OR a.scope != m.scope
                                   OR COALESCE(a.project_id, '')
                                      != COALESCE(m.project_id, '')
                                """
                            ).fetchone()[0]
                            or 0
                        )

                if "memory_source_reliability" in tables:
                    report["source_reliability_entries"] = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM memory_source_reliability"
                        ).fetchone()[0]
                        or 0
                    )

                if "memory_fts" in tables:
                    report["fts_available"] = True
                    report["fts_entries"] = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM memory_fts"
                        ).fetchone()[0]
                        or 0
                    )

                if "memory_guardian_queue" in tables:
                    queue = conn.execute(
                        """
                        SELECT
                            SUM(CASE WHEN status = 'pending'
                                THEN 1 ELSE 0 END) AS pending,
                            SUM(CASE WHEN status = 'dead'
                                THEN 1 ELSE 0 END) AS dead
                        FROM memory_guardian_queue
                        """
                    ).fetchone()
                    report["guardian_pending"] = int(queue["pending"] or 0)
                    report["guardian_dead"] = int(queue["dead"] or 0)

                if report["active_memories"]:
                    report["vector_coverage_percent"] = round(
                        report["active_vectors"]
                        / report["active_memories"]
                        * 100,
                        1,
                    )

                if deep:
                    quick = conn.execute("PRAGMA quick_check").fetchone()
                    report["integrity"] = (
                        str(quick[0]) if quick is not None else "unknown"
                    )
                    report["foreign_key_errors"] = len(
                        conn.execute("PRAGMA foreign_key_check").fetchall()
                    )

            hard_errors = (
                bool(report["missing_tables"])
                or report["invalid_scope_rows"] > 0
                or report["orphan_vectors"] > 0
                or report["orphan_links"] > 0
                or report["orphan_history"] > 0
                or report["orphan_evidence"] > 0
                or report["orphan_entity_aliases"] > 0
                or report["invalid_entity_alias_scope"] > 0
                or report["foreign_key_errors"] > 0
                or (
                    deep
                    and report["integrity"].casefold() != "ok"
                )
            )
            warning = report["guardian_dead"] > 0
            report["status"] = (
                "error" if hard_errors else ("warning" if warning else "ok")
            )
        except sqlite3.DatabaseError as exc:
            report["status"] = "error"
            report["error"] = f"{type(exc).__name__}: {exc}"
            if deep:
                report["integrity"] = "error"
        return report

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @staticmethod
    def _item_values(item: MemoryItem) -> tuple:
        return (
            item.id, item.owner_id, item.scope.value, item.project_id,
            item.kind.value, item.key, item.content, item.source, item.source_ref,
            item.confidence, item.importance,
            SQLiteMemoryStore._dump_tags(item.tags), int(item.pinned),
            item.expires_at, item.observed_at, item.event_at,
            item.valid_from, item.valid_to, item.status.value, item.access_count,
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
            observed_at=row["observed_at"],
            event_at=row["event_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
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
    def _row_to_guardian_queue_item(row: sqlite3.Row) -> MemoryGuardianQueueItem:
        return MemoryGuardianQueueItem(
            id=row["id"],
            fingerprint=row["fingerprint"],
            owner_id=row["owner_id"],
            scope=MemoryScope(row["scope"]),
            project_id=row["project_id"],
            risk=MemoryGuardianRisk(row["risk"]),
            status=MemoryGuardianQueueStatus(row["status"]),
            decision=MemoryIntelligenceDecision.model_validate_json(
                row["decision_json"]
            ),
            messages=[
                ConversationMessage.model_validate(message)
                for message in json.loads(row["messages_json"])
            ],
            analyzer=row["analyzer"],
            reviewer=row["reviewer"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            next_attempt_at=row["next_attempt_at"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_entity_alias(row: sqlite3.Row) -> EntityAlias:
        return EntityAlias(
            id=row["id"],
            owner_id=row["owner_id"],
            scope=MemoryScope(row["scope"]),
            project_id=row["project_id"],
            canonical_memory_id=row["canonical_memory_id"],
            alias=row["alias"],
            normalized_alias=row["normalized_alias"],
            confidence=float(row["confidence"]),
            created_at=row["created_at"],
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
