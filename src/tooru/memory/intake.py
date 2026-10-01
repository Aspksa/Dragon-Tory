from __future__ import annotations

from dataclasses import dataclass

from tooru.memory.guardian import MemoryGuardian
from tooru.memory.models import (
    MemoryCreate,
    MemoryEvidenceCreate,
    MemoryGuardianDecision,
    MemoryGuardianOutcome,
    MemoryItem,
)


@dataclass(slots=True)
class MemoryIntakeResult:
    decision: MemoryGuardianDecision
    memory: MemoryItem | None

    @property
    def applied(self) -> bool:
        return self.decision.outcome is MemoryGuardianOutcome.APPLIED


class MemoryIntakeGateway:
    """Single entry point for durable memory created outside normal chat."""

    def __init__(self, guardian: MemoryGuardian) -> None:
        self.guardian = guardian

    def ingest(
        self,
        memory: MemoryCreate,
        *,
        reason: str,
        auto_apply: bool = True,
    ) -> MemoryIntakeResult:
        decision = self.guardian.ingest_structured(
            memory,
            reason=reason,
            auto_apply=auto_apply,
        )
        item = None
        if decision.memory_id is not None:
            item = self.guardian.intelligence.engine.get(
                decision.memory_id,
                memory.owner_id,
            )
            if memory.source_ref:
                self.guardian.intelligence.engine.add_evidence(
                    decision.memory_id,
                    MemoryEvidenceCreate(
                        source_type=memory.source,
                        source_ref=memory.source_ref,
                        excerpt=memory.content[:4_000],
                        extraction_method="structured-memory-intake",
                        confidence=memory.confidence,
                    ),
                    owner_id=memory.owner_id,
                )
        return MemoryIntakeResult(
            decision=decision,
            memory=item,
        )
