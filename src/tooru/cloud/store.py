from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from tooru.cloud.vault import ToryVault

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

AI_ACCESS_BY_CONFIDENTIALITY = {
    "ordinary": AI_ACCESS_LEVELS,
    "personal": AI_ACCESS_LEVELS,
    "confidential": {"denied", "search", "read"},
    "highly_protected": {"denied"},
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CloudStore:
    def __init__(
        self,
        root_dir: Path,
        db_path: Path,
        *,
        vault: ToryVault | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.db_path = Path(db_path)
        self.vault = vault
        self.files_dir = self.root_dir / "files"
        self.trash_dir = self.root_dir / "trash"
        self.versions_dir = self.root_dir / "versions"
        self.incoming_dir = self.root_dir / ".incoming"

    def initialize(self) -> None:
        for path in (
            self.root_dir,
            self.files_dir,
            self.trash_dir,
            self.versions_dir,
            self.incoming_dir,
            self.db_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

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
            self._ensure_column(db, "documents", "folder_id", "TEXT")
            self._ensure_column(
                db,
                "documents",
                "favorite",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                db,
                "documents",
                "description",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "documents",
                "tags_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(db, "documents", "last_integrity_at", "TEXT")
            self._ensure_column(db, "documents", "trashed_at", "TEXT")
            self._ensure_column(
                db,
                "documents",
                "encrypted",
                "INTEGER NOT NULL DEFAULT 0",
            )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS folders (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    parent_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    trashed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_versions (
                    document_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    storage_ref TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    PRIMARY KEY(document_id, version)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    document_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    chunk_no INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    page_no INTEGER,
                    text TEXT NOT NULL,
                    PRIMARY KEY(document_id, version, chunk_no)
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
                CREATE INDEX IF NOT EXISTS idx_documents_folder
                ON documents(folder_id, trashed)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_activity_document
                ON document_activity(document_id, id DESC)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_document
                ON document_chunks(document_id, version)
                """
            )
            db.execute(
                """
                INSERT OR IGNORE INTO document_versions (
                    document_id, version, storage_ref, content_type,
                    size_bytes, sha256, created_at, source
                )
                SELECT
                    id, version, 'files/' || stored_name, content_type,
                    size_bytes, sha256, created_at, source
                FROM documents
                """
            )

    @staticmethod
    def _ensure_column(
        db: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            db.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["trashed"] = bool(item["trashed"])
        item["favorite"] = bool(item.get("favorite", 0))
        item["encrypted"] = bool(item.get("encrypted", 0))
        item["encryption_status"] = (
            "AES-256-GCM" if item["encrypted"] else "не зашифрован"
        )
        try:
            item["tags"] = json.loads(item.get("tags_json") or "[]")
        except json.JSONDecodeError:
            item["tags"] = []
        item.pop("tags_json", None)
        item["allowed_ai_access"] = sorted(
            AI_ACCESS_BY_CONFIDENTIALITY.get(
                item["confidentiality"],
                {"denied"},
            )
        )
        item["ai_ready_for_current_version"] = bool(
            item["indexed_version"]
            and item["indexed_version"] == item["version"]
            and item["ai_index_status"] == "ready"
        )
        return item

    @staticmethod
    def _folder_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["trashed"] = bool(item["trashed"])
        return item

    def _log(
        self,
        db: sqlite3.Connection,
        action: str,
        *,
        document_id: str | None = None,
        details: str = "",
    ) -> None:
        db.execute(
            """
            INSERT INTO document_activity (
                document_id, action, details, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (document_id, action, details[:2_000], utc_now()),
        )

    def _validate_folder(
        self,
        db: sqlite3.Connection,
        folder_id: str | None,
    ) -> None:
        if folder_id is None:
            return
        row = db.execute(
            "SELECT id FROM folders WHERE id = ? AND trashed = 0",
            (folder_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Папка не найдена.")

    def create_folder(
        self,
        name: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Название папки не может быть пустым.")
        folder_id = "TORY-FOLDER-" + uuid4().hex.upper()
        now = utc_now()
        with self._connect() as db:
            self._validate_folder(db, parent_id)
            db.execute(
                """
                INSERT INTO folders (
                    id, name, parent_id, created_at, updated_at, trashed
                )
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (folder_id, cleaned[:255], parent_id, now, now),
            )
            self._log(db, "folder_created", details=cleaned)
        return self.get_folder(folder_id)

    def get_folder(self, folder_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM folders WHERE id = ? AND trashed = 0",
                (folder_id,),
            ).fetchone()
        if row is None:
            raise KeyError(folder_id)
        return self._folder_row(row)

    def list_folders(
        self,
        *,
        parent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            if parent_id is None:
                rows = db.execute(
                    """
                    SELECT * FROM folders
                    WHERE parent_id IS NULL AND trashed = 0
                    ORDER BY name COLLATE NOCASE
                    """
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM folders
                    WHERE parent_id = ? AND trashed = 0
                    ORDER BY name COLLATE NOCASE
                    """,
                    (parent_id,),
                ).fetchall()
        return [self._folder_row(row) for row in rows]

    def rename_folder(self, folder_id: str, name: str) -> dict[str, Any]:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Название папки не может быть пустым.")
        with self._connect() as db:
            result = db.execute(
                """
                UPDATE folders
                SET name = ?, updated_at = ?
                WHERE id = ? AND trashed = 0
                """,
                (cleaned[:255], utc_now(), folder_id),
            )
            if result.rowcount < 1:
                raise KeyError(folder_id)
            self._log(db, "folder_renamed", details=cleaned)
        return self.get_folder(folder_id)

    def register_upload(
        self,
        temp_path: Path,
        *,
        name: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        document_id = "TORY-DOC-" + uuid4().hex.upper()
        suffix = Path(name).suffix[:16]
        stored_name = document_id + suffix
        destination = self.files_dir / stored_name
        now = utc_now()

        with self._connect() as db:
            self._validate_folder(db, folder_id)

        os.replace(temp_path, destination)
        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO documents (
                        id, name, original_name, stored_name, content_type,
                        size_bytes, sha256, scope, confidentiality, ai_access,
                        ai_index_status, version, source, created_at, updated_at,
                        folder_id, favorite, description, tags_json, trashed
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, 'personal', 'personal', 'denied',
                        'blocked', 1, 'upload', ?, ?, ?, 0, '', '[]', 0
                    )
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
                        folder_id,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO document_versions (
                        document_id, version, storage_ref, content_type,
                        size_bytes, sha256, created_at, source
                    )
                    VALUES (?, 1, ?, ?, ?, ?, ?, 'upload')
                    """,
                    (
                        document_id,
                        f"files/{stored_name}",
                        content_type or "application/octet-stream",
                        size_bytes,
                        sha256,
                        now,
                    ),
                )
                self._log(
                    db,
                    "uploaded",
                    document_id=document_id,
                    details=name,
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return self.get(document_id)

    def get(
        self,
        document_id: str,
        *,
        include_trashed: bool = False,
    ) -> dict[str, Any]:
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
        folder_id: str | None = None,
        favorites_only: bool = False,
        sort: str = "updated",
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        sql = "SELECT * FROM documents WHERE trashed = 0"
        if folder_id is None:
            sql += " AND folder_id IS NULL"
        else:
            sql += " AND folder_id = ?"
            params.append(folder_id)
        if favorites_only:
            sql += " AND favorite = 1"
        cleaned = query.strip()
        if cleaned:
            pattern = f"%{cleaned}%"
            sql += (
                " AND (name LIKE ? OR id LIKE ? OR content_type LIKE ?"
                " OR sha256 LIKE ? OR COALESCE(project_id, '') LIKE ?"
                " OR description LIKE ? OR tags_json LIKE ?)"
            )
            params.extend([pattern] * 7)

        order = {
            "name": "name COLLATE NOCASE ASC",
            "size": "size_bytes DESC",
            "created": "created_at DESC",
            "updated": "updated_at DESC",
        }.get(sort, "updated_at DESC")
        sql += f" ORDER BY {order} LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [self._row(row) for row in rows]

    def list_trashed(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM documents
                WHERE trashed = 1
                ORDER BY trashed_at DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    SUM(CASE WHEN trashed = 0 THEN 1 ELSE 0 END) AS total,
                    COALESCE(
                        SUM(CASE WHEN trashed = 0 THEN size_bytes ELSE 0 END),
                        0
                    ) AS total_bytes,
                    SUM(
                        CASE
                            WHEN trashed = 0 AND ai_access != 'denied'
                            THEN 1 ELSE 0
                        END
                    ) AS ai_allowed,
                    SUM(
                        CASE
                            WHEN trashed = 0
                            AND confidentiality IN (
                                'confidential',
                                'highly_protected'
                            )
                            THEN 1 ELSE 0
                        END
                    ) AS protected,
                    SUM(
                        CASE WHEN trashed = 0 AND favorite = 1 THEN 1 ELSE 0 END
                    ) AS favorites,
                    SUM(CASE WHEN trashed = 1 THEN 1 ELSE 0 END) AS trash
                FROM documents
                """
            ).fetchone()
            folders = db.execute(
                "SELECT COUNT(*) AS count FROM folders WHERE trashed = 0"
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "ai_allowed": int(row["ai_allowed"] or 0),
            "protected": int(row["protected"] or 0),
            "favorites": int(row["favorites"] or 0),
            "trash": int(row["trash"] or 0),
            "folders": int(folders["count"] or 0),
        }

    def update_document(
        self,
        document_id: str,
        *,
        name: str | None = None,
        folder_id: str | None | object = ...,
        favorite: bool | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        current = self.get(document_id)
        next_name = current["name"] if name is None else name.strip()
        if not next_name:
            raise ValueError("Название документа не может быть пустым.")
        next_folder = current["folder_id"] if folder_id is ... else folder_id
        next_favorite = current["favorite"] if favorite is None else favorite
        next_description = (
            current["description"] if description is None else description.strip()
        )
        next_tags = current["tags"] if tags is None else [
            tag.strip()[:80]
            for tag in tags
            if tag.strip()
        ][:50]

        with self._connect() as db:
            self._validate_folder(db, next_folder)
            db.execute(
                """
                UPDATE documents
                SET name = ?, folder_id = ?, favorite = ?, description = ?,
                    tags_json = ?, updated_at = ?
                WHERE id = ? AND trashed = 0
                """,
                (
                    next_name[:255],
                    next_folder,
                    int(next_favorite),
                    next_description[:5_000],
                    json.dumps(next_tags, ensure_ascii=False),
                    utc_now(),
                    document_id,
                ),
            )
            self._log(
                db,
                "document_updated",
                document_id=document_id,
                details=next_name,
            )
        return self.get(document_id)

    def _document_storage_paths(
        self,
        document_id: str,
    ) -> list[Path]:
        item = self.get(document_id, include_trashed=True)
        paths: list[Path] = []
        current_base = self.trash_dir if item["trashed"] else self.files_dir
        current = current_base / item["stored_name"]
        if current.is_file():
            paths.append(current)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT storage_ref
                FROM document_versions
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchall()
        for row in rows:
            path = self.root_dir / row["storage_ref"]
            if path.is_file() and path not in paths:
                paths.append(path)
        return paths

    def _set_document_encryption(
        self,
        document_id: str,
        *,
        enabled: bool,
    ) -> None:
        if self.vault is None:
            raise RuntimeError("Сейф Тори недоступен.")
        aad = document_id.encode("utf-8")
        for path in self._document_storage_paths(document_id):
            if enabled:
                self.vault.encrypt_file(path, aad=aad)
            else:
                self.vault.decrypt_file(path, aad=aad)
        with self._connect() as db:
            db.execute(
                "UPDATE documents SET encrypted = ? WHERE id = ?",
                (int(enabled), document_id),
            )
            self._log(
                db,
                "encryption_enabled" if enabled else "encryption_disabled",
                document_id=document_id,
                details="AES-256-GCM" if enabled else "plaintext",
            )

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
        next_project = (
            project_id
            if project_id is not None
            else current["project_id"]
        )

        if next_ai_access not in AI_ACCESS_LEVELS:
            raise ValueError("Недопустимый уровень доступа ИИ.")
        if next_confidentiality not in CONFIDENTIALITY_LEVELS:
            raise ValueError("Недопустимый уровень конфиденциальности.")
        if next_ai_access not in AI_ACCESS_BY_CONFIDENTIALITY[next_confidentiality]:
            raise ValueError(
                "Этот уровень конфиденциальности не разрешает выбранный "
                "доступ ИИ."
            )
        if next_scope not in SCOPES:
            raise ValueError("Недопустимый контекст документа.")
        if next_scope == "personal":
            next_project = None
        elif not next_project:
            raise ValueError("Для связи с проектом требуется project_id.")

        wants_encryption = next_confidentiality == "highly_protected"
        if wants_encryption and not current["encrypted"]:
            self._set_document_encryption(document_id, enabled=True)
        elif not wants_encryption and current["encrypted"]:
            self._set_document_encryption(document_id, enabled=False)

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
            if next_ai_access == "denied":
                db.execute(
                    "DELETE FROM document_chunks WHERE document_id = ?",
                    (document_id,),
                )
            self._log(
                db,
                "passport_updated",
                document_id=document_id,
                details=(
                    f"confidentiality={next_confidentiality};"
                    f"ai_access={next_ai_access};scope={next_scope}"
                ),
            )
        return self.get(document_id)

    def materialize_plaintext(
        self,
        document_id: str,
        *,
        include_trashed: bool = False,
    ) -> tuple[Path, Path | None]:
        item = self.get(
            document_id,
            include_trashed=include_trashed,
        )
        source = self.content_path(
            document_id,
            include_trashed=include_trashed,
        )
        if not item["encrypted"]:
            return source, None
        if self.vault is None:
            raise PermissionError("Сейф Тори недоступен.")
        destination = self.incoming_dir / (
            f"{uuid4().hex}{Path(item['name']).suffix}.plain"
        )
        try:
            self.vault.materialize(
                source,
                destination,
                aad=document_id.encode("utf-8"),
            )
        except RuntimeError as exc:
            raise PermissionError(str(exc)) from exc
        return destination, destination

    def content_path(
        self,
        document_id: str,
        *,
        include_trashed: bool = False,
    ) -> Path:
        item = self.get(document_id, include_trashed=include_trashed)
        base = self.trash_dir if item["trashed"] else self.files_dir
        path = base / item["stored_name"]
        if not path.is_file():
            raise FileNotFoundError(document_id)
        return path

    def verify_integrity(self, document_id: str) -> dict[str, Any]:
        item = self.get(document_id)
        path, cleanup = self.materialize_plaintext(document_id)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size_bytes += len(chunk)
                    digest.update(chunk)
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)

        actual_sha256 = digest.hexdigest()
        ok = (
            size_bytes == item["size_bytes"]
            and actual_sha256 == item["sha256"]
        )
        checked_at = utc_now()
        with self._connect() as db:
            db.execute(
                """
                UPDATE documents
                SET last_integrity_at = ?
                WHERE id = ?
                """,
                (checked_at, document_id),
            )
            self._log(
                db,
                "integrity_verified",
                document_id=document_id,
                details="ok" if ok else "mismatch",
            )
        return {
            "document_id": document_id,
            "ok": ok,
            "expected_sha256": item["sha256"],
            "actual_sha256": actual_sha256,
            "expected_size_bytes": item["size_bytes"],
            "actual_size_bytes": size_bytes,
            "checked_at": checked_at,
        }

    def _archive_current(
        self,
        db: sqlite3.Connection,
        item: dict[str, Any],
    ) -> None:
        source = self.files_dir / item["stored_name"]
        target_dir = self.versions_dir / item["id"]
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(item["stored_name"]).suffix
        target = target_dir / f"v{item['version']}{suffix}"
        if source.exists():
            shutil.move(str(source), str(target))
        relative = target.relative_to(self.root_dir).as_posix()
        db.execute(
            """
            UPDATE document_versions
            SET storage_ref = ?
            WHERE document_id = ? AND version = ?
            """,
            (relative, item["id"], item["version"]),
        )

    def add_version(
        self,
        document_id: str,
        temp_path: Path,
        *,
        name: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        current = self.get(document_id)
        new_version = int(current["version"]) + 1
        destination = self.files_dir / current["stored_name"]
        now = utc_now()

        if current["encrypted"]:
            if self.vault is None:
                raise PermissionError("Сейф Тори недоступен.")
            try:
                self.vault.encrypt_file(
                    temp_path,
                    aad=document_id.encode("utf-8"),
                )
            except RuntimeError as exc:
                raise PermissionError(str(exc)) from exc

        with self._connect() as db:
            self._archive_current(db, current)
            os.replace(temp_path, destination)
            db.execute(
                """
                UPDATE documents
                SET name = ?, content_type = ?, size_bytes = ?, sha256 = ?,
                    version = ?, indexed_version = NULL,
                    ai_index_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name[:255],
                    content_type or "application/octet-stream",
                    size_bytes,
                    sha256,
                    new_version,
                    (
                        "blocked"
                        if current["ai_access"] == "denied"
                        else "needs_indexing"
                    ),
                    now,
                    document_id,
                ),
            )
            db.execute(
                """
                INSERT INTO document_versions (
                    document_id, version, storage_ref, content_type,
                    size_bytes, sha256, created_at, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'new_version')
                """,
                (
                    document_id,
                    new_version,
                    f"files/{current['stored_name']}",
                    content_type or "application/octet-stream",
                    size_bytes,
                    sha256,
                    now,
                ),
            )
            self._log(
                db,
                "version_added",
                document_id=document_id,
                details=f"v{new_version}",
            )
        return self.get(document_id)

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        self.get(document_id, include_trashed=True)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = ?
                ORDER BY version DESC
                """,
                (document_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_version(
        self,
        document_id: str,
        version: int,
    ) -> dict[str, Any]:
        current = self.get(document_id)
        if version == current["version"]:
            return current
        with self._connect() as db:
            selected = db.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = ? AND version = ?
                """,
                (document_id, version),
            ).fetchone()
            if selected is None:
                raise KeyError(f"{document_id}:{version}")

            source = self.root_dir / selected["storage_ref"]
            if not source.is_file():
                raise FileNotFoundError(str(source))

            self._archive_current(db, current)
            destination = self.files_dir / current["stored_name"]
            shutil.copy2(source, destination)
            next_version = int(current["version"]) + 1
            now = utc_now()
            db.execute(
                """
                UPDATE documents
                SET content_type = ?, size_bytes = ?, sha256 = ?,
                    version = ?, indexed_version = NULL,
                    ai_index_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    selected["content_type"],
                    selected["size_bytes"],
                    selected["sha256"],
                    next_version,
                    (
                        "blocked"
                        if current["ai_access"] == "denied"
                        else "needs_indexing"
                    ),
                    now,
                    document_id,
                ),
            )
            db.execute(
                """
                INSERT INTO document_versions (
                    document_id, version, storage_ref, content_type,
                    size_bytes, sha256, created_at, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    next_version,
                    f"files/{current['stored_name']}",
                    selected["content_type"],
                    selected["size_bytes"],
                    selected["sha256"],
                    now,
                    f"restored_from_v{version}",
                ),
            )
            self._log(
                db,
                "version_restored",
                document_id=document_id,
                details=f"v{version} -> v{next_version}",
            )
        return self.get(document_id)

    def replace_chunks(
        self,
        document_id: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        item = self.get(document_id)
        if item["ai_access"] not in {"read", "answer", "memory", "full"}:
            raise PermissionError(
                "Паспорт документа не разрешает читать его содержимое."
            )
        with self._connect() as db:
            db.execute(
                "DELETE FROM document_chunks WHERE document_id = ?",
                (document_id,),
            )
            for number, chunk in enumerate(chunks, start=1):
                db.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id, version, chunk_no, label, page_no, text
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        item["version"],
                        number,
                        str(chunk["label"])[:300],
                        chunk.get("page"),
                        str(chunk["text"]),
                    ),
                )
            db.execute(
                """
                UPDATE documents
                SET indexed_version = ?, ai_index_status = 'ready',
                    updated_at = ?
                WHERE id = ?
                """,
                (item["version"], utc_now(), document_id),
            )
            self._log(
                db,
                "indexed",
                document_id=document_id,
                details=f"{len(chunks)} chunks; v{item['version']}",
            )
        return self.get(document_id)

    def document_chunks(
        self,
        document_id: str,
        *,
        query: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        item = self.get(document_id)
        if (
            item["ai_index_status"] != "ready"
            or item["indexed_version"] != item["version"]
        ):
            return []
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT chunk_no, label, page_no, text
                FROM document_chunks
                WHERE document_id = ? AND version = ?
                ORDER BY chunk_no
                """,
                (document_id, item["version"]),
            ).fetchall()
        chunks = [dict(row) for row in rows]
        if not query.strip():
            return chunks[:limit]
        terms = {
            term.lower()
            for term in query.replace("\n", " ").split(" ")
            if len(term.strip()) >= 2
        }
        for chunk in chunks:
            haystack = chunk["text"].lower()
            chunk["_score"] = sum(
                haystack.count(term)
                for term in terms
            )
        chunks.sort(
            key=lambda chunk: (
                chunk.get("_score", 0),
                -chunk["chunk_no"],
            ),
            reverse=True,
        )
        for chunk in chunks:
            chunk.pop("_score", None)
        return chunks[:limit]

    def search_chunks(
        self,
        query: str,
        *,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        cleaned = query.strip()
        if not cleaned:
            return []
        terms = {
            term.lower()
            for term in cleaned.replace("\n", " ").split(" ")
            if len(term.strip()) >= 2
        }
        if not terms:
            return []
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    c.document_id, c.version, c.chunk_no, c.label,
                    c.page_no, c.text, d.name, d.scope, d.project_id,
                    d.confidentiality, d.ai_access
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.trashed = 0
                  AND d.ai_index_status = 'ready'
                  AND d.indexed_version = d.version
                  AND d.ai_access IN ('read', 'answer', 'memory', 'full')
                """
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            haystack = (
                item["name"] + "\n" + item["text"]
            ).lower()
            score = sum(haystack.count(term) for term in terms)
            if score < 1:
                continue
            item["score"] = score
            item["snippet"] = item.pop("text")[:700]
            results.append(item)
        results.sort(
            key=lambda item: (item["score"], item["document_id"]),
            reverse=True,
        )
        return results[:limit]

    def activity(
        self,
        document_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.get(document_id, include_trashed=True)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, action, details, created_at
                FROM document_activity
                WHERE document_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (document_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def trash(self, document_id: str) -> dict[str, Any]:
        item = self.get(document_id)
        source = self.files_dir / item["stored_name"]
        destination = self.trash_dir / item["stored_name"]
        if source.exists():
            shutil.move(str(source), str(destination))
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """
                UPDATE documents
                SET trashed = 1, trashed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, document_id),
            )
            self._log(
                db,
                "trashed",
                document_id=document_id,
                details=item["name"],
            )
        return self.get(document_id, include_trashed=True)

    def restore(self, document_id: str) -> dict[str, Any]:
        item = self.get(document_id, include_trashed=True)
        if not item["trashed"]:
            return item
        source = self.trash_dir / item["stored_name"]
        destination = self.files_dir / item["stored_name"]
        if not source.is_file():
            raise FileNotFoundError(document_id)
        shutil.move(str(source), str(destination))
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """
                UPDATE documents
                SET trashed = 0, trashed_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, document_id),
            )
            self._log(
                db,
                "restored",
                document_id=document_id,
                details=item["name"],
            )
        return self.get(document_id)
