from dataclasses import dataclass

from tooru.memory.intelligence import MemoryIntelligence
from tooru.memory.models import (
    MemoryGuardianDecision,
    MemoryGuardianOutcome,
    MemoryGuardianRequest,
    MemoryGuardianResult,
    MemoryGuardianRisk,
    MemoryGuardianStatus,
    MemoryIntelligenceAction,
    MemoryIntelligenceRequest,
    MemoryItem,
    MemoryKind,
)
from tooru.memory.store import MemoryNotFoundError, SQLiteMemoryStore


@dataclass(slots=True)
class GuardianConfig:
    enabled: bool = True
    medium_importance: float = 0.65
    high_importance: float = 0.85
    min_confidence: float = 0.60


class MemoryGuardian:
    """Hidden policy layer controlling what Memory Intelligence may persist."""

    _critical_kinds = {
        MemoryKind.FACT,
        MemoryKind.PREFERENCE,
        MemoryKind.DECISION,
        MemoryKind.GOAL,
        MemoryKind.INSTRUCTION,
    }

    def __init__(
        self,
        intelligence: MemoryIntelligence,
        store: SQLiteMemoryStore,
        config: GuardianConfig,
    ):
        self.intelligence = intelligence
        self.store = store
        self.config = config

    async def process(self, request: MemoryGuardianRequest) -> MemoryGuardianResult:
        intelligence_request = MemoryIntelligenceRequest(
            owner_id=request.owner_id,
            scope=request.scope,
            project_id=request.project_id,
            messages=request.messages,
            auto_apply=False,
            use_ai=request.use_ai,
            primary_provider=request.primary_provider,
            reviewer_provider=request.reviewer_provider,
            device_id=request.device_id,
            session_id=request.session_id,
        )
        result = await self.intelligence.process(intelligence_request)

        guarded: list[MemoryGuardianDecision] = []
        applied: list[MemoryItem] = []

        for decision in result.decisions:
            risk, reason = self._classify(request, decision)
            outcome = self._outcome(
                request=request,
                decision=decision,
                risk=risk,
                analyzer=result.analyzer,
                reviewer=result.reviewer,
            )
            memory_id: str | None = None

            if outcome is MemoryGuardianOutcome.APPLIED:
                item = self.intelligence.apply_decision(
                    intelligence_request,
                    decision,
                    source="memory-guardian",
                )
                if item is not None:
                    applied.append(item)
                    memory_id = item.id

            guardian_decision = MemoryGuardianDecision(
                decision=decision,
                risk=risk,
                outcome=outcome,
                policy_reason=reason,
                memory_id=memory_id,
            )
            guarded.append(guardian_decision)
            self.store.record_guardian_event(
                owner_id=request.owner_id,
                scope=request.scope,
                project_id=request.project_id,
                guardian_decision=guardian_decision,
                analyzer=result.analyzer,
                reviewer=result.reviewer,
            )

        return MemoryGuardianResult(
            analyzer=result.analyzer,
            reviewer=result.reviewer,
            used_fallback=result.used_fallback,
            decisions=guarded,
            applied=applied,
            pending_count=sum(
                item.outcome is MemoryGuardianOutcome.PENDING for item in guarded
            ),
            blocked_count=sum(
                item.outcome is MemoryGuardianOutcome.BLOCKED for item in guarded
            ),
            ignored_count=sum(
                item.outcome is MemoryGuardianOutcome.IGNORED for item in guarded
            ),
        )

    def status(self) -> MemoryGuardianStatus:
        return self.store.guardian_status()

    def _classify(
        self,
        request: MemoryGuardianRequest,
        decision,
    ) -> tuple[MemoryGuardianRisk, str]:
        if decision.action is MemoryIntelligenceAction.IGNORE:
            return MemoryGuardianRisk.LOW, "Intelligence marked the content as non-durable."

        if decision.action is MemoryIntelligenceAction.UPDATE and decision.target_memory_id:
            try:
                target = self.intelligence.engine.get(
                    decision.target_memory_id,
                    request.owner_id,
                )
            except MemoryNotFoundError:
                target = None

            if target is not None and target.pinned:
                return (
                    MemoryGuardianRisk.PROTECTED,
                    "Pinned memory cannot be changed automatically.",
                )

        if (
            decision.kind is MemoryKind.INSTRUCTION
            or decision.importance >= self.config.high_importance
        ):
            return (
                MemoryGuardianRisk.HIGH,
                "High-impact memory requires reviewer confirmation.",
            )

        if (
            decision.action is MemoryIntelligenceAction.UPDATE
            or decision.kind in self._critical_kinds
            or decision.importance >= self.config.medium_importance
        ):
            return (
                MemoryGuardianRisk.MEDIUM,
                "Durable or updating memory requires stronger confidence.",
            )

        return MemoryGuardianRisk.LOW, "Low-risk durable memory can be automated."

    def _outcome(
        self,
        *,
        request: MemoryGuardianRequest,
        decision,
        risk: MemoryGuardianRisk,
        analyzer: str,
        reviewer: str | None,
    ) -> MemoryGuardianOutcome:
        if decision.action is MemoryIntelligenceAction.IGNORE:
            return MemoryGuardianOutcome.IGNORED

        if not self.config.enabled:
            return MemoryGuardianOutcome.PENDING

        if risk is MemoryGuardianRisk.PROTECTED:
            return MemoryGuardianOutcome.BLOCKED

        if decision.confidence < self.config.min_confidence:
            return MemoryGuardianOutcome.PENDING

        if not request.auto_apply:
            return MemoryGuardianOutcome.PENDING

        if risk is MemoryGuardianRisk.HIGH:
            return (
                MemoryGuardianOutcome.APPLIED
                if reviewer is not None
                else MemoryGuardianOutcome.PENDING
            )

        if risk is MemoryGuardianRisk.MEDIUM:
            if analyzer == "heuristic" and decision.kind in self._critical_kinds:
                return MemoryGuardianOutcome.PENDING
            return MemoryGuardianOutcome.APPLIED

        return MemoryGuardianOutcome.APPLIED
