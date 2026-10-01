import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ChatNotFoundError(LookupError):
    pass


class ChatStore:
    """Persistent local chat history, isolated from long-term memory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chats_updated
                    ON chats(updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_chat_messages_chat
                    ON chat_messages(chat_id, created_at);
                """
            )

    def create(self, title: str = "Новый чат") -> dict[str, Any]:
        chat_id = str(uuid.uuid4())
        now = self._now()
        clean_title = self._clean_title(title) or "Новый чат"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chats(id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, clean_title, now, now),
            )
        return self.get(chat_id)

    def get(self, chat_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.id) AS message_count
                FROM chats c
                LEFT JOIN chat_messages m ON m.chat_id = c.id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            raise ChatNotFoundError(chat_id)
        return dict(row)

    def list(
        self,
        *,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        params: list[Any] = []
        where = ""
        if query and query.strip():
            needle = f"%{query.strip().lower()}%"
            where = """
                WHERE lower(c.title) LIKE ?
                   OR EXISTS (
                       SELECT 1
                       FROM chat_messages sm
                       WHERE sm.chat_id = c.id
                         AND lower(sm.content) LIKE ?
                   )
            """
            params.extend([needle, needle])
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.id) AS message_count
                FROM chats c
                LEFT JOIN chat_messages m ON m.chat_id = c.id
                {where}
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def messages(
        self,
        chat_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.get(chat_id)
        sql = """
            SELECT id, chat_id, role, content, created_at, rowid AS sequence
            FROM chat_messages
            WHERE chat_id = ?
            ORDER BY rowid ASC
        """
        params: list[Any] = [chat_id]
        if limit is not None:
            safe_limit = max(1, min(limit, 500))
            sql = """
                SELECT *
                FROM (
                    SELECT
                        id,
                        chat_id,
                        role,
                        content,
                        created_at,
                        rowid AS sequence
                    FROM chat_messages
                    WHERE chat_id = ?
                    ORDER BY rowid DESC
                    LIMIT ?
                )
                ORDER BY sequence ASC
            """
            params.append(safe_limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def add_message(
        self,
        chat_id: str,
        *,
        role: str,
        content: str,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValueError("Unsupported chat role.")
        self.get(chat_id)
        message_id = str(uuid.uuid4())
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages(id, chat_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, chat_id, role, content, now),
            )
            conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (now, chat_id),
            )
        return {
            "id": message_id,
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "created_at": now,
        }

    def rename(self, chat_id: str, title: str) -> dict[str, Any]:
        clean = self._clean_title(title)
        if not clean:
            raise ValueError("Chat title cannot be empty.")
        now = self._now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE chats
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (clean, now, chat_id),
            )
            if cursor.rowcount == 0:
                raise ChatNotFoundError(chat_id)
        return self.get(chat_id)

    def auto_title(self, chat_id: str, message: str) -> dict[str, Any]:
        chat = self.get(chat_id)
        if chat["title"] != "Новый чат":
            return chat
        return self.rename(chat_id, self.title_from_message(message))

    def delete(self, chat_id: str) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM chats WHERE id = ?",
                (chat_id,),
            )
            if cursor.rowcount == 0:
                raise ChatNotFoundError(chat_id)

    def retry_context(
        self,
        chat_id: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        self.get(chat_id)
        with self._connect() as conn:
            user = conn.execute(
                """
                SELECT rowid AS sequence, content
                FROM chat_messages
                WHERE chat_id = ? AND role = 'user'
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
            if user is None:
                raise ValueError("В чате ещё нет сообщения пользователя.")

            rows = conn.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE chat_id = ? AND rowid < ?
                ORDER BY rowid ASC
                """,
                (chat_id, user["sequence"]),
            ).fetchall()
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE chat_id = ? AND rowid > ?
                """,
                (chat_id, user["sequence"]),
            )
            conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (self._now(), chat_id),
            )

        return str(user["content"]), [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            chats = conn.execute(
                "SELECT COUNT(*) AS count FROM chats"
            ).fetchone()
            messages = conn.execute(
                "SELECT COUNT(*) AS count FROM chat_messages"
            ).fetchone()
        return {
            "chats": int(chats["count"] or 0),
            "messages": int(messages["count"] or 0),
        }

    @staticmethod
    def title_from_message(message: str) -> str:
        clean = re.sub(r"\s+", " ", message).strip()
        clean = re.sub(r"^[#>*_\-\s]+", "", clean)
        if not clean:
            return "Новый чат"
        if len(clean) <= 64:
            return clean
        return clean[:61].rstrip(" ,.;:-") + "…"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _clean_title(title: str) -> str:
        return re.sub(r"\s+", " ", title).strip()[:120]

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
