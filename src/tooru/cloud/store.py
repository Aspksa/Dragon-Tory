from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

AI_ACCESS_LEVELS = {
    "denied",
    "search",
    "read",
    "answer",
    "memory",
    "full",
}
CONFIDENTIALITY_LEVELS = {
    "ordinary",
    "personal",
    "confidential",
    "highly_protected",
}
SCOPES = {"personal", "project"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CloudStore:
    def __init__(self, root_dir: Path, db_path: Path) -> None:
        self.root_dir = Path(root_dir)
        self.db_path = Path(db_path)
        self.files_dir = self.root_dir / "files"
        self.trash_dir = self.root_dir / "trash"
        self.incoming_dir = self.root_dir / ".incoming"

    def initialize(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'personal',
                    project_id TEXT,
                    confidentiality TEXT NOT NULL DEFAULT 'personal',
                    ai_access TEXT NOT NULL DEFAULT 'denied',
                    ai_index_status TEXT NOT NULL DEFAULT 'blocked',
                    version INTEGER NOT NULL DEFAULT 1,
                    indexed_version INTEGER,
                    source TEXT NOT NULL DEFAULT 'upload',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    trashed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_name ON documents(name)"
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_updated
                ON documents(updated_at DESC)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_sha256
                ON documents(sha256)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["trashed"] = bool(item["trashed"])
        item["ai_ready_for_current_version"] = bool(
            item["indexed_version"]
            and item["indexed_version"] == item["version"]
            and item["ai_index_status"] == "ready"
        )
        return item

    def register_upload(
        self,
        temp_path: Path,
        *,
        name: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        document_id = "TORY-DOC-" + uuid4().hex.upper()
        suffix = Path(name).suffix[:16]
        stored_name = document_id + suffix
        destination = self.files_dir / stored_name
        now = utc_now()

        os.replace(temp_path, destination)
        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO documents (
                        id, name, original_name, stored_name, content_type,
                        size_bytes, sha256, scope, confidentiality, ai_access,
                        ai_index_status, version, source, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'personal', 'personal', 'denied',
                            'blocked', 1, 'upload', ?, ?)
                    """,
                    (
                        document_id,
                        name,
                        name,
                        stored_name,
                        content_type or "application/octet-stream",
                        size_bytes,
                        sha256,
                        now,
                        now,
                    ),
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        return self.get(document_id)

    def get(self, document_id: str, *, include_trashed: bool = False) -> dict[str, Any]:
        sql = "SELECT * FROM documents WHERE id = ?"
        params: list[Any] = [document_id]
        if not include_trashed:
            sql += " AND trashed = 0"
        with self._connect() as db:
            row = db.execute(sql, params).fetchone()
        if row is None:
            raise KeyError(document_id)
        return self._row(row)

    def list_documents(
        self,
        *,
        query: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        sql = "SELECT * FROM documents WHERE trashed = 0"
        cleaned = query.strip()
        if cleaned:
            pattern = f"%{cleaned}%"
            sql += (
                " AND (name LIKE ? OR id LIKE ? OR content_type LIKE ?"
                " OR sha256 LIKE ? OR COALESCE(project_id, '') LIKE ?)"
            )
            params.extend([pattern, pattern, pattern, pattern, pattern])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._row(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(size_bytes), 0) AS total_bytes,
                    SUM(CASE WHEN ai_access != 'denied' THEN 1 ELSE 0 END) AS ai_allowed,
                    SUM(
                        CASE
                            WHEN confidentiality IN ('confidential', 'highly_protected')
                            THEN 1 ELSE 0
                        END
                    ) AS protected
                FROM documents
                WHERE trashed = 0
                """
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "ai_allowed": int(row["ai_allowed"] or 0),
            "protected": int(row["protected"] or 0),
        }

    def update_passport(
        self,
        document_id: str,
        *,
        ai_access: str | None = None,
        confidentiality: str | None = None,
        scope: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.get(document_id)
        next_ai_access = ai_access or current["ai_access"]
        next_confidentiality = confidentiality or current["confidentiality"]
        next_scope = scope or current["scope"]
        next_project = project_id if project_id is not None else current["project_id"]

        if next_ai_access not in AI_ACCESS_LEVELS:
            raise ValueError("Недопустимый уровень доступа ИИ.")
        if next_confidentiality not in CONFIDENTIALITY_LEVELS:
            raise ValueError("Недопустимый уровень конфиденциальности.")
        if next_scope not in SCOPES:
            raise ValueError("Недопустимая область документа.")
        if next_scope == "personal":
            next_project = None
        elif not next_project:
            raise ValueError("Для проектного документа требуется project_id.")

        if next_ai_access == "denied":
            index_status = "blocked"
        elif (
            current["indexed_version"] == current["version"]
            and current["ai_index_status"] == "ready"
        ):
            index_status = "ready"
        else:
            index_status = "needs_indexing"

        with self._connect() as db:
            db.execute(
                """
                UPDATE documents
                SET ai_access = ?, confidentiality = ?, scope = ?, project_id = ?,
                    ai_index_status = ?, updated_at = ?
                WHERE id = ? AND trashed = 0
                """,
                (
                    next_ai_access,
                    next_confidentiality,
                    next_scope,
                    next_project,
                    index_status,
                    utc_now(),
                    document_id,
                ),
            )
        return self.get(document_id)

    def content_path(self, document_id: str) -> Path:
        item = self.get(document_id)
        path = self.files_dir / item["stored_name"]
        if not path.is_file():
            raise FileNotFoundError(document_id)
        return path

    def trash(self, document_id: str) -> dict[str, Any]:
        item = self.get(document_id)
        source = self.files_dir / item["stored_name"]
        destination = self.trash_dir / item["stored_name"]
        if source.exists():
            shutil.move(str(source), str(destination))
        with self._connect() as db:
            db.execute(
                "UPDATE documents SET trashed = 1, updated_at = ? WHERE id = ?",
                (utc_now(), document_id),
            )
        return {**item, "trashed": True}
