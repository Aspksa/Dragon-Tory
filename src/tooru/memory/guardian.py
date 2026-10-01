import hashlib
import json
from dataclasses import dataclass
from typing import ClassVar
from uuid import uuid4

from tooru.memory.intelligence import MemoryIntelligence
from tooru.memory.models import (
    ConversationMessage,
    MemoryCreate,
    MemoryGuardianDecision,
    MemoryGuardianOutcome,
    MemoryGuardianQueueItem,
    MemoryGuardianQueueStatus,
    MemoryGuardianRequest,
    MemoryGuardianResult,
    MemoryGuardianRisk,
    MemoryGuardianStatus,
    MemoryIntelligenceAction,
    MemoryIntelligenceDecision,
    MemoryIntelligenceRequest,
    MemoryItem,
    MemoryKind,
)
from tooru.memory.store import MemoryNotFoundError, SQLiteMemoryStore
from tooru.observability.context import current_observation


@dataclass(slots=True)
class GuardianConfig:
    enabled: bool = True
    medium_importance: float = 0.65
    high_importance: float = 0.85
    min_confidence: float = 0.60
    max_attempts: int = 5
    retry_delay_seconds: int = 1800


class MemoryGuardian:
    """Hidden policy layer controlling what Memory Intelligence may persist."""

    _critical_kinds: ClassVar[set[MemoryKind]] = {
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
        observability=None,
    ):
        self.intelligence = intelligence
        self.store = store
        self.config = config
        self.observability = observability

    def ingest_structured(
        self,
        memory: MemoryCreate,
        *,
        reason: str = "Structured system memory intake.",
        auto_apply: bool = True,
    ) -> MemoryGuardianDecision:
        """Apply Guardian policy to an already-structured memory candidate."""
        request = MemoryGuardianRequest(
            owner_id=memory.owner_id,
            scope=memory.scope,
            project_id=memory.project_id,
            messages=[
                ConversationMessage(
                    role="tool",
                    content=(
                        f"Structured intake from {memory.source}: "
                        f"{memory.content[:2_000]}"
                    ),
                )
            ],
            auto_apply=auto_apply,
            use_ai=False,
            device_id=memory.device_id,
            session_id=memory.session_id,
        )
        decision = MemoryIntelligenceDecision(
            action=MemoryIntelligenceAction.CREATE,
            content=memory.content,
            kind=memory.kind,
            key=memory.key,
            importance=memory.importance,
            confidence=memory.confidence,
            tags=memory.tags,
            source=memory.source,
            source_ref=memory.source_ref,
            reason=reason,
        )
        risk, policy_reason = self._classify(request, decision)
        outcome = self._outcome(
            request=request,
            decision=decision,
            risk=risk,
            analyzer="structured-intake",
            reviewer=None,
        )
        memory_id: str | None = None
        queue_id: str | None = None

        if outcome is MemoryGuardianOutcome.APPLIED:
            item = self.intelligence.engine.add(memory)
            memory_id = item.id
        elif outcome is MemoryGuardianOutcome.PENDING:
            queued = self.store.queue_guardian_decision(
                fingerprint=self._fingerprint(request, decision),
                owner_id=memory.owner_id,
                scope=memory.scope,
                project_id=memory.project_id,
                risk=risk,
                decision=decision,
                messages=request.messages,
                analyzer="structured-intake",
                reviewer=None,
                max_attempts=self.config.max_attempts,
                retry_delay_seconds=self.config.retry_delay_seconds,
            )
            queue_id = queued.id

        guarded = MemoryGuardianDecision(
            decision=decision,
            risk=risk,
            outcome=outcome,
            policy_reason=policy_reason,
            memory_id=memory_id,
            queue_id=queue_id,
        )
        self._record_event(
            request=request,
            guardian_decision=guarded,
            analyzer="structured-intake",
            reviewer=None,
        )
        return guarded

    async def process(self, request: MemoryGuardianRequest) -> MemoryGuardianResult:
        intelligence_request = self._to_intelligence_request(request)
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
            queue_id: str | None = None

            if outcome is MemoryGuardianOutcome.APPLIED:
                item = self.intelligence.apply_decision(
                    intelligence_request,
                    decision,
                    source="memory-guardian",
                )
                if item is not None:
                    applied.append(item)
                    memory_id = item.id
            elif outcome is MemoryGuardianOutcome.PENDING:
                queue_item = self.store.queue_guardian_decision(
                    fingerprint=self._fingerprint(request, decision),
                    owner_id=request.owner_id,
                    scope=request.scope,
                    project_id=request.project_id,
                    risk=risk,
                    decision=decision,
                    messages=request.messages,
                    analyzer=result.analyzer,
                    reviewer=result.reviewer,
                    max_attempts=self.config.max_attempts,
                    retry_delay_seconds=self.config.retry_delay_seconds,
                )
                queue_id = queue_item.id

            guardian_decision = MemoryGuardianDecision(
                decision=decision,
                risk=risk,
                outcome=outcome,
                policy_reason=reason,
                memory_id=memory_id,
                queue_id=queue_id,
            )
            guarded.append(guardian_decision)
            self._record_event(
                request=request,
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

    def queue_items(
        self,
        *,
        status: MemoryGuardianQueueStatus | None = None,
        due_only: bool = False,
        limit: int = 50,
    ) -> list[MemoryGuardianQueueItem]:
        return self.store.guardian_queue_items(
            status=status,
            due_only=due_only,
            limit=limit,
        )

    async def retry_queue_item(self, queue_id: str) -> MemoryGuardianQueueItem:
        queued = self.store.get_guardian_queue_item(queue_id)
        if queued.status is not MemoryGuardianQueueStatus.PENDING:
            return queued
        if queued.attempts >= queued.max_attempts:
            return self.store.update_guardian_queue(
                queue_id,
                status=MemoryGuardianQueueStatus.DEAD,
                last_error="Maximum Guardian review attempts reached.",
            )

        reviewer_name = (
            queued.reviewer
            or self.intelligence.config.reviewer_provider
        )
        if not self.intelligence.router.has_provider(reviewer_name):
            return self.store.update_guardian_queue(
                queue_id,
                last_error=f"Reviewer unavailable: {reviewer_name}",
                retry_delay_seconds=self.config.retry_delay_seconds,
            )

        request = MemoryGuardianRequest(
            owner_id=queued.owner_id,
            scope=queued.scope,
            project_id=queued.project_id,
            messages=queued.messages,
            auto_apply=True,
            use_ai=True,
            primary_provider=queued.analyzer,
            reviewer_provider=reviewer_name,
        )
        intelligence_request = self._to_intelligence_request(request)

        try:
            reviewed = await self.intelligence.review_decisions(
                reviewer_name,
                intelligence_request,
                [queued.decision],
            )
            if not reviewed:
                raise ValueError("Reviewer returned no memory decisions")

            decision = reviewed[0]
            risk, reason = self._classify(request, decision)
            if decision.action is MemoryIntelligenceAction.IGNORE:
                updated = self.store.update_guardian_queue(
                    queue_id,
                    status=MemoryGuardianQueueStatus.REJECTED,
                    reviewer=reviewer_name,
                    increment_attempt=True,
                    last_error=None,
                )
                self._record_event(
                    request=request,
                    guardian_decision=MemoryGuardianDecision(
                        decision=decision,
                        risk=risk,
                        outcome=MemoryGuardianOutcome.IGNORED,
                        policy_reason="Reviewer rejected durable storage.",
                        queue_id=queue_id,
                    ),
                    analyzer=queued.analyzer,
                    reviewer=reviewer_name,
                )
                return updated

            if risk is MemoryGuardianRisk.PROTECTED:
                updated = self.store.update_guardian_queue(
                    queue_id,
                    status=MemoryGuardianQueueStatus.REJECTED,
                    reviewer=reviewer_name,
                    increment_attempt=True,
                    last_error="Reviewer targeted protected pinned memory.",
                )
                self._record_event(
                    request=request,
                    guardian_decision=MemoryGuardianDecision(
                        decision=decision,
                        risk=risk,
                        outcome=MemoryGuardianOutcome.BLOCKED,
                        policy_reason=reason,
                        queue_id=queue_id,
                    ),
                    analyzer=queued.analyzer,
                    reviewer=reviewer_name,
                )
                return updated

            if decision.confidence < self.config.min_confidence:
                raise ValueError(
                    "Reviewer confidence is below Guardian minimum threshold"
                )

            memory = self.intelligence.apply_decision(
                intelligence_request,
                decision,
                source="memory-guardian-review",
            )
            updated = self.store.update_guardian_queue(
                queue_id,
                status=MemoryGuardianQueueStatus.APPLIED,
                reviewer=reviewer_name,
                increment_attempt=True,
                last_error=None,
            )
            self._record_event(
                request=request,
                guardian_decision=MemoryGuardianDecision(
                    decision=decision,
                    risk=risk,
                    outcome=MemoryGuardianOutcome.APPLIED,
                    policy_reason="Pending memory approved by reviewer.",
                    memory_id=memory.id if memory is not None else None,
                    queue_id=queue_id,
                ),
                analyzer=queued.analyzer,
                reviewer=reviewer_name,
            )
            return updated
        except Exception as exc:  # noqa: BLE001 - queue worker must persist retry state
            next_attempt = queued.attempts + 1
            status = (
                MemoryGuardianQueueStatus.DEAD
                if next_attempt >= queued.max_attempts
                else MemoryGuardianQueueStatus.PENDING
            )
            return self.store.update_guardian_queue(
                queue_id,
                status=status,
                reviewer=reviewer_name,
                increment_attempt=True,
                retry_delay_seconds=(
                    self.config.retry_delay_seconds
                    if status is MemoryGuardianQueueStatus.PENDING
                    else None
                ),
                last_error=f"{type(exc).__name__}: {exc}",
            )

    def approve_queue_item(
        self,
        queue_id: str,
        *,
        reason: str = "",
    ) -> MemoryGuardianQueueItem:
        queued = self.store.get_guardian_queue_item(queue_id)
        if queued.status is not MemoryGuardianQueueStatus.PENDING:
            return queued

        request = MemoryGuardianRequest(
            owner_id=queued.owner_id,
            scope=queued.scope,
            project_id=queued.project_id,
            messages=queued.messages,
            auto_apply=True,
            use_ai=False,
        )
        risk, policy_reason = self._classify(request, queued.decision)
        if risk is MemoryGuardianRisk.PROTECTED:
            raise ValueError("Protected pinned memory cannot be manually auto-overwritten")

        intelligence_request = self._to_intelligence_request(request)
        memory = self.intelligence.apply_decision(
            intelligence_request,
            queued.decision,
            source="memory-guardian-manual-approval",
        )
        updated = self.store.update_guardian_queue(
            queue_id,
            status=MemoryGuardianQueueStatus.APPLIED,
            last_error=None,
        )
        self._record_event(
            request=request,
            guardian_decision=MemoryGuardianDecision(
                decision=queued.decision,
                risk=risk,
                outcome=MemoryGuardianOutcome.APPLIED,
                policy_reason=reason or f"Manual approval. {policy_reason}",
                memory_id=memory.id if memory is not None else None,
                queue_id=queue_id,
            ),
            analyzer=queued.analyzer,
            reviewer="manual",
        )
        return updated

    def reject_queue_item(
        self,
        queue_id: str,
        *,
        reason: str = "",
    ) -> MemoryGuardianQueueItem:
        queued = self.store.get_guardian_queue_item(queue_id)
        if queued.status is not MemoryGuardianQueueStatus.PENDING:
            return queued
        updated = self.store.update_guardian_queue(
            queue_id,
            status=MemoryGuardianQueueStatus.REJECTED,
            last_error=reason or None,
        )
        request = MemoryGuardianRequest(
            owner_id=queued.owner_id,
            scope=queued.scope,
            project_id=queued.project_id,
            messages=queued.messages,
            auto_apply=False,
            use_ai=False,
        )
        self._record_event(
            request=request,
            guardian_decision=MemoryGuardianDecision(
                decision=queued.decision,
                risk=queued.risk,
                outcome=MemoryGuardianOutcome.IGNORED,
                policy_reason=reason or "Pending memory manually rejected.",
                queue_id=queue_id,
            ),
            analyzer=queued.analyzer,
            reviewer="manual",
        )
        return updated

    def _classify(
        self,
        request: MemoryGuardianRequest,
        decision: MemoryIntelligenceDecision,
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
        decision: MemoryIntelligenceDecision,
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

    def _record_event(
        self,
        *,
        request: MemoryGuardianRequest,
        guardian_decision: MemoryGuardianDecision,
        analyzer: str,
        reviewer: str | None,
    ) -> None:
        self.store.record_guardian_event(
            owner_id=request.owner_id,
            scope=request.scope,
            project_id=request.project_id,
            guardian_decision=guardian_decision,
            analyzer=analyzer,
            reviewer=reviewer,
        )
        if self.observability is None:
            return
        try:
            context = current_observation()
            trace_id = context.trace_id or uuid4().hex
            outcome = guardian_decision.outcome.value
            event_status = {
                "applied": "success",
                "pending": "pending",
                "blocked": "blocked",
                "ignored": "ignored",
            }.get(outcome, outcome)
            decision = guardian_decision.decision
            self.observability.event(
                category="guardian",
                stage="decision",
                operation=decision.action.value,
                status=event_status,
                module=context.module or "memory",
                trace_id=trace_id,
                source_type=context.source_type,
                source_id=context.source_id,
                document_id=context.document_id,
                memory_id=guardian_decision.memory_id,
                message=guardian_decision.policy_reason,
                details={
                    "risk": guardian_decision.risk.value,
                    "outcome": outcome,
                    "kind": decision.kind.value,
                    "key": decision.key,
                    "scope": request.scope.value,
                    "project_id": request.project_id,
                    "analyzer": analyzer,
                    "reviewer": reviewer,
                    "queue_id": guardian_decision.queue_id,
                },
            )
            if guardian_decision.memory_id:
                self.observability.event(
                    category="memory",
                    stage="memory",
                    operation=decision.action.value,
                    status="success",
                    module=context.module or "memory",
                    trace_id=trace_id,
                    source_type=context.source_type,
                    source_id=context.source_id,
                    document_id=context.document_id,
                    memory_id=guardian_decision.memory_id,
                    message="Запись сохранена в долговременную память.",
                    details={
                        "scope": request.scope.value,
                        "project_id": request.project_id,
                        "kind": decision.kind.value,
                        "key": decision.key,
                    },
                )
        except Exception:  # noqa: BLE001 - telemetry must never break memory
            return

    @staticmethod
    def _to_intelligence_request(
        request: MemoryGuardianRequest,
    ) -> MemoryIntelligenceRequest:
        return MemoryIntelligenceRequest(
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

    @staticmethod
    def _fingerprint(
        request: MemoryGuardianRequest,
        decision: MemoryIntelligenceDecision,
    ) -> str:
        payload = {
            "owner_id": request.owner_id,
            "scope": request.scope.value,
            "project_id": request.project_id,
            "action": decision.action.value,
            "kind": decision.kind.value,
            "key": decision.key,
            "content": " ".join(decision.content.lower().split()),
            "target_memory_id": decision.target_memory_id,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
