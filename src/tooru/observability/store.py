from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from tooru.observability.context import current_observation


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ObservabilityStore:
    """Persistent, privacy-conscious execution telemetry for Dragon Tory."""

    def __init__(
        self,
        db_path: Path,
        *,
        retention_days: int = 30,
    ) -> None:
        self.db_path = db_path
        self.retention_days = max(1, int(retention_days))

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def initialize(self) -> None:
        now = utc_now()
        now_ms = int(time.time() * 1000)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS observability_events (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    module TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_type TEXT,
                    source_id TEXT,
                    document_id TEXT,
                    memory_id TEXT,
                    provider TEXT,
                    model TEXT,
                    duration_ms REAL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    started_epoch_ms INTEGER NOT NULL,
                    finished_epoch_ms INTEGER
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_observability_recent
                ON observability_events(started_epoch_ms DESC)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_observability_trace
                ON observability_events(trace_id, started_epoch_ms)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_observability_status
                ON observability_events(status, started_epoch_ms DESC)
                """
            )
            db.execute(
                """
                UPDATE observability_events
                SET status = 'interrupted',
                    finished_at = ?,
                    finished_epoch_ms = ?,
                    message = CASE
                        WHEN message = '' THEN 'Прервано перезапуском Dragon Tory.'
                        ELSE message
                    END
                WHERE status = 'running'
                """,
                (now, now_ms),
            )
        self.cleanup()

    def cleanup(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=self.retention_days)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM observability_events WHERE started_epoch_ms < ?",
                (cutoff_ms,),
            )
            return int(cursor.rowcount or 0)

    def start_span(
        self,
        *,
        category: str,
        stage: str,
        operation: str,
        module: str | None = None,
        trace_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        document_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> str:
        context = current_observation()
        event_id = uuid4().hex
        resolved_trace = trace_id or context.trace_id or uuid4().hex
        now = utc_now()
        now_ms = int(time.time() * 1000)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO observability_events (
                    id, trace_id, category, stage, module, operation, status,
                    source_type, source_id, document_id, provider, model,
                    message, details_json, started_at, started_epoch_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    resolved_trace,
                    category[:80],
                    stage[:80],
                    (module or context.module or "system")[:120],
                    operation[:120],
                    source_type or context.source_type,
                    source_id or context.source_id,
                    document_id or context.document_id,
                    provider,
                    model,
                    message[:1_000],
                    json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now_ms,
                ),
            )
        return event_id

    def finish_span(
        self,
        event_id: str,
        *,
        status: str,
        message: str | None = None,
        retry_count: int | None = None,
        memory_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        duration_ms: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        now_ms = int(time.time() * 1000)
        with self._connect() as db:
            row = db.execute(
                "SELECT started_epoch_ms, details_json FROM observability_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                return
            measured = max(0.0, float(now_ms - int(row["started_epoch_ms"])))
            existing_details = json.loads(row["details_json"] or "{}")
            if details:
                existing_details.update(details)
            db.execute(
                """
                UPDATE observability_events
                SET status = ?,
                    finished_at = ?,
                    finished_epoch_ms = ?,
                    duration_ms = ?,
                    retry_count = COALESCE(?, retry_count),
                    memory_id = COALESCE(?, memory_id),
                    provider = COALESCE(?, provider),
                    model = COALESCE(?, model),
                    message = COALESCE(?, message),
                    details_json = ?
                WHERE id = ?
                """,
                (
                    status[:80],
                    now,
                    now_ms,
                    measured if duration_ms is None else max(0.0, float(duration_ms)),
                    retry_count,
                    memory_id,
                    provider,
                    model,
                    message[:1_000] if message is not None else None,
                    json.dumps(existing_details, ensure_ascii=False, sort_keys=True),
                    event_id,
                ),
            )

    def event(
        self,
        *,
        category: str,
        stage: str,
        operation: str,
        status: str,
        module: str | None = None,
        trace_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        document_id: str | None = None,
        memory_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        retry_count: int = 0,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> str:
        event_id = self.start_span(
            category=category,
            stage=stage,
            operation=operation,
            module=module,
            trace_id=trace_id,
            source_type=source_type,
            source_id=source_id,
            document_id=document_id,
            provider=provider,
            model=model,
            message=message,
            details=details,
        )
        self.finish_span(
            event_id,
            status=status,
            retry_count=retry_count,
            memory_id=memory_id,
            provider=provider,
            model=model,
            duration_ms=0,
        )
        return event_id

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        return item

    def recent(
        self,
        *,
        limit: int = 60,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        with self._connect() as db:
            if trace_id:
                rows = db.execute(
                    """
                    SELECT rowid AS sequence, * FROM observability_events
                    WHERE trace_id = ?
                    ORDER BY started_epoch_ms ASC, rowid ASC
                    LIMIT ?
                    """,
                    (trace_id, bounded),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT rowid AS sequence, * FROM observability_events
                    ORDER BY started_epoch_ms DESC, rowid DESC
                    LIMIT ?
                    """,
                    (bounded,),
                ).fetchall()
        return [self._decode(row) for row in rows]

    def summary(
        self,
        *,
        limit: int = 50,
        hours: int = 24,
    ) -> dict[str, Any]:
        bounded = max(10, min(int(limit), 200))
        cutoff_ms = int(
            (datetime.now(UTC) - timedelta(hours=max(1, min(hours, 168)))).timestamp()
            * 1000
        )
        with self._connect() as db:
            active_rows = db.execute(
                """
                SELECT rowid AS sequence, * FROM observability_events
                WHERE status = 'running'
                ORDER BY started_epoch_ms DESC, rowid DESC
                LIMIT 20
                """
            ).fetchall()
            aggregates = db.execute(
                """
                SELECT
                    SUM(CASE WHEN category = 'ai' THEN 1 ELSE 0 END) AS ai_requests,
                    AVG(CASE
                        WHEN category = 'ai' AND status = 'success'
                        THEN duration_ms
                    END) AS ai_avg_ms,
                    SUM(CASE WHEN category = 'ai' THEN retry_count ELSE 0 END)
                        AS ai_retries,
                    SUM(CASE
                        WHEN category = 'guardian' AND status = 'blocked'
                        THEN 1 ELSE 0 END) AS guardian_blocked,
                    SUM(CASE
                        WHEN category = 'guardian' AND status = 'pending'
                        THEN 1 ELSE 0 END) AS guardian_pending,
                    SUM(CASE
                        WHEN category = 'memory' AND status = 'success'
                        THEN 1 ELSE 0 END) AS memory_writes,
                    SUM(CASE
                        WHEN category = 'analysis' AND status = 'success'
                        THEN 1 ELSE 0 END) AS analyses
                FROM observability_events
                WHERE started_epoch_ms >= ?
                """,
                (cutoff_ms,),
            ).fetchone()
            rows = db.execute(
                """
                SELECT rowid AS sequence, * FROM observability_events
                WHERE started_epoch_ms >= ?
                ORDER BY started_epoch_ms DESC, rowid DESC
                LIMIT ?
                """,
                (cutoff_ms, bounded * 4),
            ).fetchall()

        events = [self._decode(row) for row in rows]
        trace_order: list[str] = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in events:
            trace = item["trace_id"]
            if trace not in grouped:
                grouped[trace] = []
                trace_order.append(trace)
            grouped[trace].append(item)

        chains: list[dict[str, Any]] = []
        for trace in trace_order[:10]:
            items = sorted(
                grouped[trace],
                key=lambda item: (item["started_epoch_ms"], item["sequence"]),
            )
            if not items:
                continue
            status = "success"
            statuses = {str(item["status"]) for item in items}
            if "error" in statuses:
                status = "error"
            elif "blocked" in statuses:
                status = "blocked"
            elif "pending" in statuses:
                status = "pending"
            elif "running" in statuses:
                status = "running"
            first = items[0]
            chains.append(
                {
                    "trace_id": trace,
                    "module": first["module"],
                    "source_type": first.get("source_type"),
                    "source_id": first.get("source_id"),
                    "document_id": first.get("document_id"),
                    "status": status,
                    "started_at": first["started_at"],
                    "steps": [
                        {
                            key: item.get(key)
                            for key in (
                                "id",
                                "category",
                                "stage",
                                "module",
                                "operation",
                                "status",
                                "document_id",
                                "memory_id",
                                "provider",
                                "model",
                                "duration_ms",
                                "retry_count",
                                "message",
                                "started_at",
                            )
                        }
                        for item in items[:12]
                    ],
                }
            )

        stats = dict(aggregates) if aggregates is not None else {}
        for key in (
            "ai_requests",
            "ai_retries",
            "guardian_blocked",
            "guardian_pending",
            "memory_writes",
            "analyses",
        ):
            stats[key] = int(stats.get(key) or 0)
        stats["ai_avg_ms"] = round(float(stats.get("ai_avg_ms") or 0.0), 1)

        active = [self._decode(row) for row in active_rows]
        return {
            "window_hours": max(1, min(hours, 168)),
            "active": active,
            "current": active[0] if active else None,
            "stats": stats,
            "chains": chains,
            "recent": events[:bounded],
        }
