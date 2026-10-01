from __future__ import annotations

from datetime import UTC, datetime

from tooru.memory.models import (
    MemoryItem,
    MemoryLinkType,
    MemoryStatus,
    MemoryTruthAssessment,
    MemoryTruthStatus,
)
from tooru.memory.store import SQLiteMemoryStore


class MemoryTruthEngine:
    """Deterministic trust assessment over memory, evidence and graph links."""

    def __init__(self, store: SQLiteMemoryStore) -> None:
        self.store = store

    def assess(
        self,
        memory: MemoryItem,
        *,
        at: datetime | None = None,
    ) -> MemoryTruthAssessment:
        evidence = self.store.evidence_for(
            memory.id,
            owner_id=memory.owner_id,
            limit=100,
        )
        links = self.store.links_for(memory.id)
        conflicts = [
            link for link in links
            if link.relation is MemoryLinkType.CONTRADICTS
        ]
        supports = [
            link for link in links
            if link.relation is MemoryLinkType.SUPPORTS
        ]

        confidence_score = max(0.0, min(1.0, memory.confidence))
        evidence_score = (
            sum(item.confidence for item in evidence) / len(evidence)
            if evidence
            else 0.35
        )

        feedback_total = memory.helpful_count + memory.unhelpful_count
        feedback_score = (
            memory.helpful_count / feedback_total
            if feedback_total
            else 0.5
        )
        support_score = min(1.0, len(supports) / 3.0)
        source_reliability_score = self._source_reliability(
            memory,
            evidence,
        )
        temporal_status, temporal_score = self._temporal_state(
            memory,
            at=at or datetime.now(UTC),
        )
        conflict_penalty = min(0.30, 0.15 * len(conflicts))

        trust = (
            0.38 * confidence_score
            + 0.22 * evidence_score
            + 0.10 * feedback_score
            + 0.10 * temporal_score
            + 0.05 * support_score
            + 0.15 * source_reliability_score
            - conflict_penalty
        )
        trust = max(0.0, min(1.0, trust))

        reasons: list[str] = []
        if evidence:
            reasons.append(f"evidence:{len(evidence)}")
        else:
            reasons.append("evidence:none")
        if supports:
            reasons.append(f"supports:{len(supports)}")
        if conflicts:
            reasons.append(f"conflicts:{len(conflicts)}")
        reasons.append(f"temporal:{temporal_status.value}")
        reasons.append(
            f"source-reliability:{source_reliability_score:.3f}"
        )
        if memory.pinned:
            reasons.append("pinned")
        if feedback_total:
            reasons.append(
                f"feedback:{memory.helpful_count}/{feedback_total}"
            )

        return MemoryTruthAssessment(
            memory_id=memory.id,
            trust_score=round(trust, 6),
            confidence_score=round(confidence_score, 6),
            evidence_score=round(evidence_score, 6),
            feedback_score=round(feedback_score, 6),
            temporal_score=round(temporal_score, 6),
            support_score=round(support_score, 6),
            source_reliability_score=round(source_reliability_score, 6),
            conflict_penalty=round(conflict_penalty, 6),
            evidence_count=len(evidence),
            support_count=len(supports),
            conflict_count=len(conflicts),
            temporal_status=temporal_status,
            reasons=reasons,
        )

    def _source_reliability(self, memory: MemoryItem, evidence) -> float:
        defaults = {
            "user": 0.95,
            "document": 0.90,
            "service-memo": 0.90,
            "tooru-module-study": 0.82,
            "memory-guardian": 0.80,
            "chat-outcome": 0.72,
            "experience-learning": 0.70,
            "unknown": 0.50,
        }
        scores: list[float] = []
        for proof in evidence:
            learned = self.store.source_reliability(
                proof.source_type,
                proof.source_ref,
            )
            if learned is None:
                learned = self.store.source_reliability(
                    proof.source_type,
                    None,
                )
            scores.append(
                learned.reliability
                if learned is not None
                else defaults.get(proof.source_type, 0.60)
            )
        if not scores:
            learned = self.store.source_reliability(
                memory.source,
                memory.source_ref,
            )
            if learned is None:
                learned = self.store.source_reliability(
                    memory.source,
                    None,
                )
            if learned is not None:
                return learned.reliability
            return defaults.get(memory.source, 0.60)
        return sum(scores) / len(scores)

    @classmethod
    def temporal_relation(
        cls,
        newer: MemoryItem,
        older: MemoryItem,
    ) -> MemoryLinkType | None:
        new_start = cls._moment(newer.valid_from)
        new_end = cls._moment(newer.valid_to)
        old_start = cls._moment(older.valid_from)
        old_end = cls._moment(older.valid_to)

        if new_start is not None and old_end is not None and new_start > old_end:
            return MemoryLinkType.TEMPORAL_SUCCESSOR
        if new_end is not None and old_start is not None and new_end < old_start:
            return MemoryLinkType.TEMPORAL_PREDECESSOR
        return None

    @classmethod
    def _temporal_state(
        cls,
        memory: MemoryItem,
        *,
        at: datetime,
    ) -> tuple[MemoryTruthStatus, float]:
        if memory.status is MemoryStatus.SUPERSEDED:
            return MemoryTruthStatus.SUPERSEDED, 0.30

        start = cls._moment(memory.valid_from)
        end = cls._moment(memory.valid_to)
        if start is None and end is None:
            return MemoryTruthStatus.UNDATED, 0.75
        if start is not None and at < start:
            return MemoryTruthStatus.FUTURE, 0.40
        if end is not None and at > end:
            return MemoryTruthStatus.HISTORICAL, 0.55
        return MemoryTruthStatus.CURRENT, 1.0

    @staticmethod
    def _moment(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC)
