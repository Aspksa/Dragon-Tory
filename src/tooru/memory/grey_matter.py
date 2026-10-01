from __future__ import annotations

import re
from collections import deque
from typing import Any

from tooru.memory.engine import MemoryEngine
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.models import (
    EntityResolution,
    GoalProgress,
    GraphPathNode,
    GreyMatterReport,
    MemoryConsolidateRequest,
    MemoryCreate,
    MemoryKind,
    MemoryLinkType,
    MemoryScope,
    MemorySearch,
    MemoryUncertaintyAssessment,
    MemoryUncertaintyLevel,
    MemoryUpdate,
)


class GreyMatterService:
    """Higher cognition over durable memory without bypassing Guardian."""

    _correction_signal = re.compile(
        r"(?i)(?:"
        r"\bнет[, ]|"
        r"\bневерно\b|"
        r"\bнеправильно\b|"
        r"\bты\s+ошиб|"
        r"\bошиблась\b|"
        r"\bправильно\s+(?:так|будет)|"
        r"\bна\s+самом\s+деле\b|"
        r"\bисправ(?:ь|ление)"
        r")"
    )

    _entity_stop = {
        "ооо",
        "ао",
        "пао",
        "зао",
        "ип",
        "llc",
        "ltd",
        "inc",
        "corp",
        "company",
        "компания",
    }

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        intake: MemoryIntakeGateway,
    ) -> None:
        self.memory = memory
        self.store = memory.store
        self.intake = intake

    @staticmethod
    def normalize_entity(value: str) -> str:
        tokens = re.findall(
            r"[\w-]+",
            value.casefold().replace("ё", "е"),
            flags=re.UNICODE,
        )
        filtered = [
            token
            for token in tokens
            if token not in GreyMatterService._entity_stop
        ]
        return " ".join(sorted(filtered))

    def learn_entity_alias(
        self,
        canonical_memory_id: str,
        alias: str,
        *,
        owner_id: str = "local-user",
        confidence: float = 1.0,
    ):
        canonical = self.memory.get(canonical_memory_id, owner_id)
        if canonical.kind is not MemoryKind.ENTITY:
            raise ValueError("canonical memory must have kind=entity")
        normalized = self.normalize_entity(alias)
        if not normalized:
            raise ValueError("entity alias is empty after normalization")
        return self.store.add_entity_alias(
            owner_id=owner_id,
            scope=canonical.scope,
            project_id=canonical.project_id,
            canonical_memory_id=canonical.id,
            alias=alias.strip(),
            normalized_alias=normalized,
            confidence=confidence,
        )

    def resolve_entity(
        self,
        query: str,
        *,
        owner_id: str = "local-user",
        scope: MemoryScope = MemoryScope.PROJECT,
        project_id: str | None = "dragon-tory",
    ) -> EntityResolution:
        normalized = self.normalize_entity(query)
        aliases = self.store.entity_aliases(
            owner_id=owner_id,
            scope=scope,
            project_id=project_id,
            normalized_alias=normalized,
            limit=50,
        )
        if aliases:
            best = aliases[0]
            canonical = self.memory.get(best.canonical_memory_id, owner_id)
            return EntityResolution(
                query=query,
                canonical_memory_id=canonical.id,
                canonical_content=canonical.content,
                confidence=best.confidence,
                matched_aliases=[item.alias for item in aliases],
                candidate_ids=[
                    item.canonical_memory_id
                    for item in aliases
                ],
            )

        hits = self.memory.recall(
            MemorySearch(
                owner_id=owner_id,
                scope=scope,
                project_id=project_id,
                query=query,
                kind=MemoryKind.ENTITY,
                limit=8,
            ),
            track_usage=False,
        )
        candidate_ids = [hit.memory.id for hit in hits]
        if not hits:
            return EntityResolution(
                query=query,
                confidence=0.0,
                candidate_ids=[],
            )

        best = hits[0]
        confidence = max(
            0.0,
            min(
                1.0,
                0.55 * best.score
                + 0.30 * best.semantic_score
                + 0.15 * best.truth_score,
            ),
        )
        return EntityResolution(
            query=query,
            canonical_memory_id=best.memory.id if confidence >= 0.45 else None,
            canonical_content=(
                best.memory.content if confidence >= 0.45 else None
            ),
            confidence=round(confidence, 6),
            candidate_ids=candidate_ids,
        )

    def uncertainty(
        self,
        memory_id: str,
        *,
        owner_id: str = "local-user",
    ) -> MemoryUncertaintyAssessment:
        item = self.memory.get(memory_id, owner_id)
        truth = self.memory.truth(memory_id, owner_id=owner_id)
        conflicts = self.memory.links_for(
            memory_id,
            MemoryLinkType.CONTRADICTS,
        )
        alternatives: list[str] = []
        for link in conflicts[:20]:
            other_id = (
                link.target_id
                if link.source_id == memory_id
                else link.source_id
            )
            try:
                other = self.memory.get(other_id, owner_id)
            except LookupError:
                continue
            if (
                other.scope is item.scope
                and other.project_id == item.project_id
            ):
                alternatives.append(other.content[:800])

        score = 1.0 - truth.trust_score
        score += min(0.30, 0.10 * truth.conflict_count)
        if truth.evidence_count == 0:
            score += 0.08
        score = max(0.0, min(1.0, score))
        if score >= 0.60:
            level = MemoryUncertaintyLevel.HIGH
        elif score >= 0.32:
            level = MemoryUncertaintyLevel.MEDIUM
        else:
            level = MemoryUncertaintyLevel.LOW

        reasons = [
            f"trust:{truth.trust_score:.3f}",
            f"evidence:{truth.evidence_count}",
            f"conflicts:{truth.conflict_count}",
            f"source-reliability:{truth.source_reliability_score:.3f}",
        ]
        return MemoryUncertaintyAssessment(
            memory_id=memory_id,
            level=level,
            uncertainty_score=round(score, 6),
            trust_score=truth.trust_score,
            conflict_count=truth.conflict_count,
            evidence_count=truth.evidence_count,
            alternatives=alternatives,
            reasons=reasons,
        )

    def multi_hop(
        self,
        memory_id: str,
        *,
        owner_id: str = "local-user",
        depth: int = 3,
        limit: int = 100,
    ) -> list[GraphPathNode]:
        start = self.memory.get(memory_id, owner_id)
        max_depth = max(1, min(depth, 6))
        max_items = max(1, min(limit, 500))
        queue: deque[tuple[str, int, float, MemoryLinkType | None]] = deque(
            [(start.id, 0, 1.0, None)]
        )
        seen = {start.id}
        result: list[GraphPathNode] = []

        while queue and len(result) < max_items:
            current_id, current_depth, score, via = queue.popleft()
            current = self.memory.get(current_id, owner_id)
            result.append(
                GraphPathNode(
                    memory_id=current.id,
                    content=current.content[:2_000],
                    kind=current.kind,
                    depth=current_depth,
                    via=via,
                    score=round(max(0.0, min(1.0, score)), 6),
                )
            )
            if current_depth >= max_depth:
                continue
            for link in self.memory.links_for(current_id):
                other_id = (
                    link.target_id
                    if link.source_id == current_id
                    else link.source_id
                )
                if other_id in seen:
                    continue
                try:
                    other = self.memory.get(other_id, owner_id)
                except LookupError:
                    continue
                if (
                    other.scope is not start.scope
                    or other.project_id != start.project_id
                ):
                    continue
                seen.add(other_id)
                queue.append(
                    (
                        other_id,
                        current_depth + 1,
                        score * link.weight,
                        link.relation,
                    )
                )
        return result

    def link_task_to_goal(
        self,
        goal_id: str,
        task_id: str,
        *,
        owner_id: str = "local-user",
    ) -> None:
        goal = self.memory.get(goal_id, owner_id)
        task = self.memory.get(task_id, owner_id)
        if goal.kind is not MemoryKind.GOAL:
            raise ValueError("goal_id must reference goal memory")
        if task.kind is not MemoryKind.TASK:
            raise ValueError("task_id must reference task memory")
        self._same_scope(goal, task)
        self.store.add_link(
            task.id,
            goal.id,
            MemoryLinkType.PART_OF,
            1.0,
        )

    def link_task_dependency(
        self,
        task_id: str,
        dependency_id: str,
        *,
        owner_id: str = "local-user",
    ) -> None:
        task = self.memory.get(task_id, owner_id)
        dependency = self.memory.get(dependency_id, owner_id)
        if (
            task.kind is not MemoryKind.TASK
            or dependency.kind is not MemoryKind.TASK
        ):
            raise ValueError("task dependency requires two task memories")
        self._same_scope(task, dependency)
        self.store.add_link(
            task.id,
            dependency.id,
            MemoryLinkType.DEPENDS_ON,
            1.0,
        )

    def set_task_state(
        self,
        task_id: str,
        state: str,
        *,
        owner_id: str = "local-user",
    ):
        normalized = state.casefold().strip()
        if normalized not in {"open", "done", "blocked"}:
            raise ValueError("task state must be open, done or blocked")
        item = self.memory.get(task_id, owner_id)
        if item.kind is not MemoryKind.TASK:
            raise ValueError("memory must have kind=task")
        tags = [
            tag
            for tag in item.tags
            if not tag.startswith("task:")
        ]
        tags.append(f"task:{normalized}")
        return self.memory.update(
            task_id,
            owner_id,
            MemoryUpdate(
                tags=tags,
                expected_revision=item.revision,
            ),
        )

    def goal_progress(
        self,
        goal_id: str,
        *,
        owner_id: str = "local-user",
    ) -> GoalProgress:
        goal = self.memory.get(goal_id, owner_id)
        if goal.kind is not MemoryKind.GOAL:
            raise ValueError("memory must have kind=goal")
        tasks = []
        for link in self.memory.links_for(
            goal_id,
            MemoryLinkType.PART_OF,
        ):
            other_id = (
                link.source_id
                if link.target_id == goal_id
                else link.target_id
            )
            try:
                item = self.memory.get(other_id, owner_id)
            except LookupError:
                continue
            if (
                item.kind is MemoryKind.TASK
                and item.scope is goal.scope
                and item.project_id == goal.project_id
            ):
                tasks.append(item)

        done = [
            item for item in tasks
            if "task:done" in item.tags
        ]
        done_ids = {item.id for item in done}
        blocked: list[Any] = []
        open_items: list[Any] = []
        for item in tasks:
            if item.id in done_ids:
                continue
            explicit_block = "task:blocked" in item.tags
            unmet_dependency = False
            for link in self.memory.links_for(
                item.id,
                MemoryLinkType.DEPENDS_ON,
            ):
                dependency_id = (
                    link.target_id
                    if link.source_id == item.id
                    else link.source_id
                )
                if dependency_id not in done_ids:
                    unmet_dependency = True
                    break
            if explicit_block or unmet_dependency:
                blocked.append(item)
            else:
                open_items.append(item)
        completion = len(done) / len(tasks) if tasks else 0.0
        return GoalProgress(
            goal_id=goal.id,
            content=goal.content,
            completion=round(completion, 6),
            completed_tasks=len(done),
            open_tasks=len(open_items),
            blocked_tasks=len(blocked),
            task_ids=[item.id for item in tasks],
            next_actions=[item.content[:500] for item in open_items[:20]],
        )

    def record_causal_chain(
        self,
        *,
        problem: str,
        cause: str,
        action: str,
        result: str,
        owner_id: str = "local-user",
        scope: MemoryScope = MemoryScope.PROJECT,
        project_id: str | None = "dragon-tory",
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        specs = [
            ("problem", MemoryKind.EVENT, problem, 0.72),
            ("cause", MemoryKind.FACT, cause, 0.78),
            ("action", MemoryKind.DECISION, action, 0.74),
            ("result", MemoryKind.EPISODE, result, 0.70),
        ]
        created: dict[str, Any] = {}
        for role, kind, content, importance in specs:
            intake = self.intake.ingest(
                MemoryCreate(
                    owner_id=owner_id,
                    scope=scope,
                    project_id=project_id,
                    kind=kind,
                    content=content,
                    source="causal-memory",
                    source_ref=source_ref,
                    confidence=0.90,
                    importance=importance,
                    tags=["causal", f"causal:{role}"],
                ),
                reason=f"Causal memory component: {role}.",
            )
            created[role] = intake

        ids = {
            role: value.memory.id
            for role, value in created.items()
            if value.memory is not None
        }
        if {"cause", "problem"} <= ids.keys():
            self.store.add_link(
                ids["cause"],
                ids["problem"],
                MemoryLinkType.CAUSES,
                0.95,
            )
        if {"problem", "action"} <= ids.keys():
            self.store.add_link(
                ids["problem"],
                ids["action"],
                MemoryLinkType.REQUIRES,
                0.90,
            )
        if {"action", "result"} <= ids.keys():
            self.store.add_link(
                ids["action"],
                ids["result"],
                MemoryLinkType.CAUSES,
                0.90,
            )
        return {
            role: {
                "memory_id": value.memory.id if value.memory else None,
                "outcome": value.decision.outcome.value,
                "queue_id": value.decision.queue_id,
            }
            for role, value in created.items()
        }

    def learn_chat_correction(
        self,
        *,
        user_message: str,
        previous_assistant: str,
        session_id: str | None = None,
        owner_id: str = "local-user",
        project_id: str = "dragon-tory",
    ) -> str:
        if not self._correction_signal.search(user_message):
            return "correction:no-signal"
        if not previous_assistant.strip():
            return "correction:no-previous-answer"

        lesson = self.intake.ingest(
            MemoryCreate(
                owner_id=owner_id,
                scope=MemoryScope.PROJECT,
                project_id=project_id,
                kind=MemoryKind.LESSON,
                content=(
                    "Пользователь исправил предыдущий вывод Тоору.\n"
                    "Предыдущий ответ:\n"
                    + previous_assistant.strip()[:2_500]
                    + "\n\nУточнение пользователя:\n"
                    + user_message.strip()[:2_500]
                    + "\n\nПри похожей задаче сначала перепроверь предпосылку, "
                    "которая была исправлена пользователем."
                ),
                source="chat-correction",
                source_ref=(f"chat:{session_id}" if session_id else "chat"),
                confidence=0.98,
                importance=0.75,
                tags=[
                    "correction-lesson",
                    "error-learning",
                    "user-correction",
                ],
                session_id=session_id,
            ),
            reason=(
                "Explicit user correction converted into a reviewable "
                "error-learning lesson."
            ),
        )
        if lesson.memory is not None:
            return "correction:lesson-applied=1"
        if lesson.decision.queue_id:
            return "correction:lesson-pending=1"
        return "correction:lesson-blocked=1"

    def register_correction(
        self,
        memory_id: str,
        corrected_content: str,
        *,
        owner_id: str = "local-user",
        reason: str = "User correction.",
    ) -> dict[str, Any]:
        wrong = self.memory.get(memory_id, owner_id)
        corrected = self.intake.ingest(
            MemoryCreate(
                owner_id=wrong.owner_id,
                scope=wrong.scope,
                project_id=wrong.project_id,
                kind=wrong.kind,
                key=wrong.key,
                content=corrected_content,
                source="user-correction",
                source_ref=wrong.id,
                confidence=1.0,
                importance=max(0.85, wrong.importance),
                tags=list(dict.fromkeys([*wrong.tags, "corrected"])),
            ),
            reason=reason,
        )
        corrected_id = corrected.memory.id if corrected.memory else None
        lesson_id = None
        if corrected.memory is not None:
            self.store.add_link(
                corrected.memory.id,
                wrong.id,
                MemoryLinkType.CORRECTS,
                1.0,
            )
            self.record_source_feedback(
                wrong.id,
                confirmed=False,
                owner_id=owner_id,
            )
            lesson = self.intake.ingest(
                MemoryCreate(
                    owner_id=wrong.owner_id,
                    scope=wrong.scope,
                    project_id=wrong.project_id,
                    kind=MemoryKind.LESSON,
                    content=(
                        "Исправление памяти: прежняя запись была неточной. "
                        f"Было: {wrong.content[:1500]} "
                        f"Стало: {corrected_content[:1500]}. "
                        f"Причина: {reason[:500]}"
                    ),
                    source="correction-learning",
                    source_ref=wrong.id,
                    confidence=0.95,
                    importance=0.72,
                    tags=["correction-lesson", "error-learning"],
                ),
                reason="Learn a reusable lesson from an explicit correction.",
            )
            if lesson.memory is not None:
                lesson_id = lesson.memory.id
                self.store.add_link(
                    lesson.memory.id,
                    corrected.memory.id,
                    MemoryLinkType.DERIVED_FROM,
                    1.0,
                )
        return {
            "corrected_memory_id": corrected_id,
            "corrected_outcome": corrected.decision.outcome.value,
            "queue_id": corrected.decision.queue_id,
            "lesson_id": lesson_id,
        }

    def record_source_feedback(
        self,
        memory_id: str,
        *,
        confirmed: bool,
        owner_id: str = "local-user",
    ) -> list[dict[str, Any]]:
        memory = self.memory.get(memory_id, owner_id)
        evidence = self.memory.evidence(
            memory_id,
            owner_id=owner_id,
            limit=100,
        )
        targets = {
            (memory.source, memory.source_ref),
            *((item.source_type, item.source_ref) for item in evidence),
        }
        results = []
        for source_type, source_ref in targets:
            if not source_type:
                continue
            learned = self.store.update_source_reliability(
                source_type,
                source_ref=source_ref,
                confirmed=confirmed,
                base_reliability=self._base_source_reliability(source_type),
            )
            results.append(learned.model_dump(mode="json"))
        return results

    def consolidate_scope(
        self,
        *,
        owner_id: str = "local-user",
        scope: MemoryScope = MemoryScope.PROJECT,
        project_id: str | None = "dragon-tory",
        limit: int = 500,
        create_summary: bool = True,
    ) -> GreyMatterReport:
        items = self.store.scope_items(
            owner_id=owner_id,
            scope=scope,
            project_id=project_id,
            limit=limit,
        )
        entity_links = self._consolidate_entities(items)
        summary = None
        hierarchy_memory = None
        source_ids: list[str] = []
        if create_summary and len(items) >= 2:
            summary = self.memory.consolidate(
                MemoryConsolidateRequest(
                    owner_id=owner_id,
                    scope=scope,
                    project_id=project_id,
                    limit=min(max(2, len(items)), 500),
                    min_importance=0.20,
                )
            )
            hierarchy_memory = summary.memory
            source_ids = summary.source_ids
        else:
            summaries = [
                item
                for item in items
                if item.kind is MemoryKind.SUMMARY
            ]
            if summaries:
                hierarchy_memory = summaries[0]
                source_ids = [
                    item.id
                    for item in items
                    if item.id != hierarchy_memory.id
                    and item.kind is not MemoryKind.SUMMARY
                ][:250]

        hierarchy_links = 0
        if hierarchy_memory is not None:
            for source_id in source_ids:
                if source_id == hierarchy_memory.id:
                    continue
                self.store.add_link(
                    source_id,
                    hierarchy_memory.id,
                    MemoryLinkType.PART_OF,
                    1.0,
                )
                hierarchy_links += 1

        low_confidence = 0
        for item in items[:300]:
            if self.memory.truth(
                item.id,
                owner_id=owner_id,
            ).trust_score < 0.55:
                low_confidence += 1

        return GreyMatterReport(
            scope=scope,
            project_id=project_id,
            memories_scanned=len(items),
            entity_links_created=entity_links,
            hierarchy_links_created=hierarchy_links,
            causal_links_created=sum(
                1
                for item in items
                for link in self.memory.links_for(
                    item.id,
                    MemoryLinkType.CAUSES,
                )
                if link.source_id == item.id
            ),
            summaries_created=(
                1
                if summary is not None and summary.memory is not None
                else 0
            ),
            skills_found=sum(
                item.kind is MemoryKind.SKILL
                for item in items
            ),
            goals_found=sum(
                item.kind is MemoryKind.GOAL
                for item in items
            ),
            low_confidence_items=low_confidence,
        )

    def _consolidate_entities(self, items) -> int:
        entities = [
            item for item in items
            if item.kind is MemoryKind.ENTITY
        ][:250]
        by_signature: dict[str, list[Any]] = {}
        for item in entities:
            signature = self.normalize_entity(
                item.key or item.content[:300]
            )
            if not signature:
                continue
            by_signature.setdefault(signature, []).append(item)

        created = 0
        for group in by_signature.values():
            if len(group) < 2:
                continue
            canonical = sorted(
                group,
                key=lambda item: (
                    item.pinned,
                    item.importance,
                    item.confidence,
                    item.updated_at,
                ),
                reverse=True,
            )[0]
            for duplicate in group[1:]:
                self._same_scope(canonical, duplicate)
                self.store.add_link(
                    canonical.id,
                    duplicate.id,
                    MemoryLinkType.SAME_ENTITY,
                    0.98,
                )
                self.learn_entity_alias(
                    canonical.id,
                    duplicate.content[:300],
                    owner_id=canonical.owner_id,
                    confidence=0.92,
                )
                created += 1
        return created

    @staticmethod
    def _same_scope(left, right) -> None:
        if (
            left.owner_id != right.owner_id
            or left.scope is not right.scope
            or left.project_id != right.project_id
        ):
            raise ValueError("cross-scope graph links are forbidden")

    @staticmethod
    def _base_source_reliability(source_type: str) -> float:
        return {
            "user": 0.95,
            "user-correction": 0.98,
            "document": 0.90,
            "service-memo": 0.90,
            "tooru-module-study": 0.82,
            "memory-guardian": 0.80,
            "chat-outcome": 0.72,
            "experience-learning": 0.70,
            "causal-memory": 0.78,
        }.get(source_type, 0.60)
