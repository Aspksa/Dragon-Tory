from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from tooru.cognition.models import (
    CognitionStatus,
    GraphEdge,
    GraphNode,
    InsightSeverity,
    InsightStatus,
    MetacognitiveAssessment,
    ReasoningExperience,
    ReasoningPolicy,
)
from tooru.cognition.store import CognitionStore, utc_now
from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope

PROJECT_ID = "dragon-tory"

_CORRECTION_RE = re.compile(
    r"^\s*(?:нет\b|неверн\w*|ошиб\w*|не\s+так\b|исправ\w*|"
    r"это\s+не\b|я\s+же\s+говорил\w*)",
    re.IGNORECASE,
)
_ANALYSIS_RE = re.compile(
    r"\b(?:анализ|сравн|проверк|архитект|противореч|причин|риск)\w*",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"\b(?:код|python|javascript|typescript|java|rust|api|sql|github|"
    r"тест|рефактор|баг|ошибк)\w*",
    re.IGNORECASE,
)
_DOCUMENT_RE = re.compile(
    r"\b(?:документ|договор|сч[её]т|оферт|служебн|приказ|акт|pdf|docx|xlsx)\w*",
    re.IGNORECASE,
)
_GARAGE_RE = re.compile(
    r"\b(?:гараж|автомоб|машин|vin|госномер|страхов|ремонт)\w*",
    re.IGNORECASE,
)
_REQUEST_RE = re.compile(
    r"\b(?:просим|прошу|необходимо|требуется|поручить|обеспечить|согласовать)\w*",
    re.IGNORECASE,
)
_PART_LINE_RE = re.compile(
    r"\b(?:запчаст|детал|фильтр|колодк|ремень|свеч|подшипник|насос|"
    r"амортизатор|радиатор|аккумулятор|шина|масло|датчик)\w*",
    re.IGNORECASE,
)
_WORK_LINE_RE = re.compile(
    r"\b(?:ремонт|замен|диагност|мойк|монтаж|демонтаж|обслуживан|"
    r"регулиров|установк|проверка|работы?)\w*",
    re.IGNORECASE,
)
_MONEY_LINE_RE = re.compile(
    r"(?P<amount>\d[\d\s]{0,12}(?:[,.]\d{1,2})?)\s*"
    r"(?P<currency>руб(?:\.|лей)?|₽|RUB)\b",
    re.IGNORECASE,
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _norm(value: Any) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", "", str(value or "").casefold())


def _stable_id(kind: str, ref: str) -> str:
    digest = hashlib.sha1(
        f"{kind}:{ref}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:24]
    return f"COG-{kind.upper()}-{digest}"


def _fingerprint(rule_id: str, *parts: Any) -> str:
    payload = "|".join([rule_id, *(_norm(part) for part in parts)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


class CognitionService:
    """Adaptive, proactive cognitive control plane for Dragon Tory."""

    MIN_POLICY_SAMPLES = 24
    POLICY_WINDOW = 240

    def __init__(
        self,
        *,
        store: CognitionStore,
        memory,
        guardian,
        cloud_store,
        smart_drive,
        document_intelligence,
        observability=None,
    ) -> None:
        self.store = store
        self.memory = memory
        self.guardian = guardian
        self.cloud_store = cloud_store
        self.smart_drive = smart_drive
        self.document_intelligence = document_intelligence
        self.observability = observability

    def initialize(self) -> None:
        self.store.initialize()

    @staticmethod
    def task_bucket(message: str) -> str:
        text = message.strip()
        if _GARAGE_RE.search(text):
            return "garage"
        if _DOCUMENT_RE.search(text):
            return "documents"
        if _CODE_RE.search(text):
            return "engineering"
        if _ANALYSIS_RE.search(text):
            return "analysis"
        if len(text) < 80:
            return "simple"
        return "general"

    def policy(self) -> ReasoningPolicy:
        return self.store.current_policy()

    def apply_reasoning_policy(self, config) -> ReasoningPolicy:
        policy = self.policy()
        config.hybrid_complexity_threshold = (
            policy.hybrid_complexity_threshold
        )
        config.tree_complexity_threshold = policy.tree_complexity_threshold
        config.hybrid_uncertainty_threshold = (
            policy.hybrid_uncertainty_threshold
        )
        config.tree_uncertainty_threshold = policy.tree_uncertainty_threshold
        config.verifier_escalation_score = policy.verifier_escalation_score
        config.verifier_escalation_uncertainty = (
            policy.verifier_escalation_uncertainty
        )
        return policy

    def assess(
        self,
        *,
        complexity: float,
        memory_uncertainty: float,
        contradiction_count: int,
        context_memories: int,
        document_matches: int,
        verification_score: float | None = None,
        verification_uncertainty: float | None = None,
        verification_contradictions: int = 0,
    ) -> MetacognitiveAssessment:
        coverage = _clamp(
            (float(context_memories) + 1.5 * float(document_matches)) / 8.0,
            0.0,
            1.0,
        )
        uncertainty = max(
            float(memory_uncertainty),
            float(verification_uncertainty or 0.0),
        )
        contradictions = int(contradiction_count) + int(
            verification_contradictions
        )
        contradiction_pressure = _clamp(contradictions / 3.0, 0.0, 1.0)

        evidence_gap = float(complexity) * (1.0 - coverage)
        risk = (
            0.50 * evidence_gap
            + 0.32 * uncertainty
            + 0.28 * contradiction_pressure
        )
        if verification_score is not None:
            risk += 0.22 * (1.0 - float(verification_score))
        readiness = _clamp(1.0 - risk, 0.0, 1.0)

        reasons: list[str] = []
        if evidence_gap >= 0.35:
            reasons.append("low-evidence-coverage")
        if uncertainty >= 0.40:
            reasons.append("high-uncertainty")
        if contradiction_pressure >= 0.34:
            reasons.append("contradiction-pressure")
        if verification_score is not None and verification_score < 0.82:
            reasons.append("weak-verifier-score")

        should_escalate = (
            float(complexity) >= 0.35
            and (
                readiness < 0.52
                or contradiction_pressure >= 0.67
                or uncertainty >= 0.58
            )
        )
        if verification_score is not None and verification_score < 0.72:
            should_escalate = True

        return MetacognitiveAssessment(
            readiness=round(readiness, 6),
            uncertainty=round(_clamp(uncertainty, 0.0, 1.0), 6),
            evidence_coverage=round(coverage, 6),
            contradiction_pressure=round(contradiction_pressure, 6),
            should_escalate=should_escalate,
            reasons=reasons,
        )

    def record_reasoning_experience(
        self,
        *,
        task: str,
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
        experience = self.store.add_experience(
            task_bucket=self.task_bucket(task),
            mode=mode,
            complexity=complexity,
            memory_uncertainty=memory_uncertainty,
            contradiction_count=contradiction_count,
            verifier_score=verifier_score,
            verifier_uncertainty=verifier_uncertainty,
            passed=passed,
            escalated=escalated,
            ai_calls=ai_calls,
            duration_ms=duration_ms,
        )
        if self.observability is not None:
            self.observability.event(
                category="cognition",
                stage="learning",
                operation="reasoning_experience",
                status="success",
                module="cognition",
                source_type="reasoning",
                source_id=experience.id,
                message=(
                    f"Reasoning outcome recorded: {mode} / "
                    f"{experience.task_bucket}."
                ),
                details={
                    "experience_id": experience.id,
                    "task_bucket": experience.task_bucket,
                    "mode": mode,
                    "passed": passed,
                    "score": verifier_score,
                    "ai_calls": ai_calls,
                    "duration_ms": round(duration_ms, 3),
                    "escalated": escalated,
                },
            )
        return experience

    @staticmethod
    def _failure(item: ReasoningExperience) -> bool:
        if item.user_feedback in {"unhelpful", "corrected"}:
            return True
        if item.passed is False:
            return True
        return (
            item.verifier_score is not None
            and item.verifier_score < 0.78
        )

    def adapt_policy(self, *, force: bool = False) -> dict[str, Any]:
        experiences = self.store.experiences(limit=self.POLICY_WINDOW)
        verified = [
            item
            for item in experiences
            if item.verifier_score is not None or item.user_feedback is not None
        ]
        current = self.policy()
        if len(verified) < self.MIN_POLICY_SAMPLES and not force:
            return {
                "changed": False,
                "reason": "need-more-samples",
                "sample_count": len(verified),
                "required": self.MIN_POLICY_SAMPLES,
                "policy": current.model_dump(mode="json"),
            }

        by_mode: dict[str, list[ReasoningExperience]] = defaultdict(list)
        for item in verified:
            by_mode[item.mode].append(item)

        chain = by_mode.get("chain", [])
        hybrid = by_mode.get("hybrid", [])
        tree = by_mode.get("tree", [])
        changes: dict[str, float] = {}

        hybrid_complexity = current.hybrid_complexity_threshold
        tree_complexity = current.tree_complexity_threshold
        verifier_score = current.verifier_escalation_score
        verifier_uncertainty = current.verifier_escalation_uncertainty

        if len(chain) >= 8:
            failure_rate = sum(self._failure(x) for x in chain) / len(chain)
            if failure_rate >= 0.25:
                hybrid_complexity -= 0.02
                verifier_score += 0.01
                changes["chain_failure_rate"] = round(failure_rate, 4)
            elif failure_rate <= 0.08:
                hybrid_complexity += 0.01
                changes["chain_failure_rate"] = round(failure_rate, 4)

        if len(hybrid) >= 8:
            escalation_rate = sum(x.escalated for x in hybrid) / len(hybrid)
            failure_rate = sum(self._failure(x) for x in hybrid) / len(hybrid)
            if escalation_rate >= 0.45 or failure_rate >= 0.22:
                tree_complexity -= 0.02
                verifier_score += 0.01
                changes["hybrid_escalation_rate"] = round(
                    escalation_rate,
                    4,
                )
            elif escalation_rate <= 0.12 and failure_rate <= 0.08:
                tree_complexity += 0.01

        costly = [
            item
            for item in tree
            if item.ai_calls >= 4 and not self._failure(item)
        ]
        if len(tree) >= 8 and len(costly) / len(tree) >= 0.75:
            tree_complexity += 0.01
            changes["tree_cost_pressure"] = round(
                len(costly) / len(tree),
                4,
            )

        corrected = [
            item for item in verified
            if item.user_feedback in {"unhelpful", "corrected"}
        ]
        if len(corrected) >= 3:
            verifier_score += 0.01
            verifier_uncertainty -= 0.01
            changes["explicit_corrections"] = float(len(corrected))

        proposed = ReasoningPolicy(
            version=current.version + 1,
            sample_count=len(verified),
            hybrid_complexity_threshold=_clamp(
                hybrid_complexity,
                0.30,
                0.60,
            ),
            tree_complexity_threshold=_clamp(
                tree_complexity,
                0.60,
                0.88,
            ),
            hybrid_uncertainty_threshold=current.hybrid_uncertainty_threshold,
            tree_uncertainty_threshold=current.tree_uncertainty_threshold,
            verifier_escalation_score=_clamp(
                verifier_score,
                0.72,
                0.92,
            ),
            verifier_escalation_uncertainty=_clamp(
                verifier_uncertainty,
                0.20,
                0.55,
            ),
        )
        same = all(
            math.isclose(getattr(current, name), getattr(proposed, name))
            for name in (
                "hybrid_complexity_threshold",
                "tree_complexity_threshold",
                "hybrid_uncertainty_threshold",
                "tree_uncertainty_threshold",
                "verifier_escalation_score",
                "verifier_escalation_uncertainty",
            )
        )
        if same:
            return {
                "changed": False,
                "reason": "stable",
                "sample_count": len(verified),
                "policy": current.model_dump(mode="json"),
            }

        reason = "adaptive-bounded:" + ",".join(sorted(changes))
        saved = self.store.save_policy(proposed, reason=reason)
        if self.observability is not None:
            self.observability.event(
                category="cognition",
                stage="learning",
                operation="reasoning_policy_adapted",
                status="success",
                module="cognition",
                source_type="policy",
                source_id=str(saved.version),
                message="Bounded reasoning policy adapted from verified outcomes.",
                details={
                    "changes": changes,
                    "policy": saved.model_dump(mode="json"),
                },
            )
        return {
            "changed": True,
            "reason": reason,
            "sample_count": len(verified),
            "signals": changes,
            "policy": saved.model_dump(mode="json"),
        }

    def feedback(
        self,
        experience_id: str,
        *,
        feedback: str,
        note: str = "",
    ) -> ReasoningExperience:
        return self.store.feedback(
            experience_id,
            feedback=feedback,
            note=note,
        )

    def learn_correction(
        self,
        *,
        user_message: str,
        previous_assistant: str,
        session_id: str | None,
    ) -> str:
        if not previous_assistant.strip() or not _CORRECTION_RE.search(
            user_message
        ):
            return "correction:not-detected"
        content = (
            "Исправление пользователя к предыдущему ответу Тоору.\n"
            f"Предыдущий ответ: {previous_assistant.strip()[:2500]}\n"
            f"Исправление: {user_message.strip()[:2500]}"
        )
        candidate = MemoryCreate(
            owner_id="local-user",
            scope=MemoryScope.PROJECT,
            project_id=PROJECT_ID,
            kind=MemoryKind.LESSON,
            key=None,
            content=content,
            source="cognition-correction-learning",
            source_ref=(
                f"chat:{session_id}:correction"
                if session_id
                else "chat:correction"
            ),
            confidence=0.90,
            importance=0.78,
            tags=[
                "correction-learning",
                "cognitive-core-viii",
                "guardian-reviewed",
            ],
            session_id=session_id,
        )
        try:
            result = self.guardian.ingest_structured(
                candidate,
                reason=(
                    "Explicit user correction captured as a project lesson. "
                    "Guardian remains authoritative for durable memory."
                ),
                auto_apply=True,
            )
        except Exception as exc:  # noqa: BLE001
            return "correction:error=" + type(exc).__name__
        if result.memory_id:
            return "correction:applied"
        if result.queue_id:
            return "correction:pending"
        return "correction:blocked"

    def _domain_line_items(
        self,
        document_id: str,
    ) -> list[dict[str, Any]]:
        try:
            chunks = self.cloud_store.document_chunks(
                document_id,
                limit=30,
            )
        except (KeyError, PermissionError, ValueError):
            return []
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for chunk in chunks:
            text = str(chunk.get("text") or "")
            for raw_line in text.splitlines():
                line = " ".join(raw_line.strip().split())
                if len(line) < 8 or len(line) > 260:
                    continue
                kind = ""
                if _PART_LINE_RE.search(line):
                    kind = "part"
                elif _WORK_LINE_RE.search(line):
                    kind = "work"
                if not kind:
                    continue
                label = line[:220]
                key = (kind, _norm(label))
                if key in seen:
                    continue
                seen.add(key)
                amount = None
                currency = None
                money = _MONEY_LINE_RE.search(line)
                if money:
                    try:
                        amount = float(
                            money.group("amount").replace(" ", "").replace(",", ".")
                        )
                    except ValueError:
                        amount = None
                    currency = "RUB"
                items.append(
                    {
                        "kind": kind,
                        "label": label,
                        "amount": amount,
                        "currency": currency,
                        "chunk_no": chunk.get("chunk_no"),
                        "page_no": chunk.get("page_no"),
                    }
                )
                if len(items) >= 30:
                    return items
        return items

    def _collect_documents(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for document in self.cloud_store.all_active_documents(limit=5_000):
            item = {"document": document, "dna": None, "analysis": None}
            try:
                item["dna"] = self.smart_drive.get_dna(document["id"])
            except (KeyError, ValueError):
                pass
            try:
                item["analysis"] = self.document_intelligence.get(
                    document["id"]
                )
            except (KeyError, ValueError):
                pass
            result.append(item)
        return result

    def rebuild_graph(self) -> dict[str, int]:
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}

        def add_node(
            kind: str,
            ref_id: str,
            label: str,
            attributes: dict[str, Any] | None = None,
        ) -> str:
            node_id = _stable_id(kind, ref_id)
            nodes[node_id] = GraphNode(
                id=node_id,
                kind=kind,
                label=(label or ref_id)[:500],
                ref_id=ref_id[:500],
                attributes=attributes or {},
            )
            return node_id

        def add_edge(
            source: str,
            target: str,
            kind: str,
            *,
            confidence: float = 1.0,
            evidence: list[dict[str, Any]] | None = None,
        ) -> None:
            if source == target:
                return
            edge_id = _stable_id(
                "edge",
                f"{source}:{kind}:{target}",
            )
            edges[edge_id] = GraphEdge(
                id=edge_id,
                source_id=source,
                target_id=target,
                kind=kind,
                confidence=_clamp(confidence, 0.0, 1.0),
                evidence=evidence or [],
            )

        employees = self.smart_drive.list_employees(limit=1_000)
        employee_by_name: dict[str, str] = {}
        employee_nodes: dict[str, str] = {}
        for item in employees:
            node = add_node(
                "person",
                str(item["id"]),
                str(item.get("full_name") or item["id"]),
                {
                    "department": item.get("department"),
                    "position": item.get("position"),
                    "active": bool(item.get("active", True)),
                },
            )
            employee_nodes[str(item["id"])] = node
            employee_by_name[_norm(item.get("full_name"))] = node

        counterparties = self.smart_drive.list_counterparties(limit=2_000)
        counterparty_nodes: dict[str, str] = {}
        counterparty_by_name: dict[str, str] = {}
        for item in counterparties:
            node = add_node(
                "company",
                str(item["id"]),
                str(item.get("name") or item["id"]),
                {"inn": item.get("inn"), "kpp": item.get("kpp")},
            )
            counterparty_nodes[str(item["id"])] = node
            counterparty_by_name[_norm(item.get("name"))] = node

        vehicle_by_vin: dict[str, str] = {}
        for item in self.smart_drive.list_vehicles(limit=1_000):
            label = " ".join(
                value
                for value in (
                    str(item.get("garage_number") or "").strip(),
                    str(item.get("plate_number") or "").strip(),
                    str(item.get("make_model") or "").strip(),
                )
                if value
            )
            node = add_node(
                "vehicle",
                str(item["id"]),
                label or str(item["id"]),
                {
                    "vin": item.get("vin"),
                    "plate_number": item.get("plate_number"),
                    "garage_number": item.get("garage_number"),
                    "active": bool(item.get("active", True)),
                },
            )
            vin = _norm(item.get("vin"))
            if vin:
                vehicle_by_vin[vin] = node
            driver_id = str(item.get("driver_employee_id") or "")
            if driver_id and driver_id in employee_nodes:
                add_edge(
                    employee_nodes[driver_id],
                    node,
                    "DRIVES",
                    confidence=1.0,
                )

        for bundle in self._collect_documents():
            document = bundle["document"]
            dna = bundle["dna"] or {}
            analysis = bundle["analysis"] or {}
            kind = str(analysis.get("kind") or dna.get("kind") or "document")
            doc_node = add_node(
                "document",
                str(document["id"]),
                str(document.get("name") or document["id"]),
                {
                    "kind": kind,
                    "version": document.get("version"),
                    "project_id": document.get("project_id"),
                    "document_number": dna.get("document_number"),
                    "document_date": dna.get("document_date"),
                },
            )

            counterparty_id = str(dna.get("counterparty_id") or "")
            cp_node = counterparty_nodes.get(counterparty_id)
            if cp_node is None:
                cp_node = counterparty_by_name.get(
                    _norm(dna.get("counterparty"))
                )
            if cp_node:
                add_edge(doc_node, cp_node, "INVOLVES_COMPANY")

            entities = analysis.get("entities") or {}
            for cp_name in entities.get("counterparties") or []:
                target = counterparty_by_name.get(_norm(cp_name))
                if target:
                    add_edge(
                        doc_node,
                        target,
                        "MENTIONS_COMPANY",
                        confidence=0.85,
                    )

            for employee_name in entities.get("employees") or []:
                target = employee_by_name.get(_norm(employee_name))
                if target:
                    add_edge(
                        doc_node,
                        target,
                        "INVOLVES_PERSON",
                        confidence=0.85,
                    )

            for vin in entities.get("vin") or []:
                target = vehicle_by_vin.get(_norm(vin))
                if target:
                    add_edge(
                        doc_node,
                        target,
                        "REFERENCES_VEHICLE",
                        confidence=0.98,
                        evidence=[{"vin": vin}],
                    )

            amount_value = dna.get("amount_value")
            amount_currency = str(dna.get("amount_currency") or "")
            if isinstance(amount_value, (int, float)):
                money_ref = (
                    f"{document['id']}:{amount_currency}:{amount_value}"
                )
                money_node = add_node(
                    "money",
                    money_ref,
                    f"{amount_value:g} {amount_currency}".strip(),
                    {
                        "value": float(amount_value),
                        "currency": amount_currency,
                    },
                )
                add_edge(doc_node, money_node, "HAS_AMOUNT")

            document_date = dna.get("document_date")
            if document_date:
                event_node = add_node(
                    "event",
                    f"{document['id']}:document-date",
                    f"Дата документа {document_date}",
                    {"date": document_date, "event_type": "document_date"},
                )
                add_edge(doc_node, event_node, "HAS_EVENT")

            work_reason = str(dna.get("work_reason") or "").strip()
            subtype = str(dna.get("document_subtype") or "").strip()
            if work_reason or "работ" in subtype.casefold():
                work_node = add_node(
                    "work",
                    f"{document['id']}:work",
                    work_reason or subtype,
                    {
                        "date": dna.get("work_date"),
                        "hours": dna.get("work_hours"),
                    },
                )
                add_edge(doc_node, work_node, "DESCRIBES_WORK")

            for line_item in self._domain_line_items(
                str(document["id"])
            ):
                entity_kind = str(line_item["kind"])
                entity_ref = _norm(line_item["label"])
                entity_node = add_node(
                    entity_kind,
                    entity_ref,
                    str(line_item["label"]),
                    {
                        "amount": line_item.get("amount"),
                        "currency": line_item.get("currency"),
                    },
                )
                add_edge(
                    doc_node,
                    entity_node,
                    (
                        "DESCRIBES_PART"
                        if entity_kind == "part"
                        else "DESCRIBES_WORK"
                    ),
                    confidence=0.72,
                    evidence=[
                        {
                            "chunk_no": line_item.get("chunk_no"),
                            "page_no": line_item.get("page_no"),
                            "line": line_item.get("label"),
                        }
                    ],
                )

        try:
            legacy_graph = self.smart_drive.graph(limit=2_000)
        except Exception:  # noqa: BLE001
            legacy_graph = {"edges": []}
        for relation in legacy_graph.get("edges") or []:
            source = _stable_id("document", str(relation.get("source_id")))
            target = _stable_id("document", str(relation.get("target_id")))
            if source in nodes and target in nodes:
                add_edge(
                    source,
                    target,
                    str(relation.get("relation_type") or "RELATED_DOCUMENT"),
                    confidence=float(relation.get("confidence") or 1.0),
                )

        self.store.replace_graph(
            nodes=list(nodes.values()),
            edges=list(edges.values()),
        )
        return {"nodes": len(nodes), "edges": len(edges)}

    def _emit_insight(
        self,
        seen: set[str],
        *,
        rule_id: str,
        severity: InsightSeverity,
        confidence: float,
        title: str,
        summary: str,
        refs: list[str],
        evidence: list[dict[str, Any]],
        fingerprint_parts: list[Any],
    ) -> None:
        fingerprint = _fingerprint(rule_id, *fingerprint_parts)
        seen.add(fingerprint)
        self.store.upsert_insight(
            rule_id=rule_id,
            severity=severity,
            confidence=confidence,
            title=title,
            summary=summary,
            fingerprint=fingerprint,
            entity_refs=refs,
            evidence=evidence,
        )

    def scan_proactive(self) -> dict[str, Any]:
        seen: set[str] = set()
        today = datetime.now(UTC).date()
        bundles = self._collect_documents()
        vehicles = self.smart_drive.list_vehicles(limit=1_000)

        identity_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(
            list
        )
        for vehicle in vehicles:
            if not vehicle.get("active", True):
                continue
            for field in ("vin", "plate_number"):
                value = _norm(vehicle.get(field))
                if value:
                    identity_index[(field, value)].append(vehicle)
        for (field, value), items in identity_index.items():
            if len(items) < 2:
                continue
            labels = [
                str(item.get("garage_number") or item.get("plate_number") or item["id"])
                for item in items
            ]
            self._emit_insight(
                seen,
                rule_id="duplicate_vehicle_identity",
                severity=InsightSeverity.HIGH,
                confidence=0.99,
                title="Дублирующий идентификатор автомобиля",
                summary=(
                    f"{field.upper()} {value} указан у нескольких карточек: "
                    + ", ".join(labels)
                ),
                refs=[str(item["id"]) for item in items],
                evidence=[{"field": field, "value": value, "vehicles": labels}],
                fingerprint_parts=[field, value],
            )

        for vehicle in self.smart_drive.garage_alerts(days=15):
            days_left = int(vehicle.get("insurance_days_left") or 0)
            expired = days_left < 0
            self._emit_insight(
                seen,
                rule_id="insurance_expiry",
                severity=(
                    InsightSeverity.HIGH
                    if expired
                    else InsightSeverity.MEDIUM
                ),
                confidence=1.0,
                title=(
                    "Страховка автомобиля просрочена"
                    if expired
                    else "Заканчивается страховка автомобиля"
                ),
                summary=(
                    (
                        str(vehicle.get("garage_number"))
                        if vehicle.get("garage_number")
                        else str(
                            vehicle.get("plate_number")
                            or vehicle["id"]
                        )
                    )
                    + ": "
                    + (
                        f"просрочено на {abs(days_left)} дн."
                        if expired
                        else f"осталось {days_left} дн."
                    )
                ),
                refs=[str(vehicle["id"])],
                evidence=[
                    {
                        "insurance_end": vehicle.get("insurance_end"),
                        "days_left": days_left,
                        "policy": vehicle.get("insurance_policy"),
                    }
                ],
                fingerprint_parts=[vehicle["id"], vehicle.get("insurance_end")],
            )

        contracts_by_cp: set[str] = set()
        invoice_bundles: list[dict[str, Any]] = []
        document_number_index: dict[
            tuple[str, str, str],
            list[dict[str, Any]],
        ] = defaultdict(list)
        repair_by_vin: dict[str, list[tuple[date, str]]] = defaultdict(list)
        amounts_by_cp_kind: dict[
            tuple[str, str],
            list[tuple[float, str]],
        ] = defaultdict(list)
        line_prices: dict[
            tuple[str, str],
            list[tuple[float, str, str]],
        ] = defaultdict(list)

        for bundle in bundles:
            document = bundle["document"]
            dna = bundle["dna"] or {}
            analysis = bundle["analysis"] or {}
            kind = str(analysis.get("kind") or dna.get("kind") or "").casefold()
            cp_key = _norm(
                dna.get("counterparty_id") or dna.get("counterparty")
            )
            number = _norm(dna.get("document_number"))
            if "договор" in kind or "contract" in kind:
                if cp_key:
                    contracts_by_cp.add(cp_key)
            if kind in {"счёт", "счет", "invoice"}:
                invoice_bundles.append(bundle)
            if number:
                document_number_index[(kind, cp_key, number)].append(bundle)

            checks = analysis.get("checks") or {}
            warnings = checks.get("warnings") or []
            for warning in warnings:
                code = str(warning.get("code") or "document_warning")
                warning_severity = str(warning.get("severity") or "warning")
                severity = (
                    InsightSeverity.HIGH
                    if warning_severity == "high"
                    else InsightSeverity.MEDIUM
                )
                self._emit_insight(
                    seen,
                    rule_id="document_check:" + code,
                    severity=severity,
                    confidence=0.96,
                    title="Проверка документа требует внимания",
                    summary=(
                        f"{document.get('name')}: "
                        f"{warning.get('message') or code}"
                    ),
                    refs=[str(document["id"])],
                    evidence=[dict(warning)],
                    fingerprint_parts=[document["id"], document.get("version"), code],
                )

            analyzed_cp = [
                _norm(value)
                for value in (analysis.get("entities") or {}).get(
                    "counterparties",
                    [],
                )
                if _norm(value)
            ]
            dna_cp = _norm(dna.get("counterparty"))
            if dna_cp and analyzed_cp and not any(
                dna_cp in value or value in dna_cp for value in analyzed_cp
            ):
                self._emit_insight(
                    seen,
                    rule_id="counterparty_mismatch",
                    severity=InsightSeverity.MEDIUM,
                    confidence=0.72,
                    title="Контрагент в карточке и тексте различается",
                    summary=(
                        f"{document.get('name')}: в карточке "
                        f"«{dna.get('counterparty')}», в тексте найдены "
                        + ", ".join(
                            (analysis.get("entities") or {}).get(
                                "counterparties",
                                [],
                            )[:3]
                        )
                    ),
                    refs=[str(document["id"])],
                    evidence=[
                        {
                            "dna_counterparty": dna.get("counterparty"),
                            "text_counterparties": (
                                analysis.get("entities") or {}
                            ).get("counterparties", [])[:10],
                        }
                    ],
                    fingerprint_parts=[document["id"], "counterparty"],
                )

            for deadline in analysis.get("deadlines") or []:
                deadline_date = _parse_date(deadline.get("date"))
                if deadline_date is None or deadline_date >= today:
                    continue
                self._emit_insight(
                    seen,
                    rule_id="overdue_document_deadline",
                    severity=InsightSeverity.MEDIUM,
                    confidence=0.76,
                    title="В документе обнаружен прошедший срок",
                    summary=(
                        f"{document.get('name')}: срок "
                        f"{deadline.get('date')} уже прошёл. "
                        "Требуется проверить, исполнено ли обязательство."
                    ),
                    refs=[str(document["id"])],
                    evidence=[dict(deadline)],
                    fingerprint_parts=[
                        document["id"],
                        deadline.get("date"),
                        deadline.get("context"),
                    ],
                )

            entities = analysis.get("entities") or {}
            doc_date = (
                _parse_date(dna.get("document_date"))
                or _parse_date(document.get("created_at"))
            )
            repair_signal = (
                "ремонт" in str(document.get("name") or "").casefold()
                or "ремонт" in kind
                or "repair" in kind
            )
            if repair_signal and doc_date:
                for vin in entities.get("vin") or []:
                    repair_by_vin[_norm(vin)].append(
                        (doc_date, str(document["id"]))
                    )

            amount = dna.get("amount_value")
            if (
                cp_key
                and kind
                and isinstance(amount, (int, float))
                and float(amount) > 0
            ):
                amounts_by_cp_kind[(cp_key, kind)].append(
                    (float(amount), str(document["id"]))
                )

            for line_item in self._domain_line_items(
                str(document["id"])
            ):
                amount = line_item.get("amount")
                currency = str(line_item.get("currency") or "")
                label_key = _norm(line_item.get("label"))
                if (
                    label_key
                    and isinstance(amount, (int, float))
                    and float(amount) > 0
                ):
                    line_prices[
                        (str(line_item["kind"]), label_key)
                    ].append(
                        (
                            float(amount),
                            str(document["id"]),
                            currency,
                        )
                    )

            if (
                "служеб" in kind
                and _REQUEST_RE.search(
                    str(analysis.get("summary_local") or "")
                    + " "
                    + str(dna.get("terms_summary") or "")
                )
            ):
                doc_date = (
                    _parse_date(dna.get("document_date"))
                    or _parse_date(document.get("created_at"))
                )
                if doc_date and (today - doc_date).days >= 12:
                    try:
                        relations = self.smart_drive.list_relations(
                            str(document["id"])
                        )
                    except Exception:  # noqa: BLE001
                        relations = []
                    if not relations:
                        self._emit_insight(
                            seen,
                            rule_id="memo_without_followup",
                            severity=InsightSeverity.MEDIUM,
                            confidence=0.68,
                            title="По служебной записке не видно продолжения",
                            summary=(
                                f"{document.get('name')}: прошло "
                                f"{(today - doc_date).days} дн., "
                                "связанных последующих документов нет."
                            ),
                            refs=[str(document["id"])],
                            evidence=[
                                {
                                    "document_date": doc_date.isoformat(),
                                    "age_days": (today - doc_date).days,
                                    "relations": 0,
                                }
                            ],
                            fingerprint_parts=[document["id"]],
                        )

        for bundle in invoice_bundles:
            document = bundle["document"]
            dna = bundle["dna"] or {}
            cp_key = _norm(
                dna.get("counterparty_id") or dna.get("counterparty")
            )
            if cp_key and cp_key not in contracts_by_cp:
                self._emit_insight(
                    seen,
                    rule_id="invoice_without_contract",
                    severity=InsightSeverity.LOW,
                    confidence=0.70,
                    title="Счёт без найденного связанного договора",
                    summary=(
                        f"{document.get('name')}: для контрагента "
                        f"«{dna.get('counterparty') or 'не указан'}» "
                        "в изученных документах договор не найден. "
                        "Счёт может быть самостоятельным — это сигнал для проверки."
                    ),
                    refs=[str(document["id"])],
                    evidence=[
                        {
                            "counterparty": dna.get("counterparty"),
                            "counterparty_id": dna.get("counterparty_id"),
                        }
                    ],
                    fingerprint_parts=[document["id"], cp_key],
                )

        for (kind, cp_key, number), items in document_number_index.items():
            if len(items) < 2:
                continue
            ids = [str(item["document"]["id"]) for item in items]
            self._emit_insight(
                seen,
                rule_id="duplicate_document_number",
                severity=InsightSeverity.MEDIUM,
                confidence=0.88,
                title="Повторяется номер документа",
                summary=(
                    f"Номер {number} встречается в {len(items)} документах "
                    f"типа «{kind or 'не определён'}»."
                ),
                refs=ids,
                evidence=[{"document_ids": ids, "number": number}],
                fingerprint_parts=[kind, cp_key, number],
            )

        cutoff = today - timedelta(days=90)
        for vin, repairs in repair_by_vin.items():
            recent = [item for item in repairs if item[0] >= cutoff]
            if len(recent) < 3:
                continue
            self._emit_insight(
                seen,
                rule_id="frequent_vehicle_repairs",
                severity=InsightSeverity.MEDIUM,
                confidence=0.80,
                title="Автомобиль часто появляется в ремонтных документах",
                summary=(
                    f"VIN {vin}: {len(recent)} ремонтных документа "
                    "за последние 90 дней."
                ),
                refs=[item[1] for item in recent],
                evidence=[
                    {
                        "vin": vin,
                        "documents": [
                            {"date": item[0].isoformat(), "document_id": item[1]}
                            for item in recent
                        ],
                    }
                ],
                fingerprint_parts=[vin, cutoff.isoformat()],
            )

        for (cp_key, kind), values in amounts_by_cp_kind.items():
            if len(values) < 4:
                continue
            baseline = median(value for value, _ in values)
            if baseline <= 0:
                continue
            for value, document_id in values:
                ratio = value / baseline
                if ratio < 2.0:
                    continue
                self._emit_insight(
                    seen,
                    rule_id="document_amount_outlier",
                    severity=InsightSeverity.LOW,
                    confidence=0.58,
                    title="Необычно высокая общая сумма документа",
                    summary=(
                        f"Документ {document_id}: сумма примерно "
                        f"в {ratio:.1f} раза выше медианы похожих документов. "
                        "Это не сравнение цены позиции и требует проверки состава."
                    ),
                    refs=[document_id],
                    evidence=[
                        {
                            "amount": value,
                            "median": baseline,
                            "ratio": round(ratio, 3),
                            "kind": kind,
                        }
                    ],
                    fingerprint_parts=[document_id, "amount-outlier"],
                )

        for (item_kind, label_key), values in line_prices.items():
            if len(values) < 2:
                continue
            positive = [value for value, _, _ in values if value > 0]
            if len(positive) < 2:
                continue
            low = min(positive)
            high = max(positive)
            if low <= 0 or high / low < 1.50:
                continue
            high_entry = max(values, key=lambda item: item[0])
            ratio = high / low
            self._emit_insight(
                seen,
                rule_id="line_item_price_jump",
                severity=InsightSeverity.MEDIUM,
                confidence=0.64,
                title="Сумма одинаковой позиции заметно выросла",
                summary=(
                    f"Позиция {label_key[:80]}: максимальная сумма строки "
                    f"примерно в {ratio:.1f} раза выше минимальной. "
                    "Тоору помечает это как сигнал, а не как доказанную "
                    "изменённую цену за единицу."
                ),
                refs=[item[1] for item in values],
                evidence=[
                    {
                        "kind": item_kind,
                        "normalized_label": label_key,
                        "values": [
                            {
                                "amount": item[0],
                                "document_id": item[1],
                                "currency": item[2],
                            }
                            for item in values
                        ],
                    }
                ],
                fingerprint_parts=[item_kind, label_key],
            )

        auto_rules = {
            "duplicate_vehicle_identity",
            "insurance_expiry",
            "counterparty_mismatch",
            "overdue_document_deadline",
            "memo_without_followup",
            "invoice_without_contract",
            "duplicate_document_number",
            "frequent_vehicle_repairs",
            "document_amount_outlier",
            "line_item_price_jump",
        }
        for insight in self.store.insights(
            status=InsightStatus.OPEN,
            limit=2_000,
        ):
            root_rule = insight.rule_id.split(":", 1)[0]
            if (
                insight.fingerprint not in seen
                and (
                    root_rule in auto_rules
                    or insight.rule_id.startswith("document_check:")
                )
            ):
                self.store.set_insight_status(
                    insight.id,
                    InsightStatus.RESOLVED,
                )

        open_items = self.store.insights(
            status=InsightStatus.OPEN,
            limit=500,
        )
        if self.observability is not None:
            self.observability.event(
                category="cognition",
                stage="proactive",
                operation="proactive_scan",
                status="success",
                module="cognition",
                source_type="system",
                source_id="proactive-scan",
                message=f"Proactive scan found {len(open_items)} open insights.",
                details={
                    "open_insights": len(open_items),
                    "high_insights": sum(
                        item.severity
                        in {InsightSeverity.HIGH, InsightSeverity.CRITICAL}
                        for item in open_items
                    ),
                },
            )
        return {
            "open": len(open_items),
            "high": sum(
                item.severity
                in {InsightSeverity.HIGH, InsightSeverity.CRITICAL}
                for item in open_items
            ),
            "seen_fingerprints": len(seen),
        }

    def run_cycle(self) -> dict[str, Any]:
        policy = self.adapt_policy()
        graph = self.rebuild_graph()
        insights = self.scan_proactive()
        completed = utc_now()
        self.store.set_state("last_cycle_at", completed)
        return {
            "completed_at": completed,
            "policy": policy,
            "graph": graph,
            "insights": insights,
        }

    def status(self, *, automation_running: bool = False) -> CognitionStatus:
        stats = self.store.stats()
        return CognitionStatus(
            policy=self.policy(),
            experiences=stats["experiences"],
            open_insights=stats["open_insights"],
            high_insights=stats["high_insights"],
            graph_nodes=stats["graph_nodes"],
            graph_edges=stats["graph_edges"],
            last_cycle_at=self.store.get_state("last_cycle_at"),
            automation_running=automation_running,
        )
