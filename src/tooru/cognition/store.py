from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from tooru.cognition.models import (
    GraphEdge,
    GraphNode,
    InsightSeverity,
    InsightStatus,
    ProactiveInsight,
    ReasoningExperience,
    ReasoningPolicy,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CognitionStore:
    """Local audited storage for reasoning learning, graph and proactive insights."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

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
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS reasoning_experiences (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    task_bucket TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    complexity REAL NOT NULL,
                    memory_uncertainty REAL NOT NULL,
                    contradiction_count INTEGER NOT NULL,
                    verifier_score REAL,
                    verifier_uncertainty REAL,
                    passed INTEGER,
                    escalated INTEGER NOT NULL DEFAULT 0,
                    ai_calls INTEGER NOT NULL DEFAULT 1,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    user_feedback TEXT,
                    feedback_note TEXT
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reasoning_experiences_recent
                ON reasoning_experiences(created_at DESC)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reasoning_experiences_bucket
                ON reasoning_experiences(task_bucket, created_at DESC)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS reasoning_policy (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    version INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL,
                    hybrid_complexity_threshold REAL NOT NULL,
                    tree_complexity_threshold REAL NOT NULL,
                    hybrid_uncertainty_threshold REAL NOT NULL,
                    tree_uncertainty_threshold REAL NOT NULL,
                    verifier_escalation_score REAL NOT NULL,
                    verifier_escalation_uncertainty REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS reasoning_policy_history (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    policy_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognition_insights (
                    id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    entity_refs_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    resolved_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cognition_insights_status
                ON cognition_insights(status, severity, last_seen_at DESC)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognition_graph_nodes (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    attributes_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cognition_graph_nodes_ref
                ON cognition_graph_nodes(kind, ref_id)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognition_graph_edges (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY(source_id) REFERENCES cognition_graph_nodes(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(target_id) REFERENCES cognition_graph_nodes(id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cognition_graph_edges_source
                ON cognition_graph_edges(source_id, kind)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cognition_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            exists = db.execute(
                "SELECT 1 FROM reasoning_policy WHERE singleton = 1"
            ).fetchone()
            if exists is None:
                policy = ReasoningPolicy(updated_at=utc_now())
                self._write_policy(db, policy)

    @staticmethod
    def _write_policy(
        db: sqlite3.Connection,
        policy: ReasoningPolicy,
    ) -> None:
        updated_at = policy.updated_at or utc_now()
        db.execute(
            """
            INSERT OR REPLACE INTO reasoning_policy (
                singleton, version, sample_count,
                hybrid_complexity_threshold, tree_complexity_threshold,
                hybrid_uncertainty_threshold, tree_uncertainty_threshold,
                verifier_escalation_score,
                verifier_escalation_uncertainty,
                updated_at, reason
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.version,
                policy.sample_count,
                policy.hybrid_complexity_threshold,
                policy.tree_complexity_threshold,
                policy.hybrid_uncertainty_threshold,
                policy.tree_uncertainty_threshold,
                policy.verifier_escalation_score,
                policy.verifier_escalation_uncertainty,
                updated_at,
                policy.reason,
            ),
        )

    def current_policy(self) -> ReasoningPolicy:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM reasoning_policy WHERE singleton = 1"
            ).fetchone()
        if row is None:
            policy = ReasoningPolicy(updated_at=utc_now())
            self.save_policy(policy, reason="initialize-default")
            return policy
        item = dict(row)
        item.pop("singleton", None)
        return ReasoningPolicy.model_validate(item)

    def save_policy(
        self,
        policy: ReasoningPolicy,
        *,
        reason: str,
    ) -> ReasoningPolicy:
        updated = policy.model_copy(
            update={
                "updated_at": utc_now(),
                "reason": reason[:1_000],
            }
        )
        with self._connect() as db:
            self._write_policy(db, updated)
            db.execute(
                """
                INSERT INTO reasoning_policy_history (
                    id, version, policy_json, created_at, reason
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    updated.version,
                    updated.model_dump_json(),
                    updated.updated_at,
                    reason[:1_000],
                ),
            )
        return updated

    def add_experience(
        self,
        *,
        task_bucket: str,
        mode: str,
        complexity: float,
        memory_uncertainty: float,
        contradiction_count: int,
        verifier_score: float | None,
        verifier_uncertainty: float | None,
        passed: bool | None,
        escalated: bool,
        ai_calls: int,
        duration_ms: float,
    ) -> ReasoningExperience:
        item = ReasoningExperience(
            id="COG-EXP-" + uuid4().hex.upper(),
            created_at=utc_now(),
            task_bucket=task_bucket[:120],
            mode=mode[:30],
            complexity=max(0.0, min(1.0, float(complexity))),
            memory_uncertainty=max(
                0.0,
                min(1.0, float(memory_uncertainty)),
            ),
            contradiction_count=max(0, int(contradiction_count)),
            verifier_score=(
                None
                if verifier_score is None
                else max(0.0, min(1.0, float(verifier_score)))
            ),
            verifier_uncertainty=(
                None
                if verifier_uncertainty is None
                else max(0.0, min(1.0, float(verifier_uncertainty)))
            ),
            passed=passed,
            escalated=bool(escalated),
            ai_calls=max(1, int(ai_calls)),
            duration_ms=max(0.0, float(duration_ms)),
        )
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO reasoning_experiences (
                    id, created_at, task_bucket, mode, complexity,
                    memory_uncertainty, contradiction_count,
                    verifier_score, verifier_uncertainty, passed,
                    escalated, ai_calls, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.created_at,
                    item.task_bucket,
                    item.mode,
                    item.complexity,
                    item.memory_uncertainty,
                    item.contradiction_count,
                    item.verifier_score,
                    item.verifier_uncertainty,
                    None if item.passed is None else int(item.passed),
                    int(item.escalated),
                    item.ai_calls,
                    item.duration_ms,
                ),
            )
        return item

    @staticmethod
    def _experience(row: sqlite3.Row) -> ReasoningExperience:
        item = dict(row)
        item["escalated"] = bool(item["escalated"])
        if item["passed"] is not None:
            item["passed"] = bool(item["passed"])
        return ReasoningExperience.model_validate(item)

    def experiences(
        self,
        *,
        limit: int = 500,
        task_bucket: str | None = None,
    ) -> list[ReasoningExperience]:
        bounded = max(1, min(int(limit), 5_000))
        with self._connect() as db:
            if task_bucket:
                rows = db.execute(
                    """
                    SELECT * FROM reasoning_experiences
                    WHERE task_bucket = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (task_bucket, bounded),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM reasoning_experiences
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (bounded,),
                ).fetchall()
        return [self._experience(row) for row in rows]

    def feedback(
        self,
        experience_id: str,
        *,
        feedback: str,
        note: str = "",
    ) -> ReasoningExperience:
        normalized = feedback.strip().casefold()
        if normalized not in {"helpful", "unhelpful", "corrected"}:
            raise ValueError("Unsupported reasoning feedback.")
        with self._connect() as db:
            result = db.execute(
                """
                UPDATE reasoning_experiences
                SET user_feedback = ?, feedback_note = ?
                WHERE id = ?
                """,
                (normalized, note.strip()[:4_000], experience_id),
            )
            if result.rowcount < 1:
                raise KeyError(experience_id)
            row = db.execute(
                "SELECT * FROM reasoning_experiences WHERE id = ?",
                (experience_id,),
            ).fetchone()
        if row is None:
            raise KeyError(experience_id)
        return self._experience(row)

    @staticmethod
    def _insight(row: sqlite3.Row) -> ProactiveInsight:
        item = dict(row)
        item["entity_refs"] = json.loads(item.pop("entity_refs_json") or "[]")
        item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
        return ProactiveInsight.model_validate(item)

    def upsert_insight(
        self,
        *,
        rule_id: str,
        severity: InsightSeverity,
        confidence: float,
        title: str,
        summary: str,
        fingerprint: str,
        entity_refs: list[str],
        evidence: list[dict[str, Any]],
    ) -> ProactiveInsight:
        now = utc_now()
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM cognition_insights WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing is None:
                insight_id = "COG-INS-" + uuid4().hex.upper()
                db.execute(
                    """
                    INSERT INTO cognition_insights (
                        id, rule_id, severity, confidence, title, summary,
                        fingerprint, status, entity_refs_json, evidence_json,
                        first_seen_at, last_seen_at, resolved_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, NULL)
                    """,
                    (
                        insight_id,
                        rule_id[:120],
                        severity.value,
                        max(0.0, min(1.0, float(confidence))),
                        title[:500],
                        summary[:5_000],
                        fingerprint[:500],
                        json.dumps(entity_refs[:30], ensure_ascii=False),
                        json.dumps(evidence[:50], ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            else:
                insight_id = str(existing["id"])
                status = str(existing["status"])
                if status == InsightStatus.RESOLVED.value:
                    status = InsightStatus.OPEN.value
                db.execute(
                    """
                    UPDATE cognition_insights
                    SET severity = ?, confidence = ?, title = ?, summary = ?,
                        status = ?, entity_refs_json = ?, evidence_json = ?,
                        last_seen_at = ?, resolved_at = NULL
                    WHERE id = ?
                    """,
                    (
                        severity.value,
                        max(0.0, min(1.0, float(confidence))),
                        title[:500],
                        summary[:5_000],
                        status,
                        json.dumps(entity_refs[:30], ensure_ascii=False),
                        json.dumps(evidence[:50], ensure_ascii=False),
                        now,
                        insight_id,
                    ),
                )
            row = db.execute(
                "SELECT * FROM cognition_insights WHERE id = ?",
                (insight_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Insight upsert failed.")
        return self._insight(row)

    def insights(
        self,
        *,
        status: InsightStatus | None = InsightStatus.OPEN,
        limit: int = 200,
    ) -> list[ProactiveInsight]:
        bounded = max(1, min(int(limit), 2_000))
        with self._connect() as db:
            if status is None:
                rows = db.execute(
                    """
                    SELECT * FROM cognition_insights
                    ORDER BY
                        CASE severity
                            WHEN 'critical' THEN 5
                            WHEN 'high' THEN 4
                            WHEN 'medium' THEN 3
                            WHEN 'low' THEN 2
                            ELSE 1
                        END DESC,
                        last_seen_at DESC
                    LIMIT ?
                    """,
                    (bounded,),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM cognition_insights
                    WHERE status = ?
                    ORDER BY
                        CASE severity
                            WHEN 'critical' THEN 5
                            WHEN 'high' THEN 4
                            WHEN 'medium' THEN 3
                            WHEN 'low' THEN 2
                            ELSE 1
                        END DESC,
                        last_seen_at DESC
                    LIMIT ?
                    """,
                    (status.value, bounded),
                ).fetchall()
        return [self._insight(row) for row in rows]

    def set_insight_status(
        self,
        insight_id: str,
        status: InsightStatus,
    ) -> ProactiveInsight:
        resolved_at = (
            utc_now()
            if status in {InsightStatus.RESOLVED, InsightStatus.DISMISSED}
            else None
        )
        with self._connect() as db:
            result = db.execute(
                """
                UPDATE cognition_insights
                SET status = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status.value, resolved_at, insight_id),
            )
            if result.rowcount < 1:
                raise KeyError(insight_id)
            row = db.execute(
                "SELECT * FROM cognition_insights WHERE id = ?",
                (insight_id,),
            ).fetchone()
        if row is None:
            raise KeyError(insight_id)
        return self._insight(row)

    def replace_graph(
        self,
        *,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM cognition_graph_edges")
            db.execute("DELETE FROM cognition_graph_nodes")
            db.executemany(
                """
                INSERT INTO cognition_graph_nodes (
                    id, kind, label, ref_id, attributes_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        node.id,
                        node.kind[:80],
                        node.label[:500],
                        node.ref_id[:500],
                        json.dumps(
                            node.attributes,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                    for node in nodes
                ],
            )
            db.executemany(
                """
                INSERT INTO cognition_graph_edges (
                    id, source_id, target_id, kind, confidence, evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.id,
                        edge.source_id,
                        edge.target_id,
                        edge.kind[:80],
                        edge.confidence,
                        json.dumps(edge.evidence, ensure_ascii=False),
                    )
                    for edge in edges
                ],
            )

    def graph(self, *, limit: int = 500) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 5_000))
        with self._connect() as db:
            node_rows = db.execute(
                """
                SELECT * FROM cognition_graph_nodes
                ORDER BY kind, label COLLATE NOCASE
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            node_ids = {str(row["id"]) for row in node_rows}
            edge_rows = db.execute(
                """
                SELECT * FROM cognition_graph_edges
                ORDER BY kind, id
                LIMIT ?
                """,
                (bounded * 4,),
            ).fetchall()
        nodes = [
            {
                **dict(row),
                "attributes": json.loads(row["attributes_json"] or "{}"),
            }
            for row in node_rows
        ]
        for item in nodes:
            item.pop("attributes_json", None)
        edges = []
        for row in edge_rows:
            if row["source_id"] not in node_ids or row["target_id"] not in node_ids:
                continue
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
            edges.append(item)
        return {"nodes": nodes, "edges": edges}

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO cognition_state(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key[:120], value[:10_000]),
            )

    def get_state(self, key: str) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM cognition_state WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row["value"])

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM reasoning_experiences) AS experiences,
                    (SELECT COUNT(*) FROM cognition_insights
                     WHERE status = 'open') AS open_insights,
                    (SELECT COUNT(*) FROM cognition_insights
                     WHERE status = 'open'
                       AND severity IN ('high', 'critical')) AS high_insights,
                    (SELECT COUNT(*) FROM cognition_graph_nodes) AS graph_nodes,
                    (SELECT COUNT(*) FROM cognition_graph_edges) AS graph_edges
                """
            ).fetchone()
        return {
            key: int(row[key] or 0)
            for key in (
                "experiences",
                "open_insights",
                "high_insights",
                "graph_nodes",
                "graph_edges",
            )
        }
