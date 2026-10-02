from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tooru.chat.reasoning import ReasoningConfig
from tooru.cognition.models import InsightSeverity, InsightStatus
from tooru.cognition.service import CognitionService
from tooru.cognition.store import CognitionStore


class StubCloud:
    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents = documents or []

    def all_active_documents(self, *, limit: int = 5_000) -> list[dict]:
        return list(self.documents[:limit])

    def document_chunks(
        self,
        document_id: str,
        *,
        query: str = "",
        limit: int = 10,
    ) -> list[dict]:
        return []


class StubSmart:
    def __init__(
        self,
        *,
        vehicles: list[dict] | None = None,
        employees: list[dict] | None = None,
        counterparties: list[dict] | None = None,
        dna: dict[str, dict] | None = None,
        permissions: dict[str, bool] | None = None,
    ) -> None:
        self.vehicles = vehicles or []
        self.employees = employees or []
        self.counterparties = counterparties or []
        self.dna = dna or {}
        self.permissions = permissions or {}
        self.provenance_events: list[dict] = []

    def list_employees(self, *, limit: int = 1_000) -> list[dict]:
        return list(self.employees[:limit])

    def list_counterparties(self, *, limit: int = 2_000) -> list[dict]:
        return list(self.counterparties[:limit])

    def list_vehicles(self, *, limit: int = 1_000) -> list[dict]:
        return list(self.vehicles[:limit])

    def get_dna(self, document_id: str) -> dict:
        if document_id not in self.dna:
            raise KeyError(document_id)
        return dict(self.dna[document_id])

    def graph(self, *, limit: int = 2_000) -> dict:
        return {"nodes": [], "edges": []}

    def garage_alerts(self, *, days: int = 15) -> list[dict]:
        return [
            item
            for item in self.vehicles
            if item.get("insurance_days_left") is not None
            and int(item["insurance_days_left"]) <= days
        ]

    def list_relations(self, document_id: str) -> list[dict]:
        return []

    def permission(self, document_id: str, name: str) -> bool:
        assert name == "content_read"
        return self.permissions.get(document_id, True)

    def apply_intelligence_defaults(
        self,
        document_id: str,
        result: dict,
    ) -> dict:
        return {"document_id": document_id, "applied": True}

    def record_provenance(
        self,
        document_id: str,
        operation: str,
        *,
        actor: str,
        details: dict,
    ) -> None:
        self.provenance_events.append(
            {
                "document_id": document_id,
                "operation": operation,
                "actor": actor,
                "details": details,
            }
        )


class StubIntelligence:
    def __init__(
        self,
        analyses: dict[str, dict] | None = None,
        pending: list[dict] | None = None,
    ) -> None:
        self.analyses = analyses or {}
        self.pending = pending or []
        self.analyzed: list[str] = []

    def get(self, document_id: str) -> dict:
        if document_id not in self.analyses:
            raise KeyError(document_id)
        return dict(self.analyses[document_id])

    def collection_items(
        self,
        collection_id: str,
        *,
        limit: int = 100,
    ) -> list[dict]:
        assert collection_id == "attention:unanalyzed"
        return list(self.pending[:limit])

    def analyze(self, document_id: str) -> dict:
        self.analyzed.append(document_id)
        if document_id not in self.analyses:
            raise KeyError(document_id)
        return dict(self.analyses[document_id])


class StubGuardian:
    def __init__(self) -> None:
        self.candidates = []

    def ingest_structured(self, memory, *, reason: str, auto_apply: bool):
        self.candidates.append(memory)
        return SimpleNamespace(memory_id="MEM-1", queue_id=None)


def make_service(
    tmp_path: Path,
    *,
    cloud: StubCloud | None = None,
    smart: StubSmart | None = None,
    intelligence: StubIntelligence | None = None,
    guardian: StubGuardian | None = None,
) -> CognitionService:
    store = CognitionStore(tmp_path / "cognition.sqlite3")
    service = CognitionService(
        store=store,
        memory=None,
        guardian=guardian or StubGuardian(),
        cloud_store=cloud or StubCloud(),
        smart_drive=smart or StubSmart(),
        document_intelligence=intelligence or StubIntelligence(),
    )
    service.initialize()
    return service


def test_metacognition_escalates_only_when_task_needs_evidence(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    simple = service.assess(
        complexity=0.08,
        memory_uncertainty=0.0,
        contradiction_count=0,
        context_memories=0,
        document_matches=0,
    )
    complex_case = service.assess(
        complexity=0.85,
        memory_uncertainty=0.62,
        contradiction_count=2,
        context_memories=0,
        document_matches=0,
    )

    assert simple.should_escalate is False
    assert complex_case.should_escalate is True
    assert complex_case.readiness < simple.readiness


def test_reasoning_policy_learns_conservatively_from_verified_failures(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    initial = service.policy()

    for _ in range(24):
        service.store.add_experience(
            task_bucket="analysis",
            mode="chain",
            complexity=0.35,
            memory_uncertainty=0.10,
            contradiction_count=0,
            verifier_score=0.60,
            verifier_uncertainty=0.35,
            passed=False,
            escalated=False,
            ai_calls=2,
            duration_ms=120.0,
        )

    report = service.adapt_policy()
    learned = service.policy()

    assert report["changed"] is True
    assert learned.version == initial.version + 1
    assert learned.hybrid_complexity_threshold < initial.hybrid_complexity_threshold
    assert learned.verifier_escalation_score > initial.verifier_escalation_score
    assert 0.30 <= learned.hybrid_complexity_threshold <= 0.60
    assert 0.72 <= learned.verifier_escalation_score <= 0.92

    config = ReasoningConfig()
    service.apply_reasoning_policy(config)
    assert config.hybrid_complexity_threshold == learned.hybrid_complexity_threshold


def test_reasoning_policy_waits_for_enough_evidence(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    for _ in range(5):
        service.store.add_experience(
            task_bucket="analysis",
            mode="chain",
            complexity=0.30,
            memory_uncertainty=0.10,
            contradiction_count=0,
            verifier_score=0.55,
            verifier_uncertainty=0.30,
            passed=False,
            escalated=False,
            ai_calls=2,
            duration_ms=100.0,
        )

    report = service.adapt_policy()
    assert report["changed"] is False
    assert report["reason"] == "need-more-samples"
    assert service.policy().version == 1


def test_correction_learning_is_guarded(tmp_path: Path) -> None:
    guardian = StubGuardian()
    service = make_service(tmp_path, guardian=guardian)

    result = service.learn_correction(
        user_message="Нет, эта запчасть не относится к этой машине.",
        previous_assistant="Эта запчасть относится к автомобилю А.",
        session_id="chat-1",
    )

    assert result == "correction:applied"
    assert len(guardian.candidates) == 1
    candidate = guardian.candidates[0]
    assert candidate.kind.value == "lesson"
    assert candidate.scope.value == "project"
    assert candidate.project_id == "dragon-tory"


def test_work_graph_links_people_vehicles_documents_and_money(
    tmp_path: Path,
) -> None:
    cloud = StubCloud(
        [
            {
                "id": "DOC-1",
                "name": "Счёт на ремонт",
                "version": 1,
                "project_id": "dragon-tory",
                "created_at": "2026-09-20T00:00:00+00:00",
            }
        ]
    )
    smart = StubSmart(
        employees=[
            {
                "id": "EMP-1",
                "full_name": "Иванов Иван",
                "department": "Гараж",
                "position": "Водитель",
                "active": True,
            }
        ],
        counterparties=[
            {"id": "CP-1", "name": "Авто Сервис", "inn": "123", "kpp": ""}
        ],
        vehicles=[
            {
                "id": "CAR-1",
                "garage_number": "7",
                "plate_number": "A001AA",
                "vin": "JT123456789012345",
                "make_model": "Toyota",
                "driver_employee_id": "EMP-1",
                "active": True,
                "insurance_days_left": 100,
            }
        ],
        dna={
            "DOC-1": {
                "kind": "счёт",
                "counterparty_id": "CP-1",
                "counterparty": "Авто Сервис",
                "amount_value": 12500.0,
                "amount_currency": "RUB",
                "document_number": "15",
                "document_date": "2026-09-20",
                "work_reason": "Ремонт автомобиля",
                "document_subtype": "ремонт",
            }
        },
    )
    intelligence = StubIntelligence(
        {
            "DOC-1": {
                "kind": "счёт",
                "summary_local": "Ремонт автомобиля",
                "entities": {
                    "vin": ["JT123456789012345"],
                    "counterparties": ["Авто Сервис"],
                    "employees": ["Иванов Иван"],
                    "amounts": [],
                },
                "checks": {"warnings": []},
                "deadlines": [],
            }
        }
    )
    service = make_service(
        tmp_path,
        cloud=cloud,
        smart=smart,
        intelligence=intelligence,
    )

    result = service.rebuild_graph()
    graph = service.store.graph(limit=100)

    kinds = {node["kind"] for node in graph["nodes"]}
    edge_kinds = {edge["kind"] for edge in graph["edges"]}
    assert result["nodes"] >= 6
    assert {"person", "vehicle", "document", "company", "money", "work"} <= kinds
    assert {
        "DRIVES",
        "INVOLVES_COMPANY",
        "REFERENCES_VEHICLE",
        "HAS_AMOUNT",
        "DESCRIBES_WORK",
    } <= edge_kinds


def test_proactive_scan_detects_evidence_backed_anomalies(
    tmp_path: Path,
) -> None:
    cloud = StubCloud(
        [
            {
                "id": "DOC-1",
                "name": "Счёт 15",
                "version": 1,
                "project_id": "dragon-tory",
                "created_at": "2026-09-20T00:00:00+00:00",
            }
        ]
    )
    smart = StubSmart(
        vehicles=[
            {
                "id": "CAR-1",
                "garage_number": "1",
                "plate_number": "A001AA",
                "vin": "JT123456789012345",
                "make_model": "Toyota A",
                "driver_employee_id": None,
                "active": True,
                "insurance_days_left": -2,
                "insurance_end": "2026-09-29",
                "insurance_policy": "P1",
            },
            {
                "id": "CAR-2",
                "garage_number": "2",
                "plate_number": "A002AA",
                "vin": "JT123456789012345",
                "make_model": "Toyota B",
                "driver_employee_id": None,
                "active": True,
                "insurance_days_left": 100,
            },
        ],
        dna={
            "DOC-1": {
                "kind": "счёт",
                "counterparty_id": "CP-UNKNOWN",
                "counterparty": "Поставщик",
                "document_number": "15",
                "document_date": "2026-09-20",
                "amount_value": 1000.0,
                "amount_currency": "RUB",
            }
        },
    )
    intelligence = StubIntelligence(
        {
            "DOC-1": {
                "kind": "счёт",
                "summary_local": "Счёт поставщика",
                "entities": {
                    "vin": [],
                    "counterparties": ["Другой поставщик"],
                    "employees": [],
                    "amounts": [],
                },
                "checks": {
                    "warnings": [
                        {
                            "code": "vat_amount_mismatch",
                            "severity": "warning",
                            "message": "НДС требует проверки.",
                        }
                    ]
                },
                "deadlines": [],
            }
        }
    )
    service = make_service(
        tmp_path,
        cloud=cloud,
        smart=smart,
        intelligence=intelligence,
    )

    report = service.scan_proactive()
    insights = service.store.insights(
        status=InsightStatus.OPEN,
        limit=100,
    )
    rules = {item.rule_id for item in insights}

    assert report["open"] >= 4
    assert "duplicate_vehicle_identity" in rules
    assert "insurance_expiry" in rules
    assert "invoice_without_contract" in rules
    assert "document_check:vat_amount_mismatch" in rules
    assert "counterparty_mismatch" in rules
    assert any(item.severity is InsightSeverity.HIGH for item in insights)


def test_dismissed_insight_stays_dismissed_across_scan(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    item = service.store.upsert_insight(
        rule_id="test",
        severity=InsightSeverity.LOW,
        confidence=0.8,
        title="Test",
        summary="Test",
        fingerprint="same",
        entity_refs=[],
        evidence=[],
    )
    service.store.set_insight_status(item.id, InsightStatus.DISMISSED)
    updated = service.store.upsert_insight(
        rule_id="test",
        severity=InsightSeverity.HIGH,
        confidence=0.9,
        title="Test again",
        summary="Still present",
        fingerprint="same",
        entity_refs=[],
        evidence=[],
    )

    assert updated.status is InsightStatus.DISMISSED


def test_auto_analysis_respects_document_ai_contract(tmp_path: Path) -> None:
    cloud = StubCloud(
        [
            {"id": "DOC-ALLOW", "name": "Разрешённый.docx"},
            {"id": "DOC-DENY", "name": "Закрытый.docx"},
        ]
    )
    smart = StubSmart(
        permissions={
            "DOC-ALLOW": True,
            "DOC-DENY": False,
        }
    )
    intelligence = StubIntelligence(
        analyses={
            "DOC-ALLOW": {
                "version": 1,
                "kind": "счёт",
                "ocr_used": False,
            },
            "DOC-DENY": {
                "version": 1,
                "kind": "договор",
                "ocr_used": False,
            },
        },
        pending=[
            {"id": "DOC-ALLOW", "name": "Разрешённый.docx"},
            {"id": "DOC-DENY", "name": "Закрытый.docx"},
        ],
    )
    service = make_service(
        tmp_path,
        cloud=cloud,
        smart=smart,
        intelligence=intelligence,
    )

    report = service.analyze_pending_documents()

    assert report["analyzed"] == 1
    assert report["skipped"] == 1
    assert intelligence.analyzed == ["DOC-ALLOW"]
    assert len(smart.provenance_events) == 1
    event = smart.provenance_events[0]
    assert event["operation"] == "cognition_auto_analysis"
    assert event["details"]["external_ai_used"] is False


def test_line_item_price_signal_ignores_price_in_identity(
    tmp_path: Path,
) -> None:
    documents = [
        {
            "id": "DOC-1",
            "name": "Счёт 1",
            "version": 1,
            "project_id": "dragon-tory",
            "created_at": "2026-09-01T00:00:00+00:00",
        },
        {
            "id": "DOC-2",
            "name": "Счёт 2",
            "version": 1,
            "project_id": "dragon-tory",
            "created_at": "2026-09-15T00:00:00+00:00",
        },
    ]

    class ChunkCloud(StubCloud):
        def document_chunks(
            self,
            document_id: str,
            *,
            query: str = "",
            limit: int = 10,
        ) -> list[dict]:
            price = "1000 руб" if document_id == "DOC-1" else "1700 руб"
            return [
                {
                    "chunk_no": 1,
                    "page_no": 1,
                    "text": f"Фильтр масляный ABC-123 {price}",
                }
            ]

    smart = StubSmart(
        dna={
            "DOC-1": {"kind": "счёт"},
            "DOC-2": {"kind": "счёт"},
        }
    )
    intelligence = StubIntelligence(
        analyses={
            "DOC-1": {
                "kind": "счёт",
                "summary_local": "",
                "entities": {
                    "vin": [],
                    "counterparties": [],
                    "employees": [],
                    "amounts": [],
                },
                "checks": {"warnings": []},
                "deadlines": [],
            },
            "DOC-2": {
                "kind": "счёт",
                "summary_local": "",
                "entities": {
                    "vin": [],
                    "counterparties": [],
                    "employees": [],
                    "amounts": [],
                },
                "checks": {"warnings": []},
                "deadlines": [],
            },
        }
    )
    service = make_service(
        tmp_path,
        cloud=ChunkCloud(documents),
        smart=smart,
        intelligence=intelligence,
    )

    service.scan_proactive()
    rules = {
        item.rule_id
        for item in service.store.insights(
            status=InsightStatus.OPEN,
            limit=100,
        )
    }

    assert "line_item_price_jump" in rules


def test_vehicle_plate_canonicalization_avoids_false_mismatch(
    tmp_path: Path,
) -> None:
    cloud = StubCloud(
        [
            {
                "id": "DOC-PLATE-OK",
                "name": "Счёт на автомобиль",
                "version": 1,
                "project_id": "dragon-tory",
                "created_at": "2026-09-20T00:00:00+00:00",
            }
        ]
    )
    smart = StubSmart(
        vehicles=[
            {
                "id": "CAR-OK",
                "garage_number": "10",
                "plate_number": "A001AA25",
                "vin": "JF1SJABC1GH123456",
                "make_model": "Subaru",
                "driver_employee_id": None,
                "active": True,
                "insurance_days_left": 100,
            }
        ],
        dna={"DOC-PLATE-OK": {"kind": "счёт"}},
    )
    intelligence = StubIntelligence(
        {
            "DOC-PLATE-OK": {
                "kind": "счёт",
                "summary_local": "",
                "entities": {
                    "vin": ["JF1SJABC1GH123456"],
                    "plate_number": ["А001АА25"],
                    "counterparties": [],
                    "employees": [],
                    "amounts": [],
                },
                "checks": {"warnings": []},
                "deadlines": [],
            }
        }
    )
    service = make_service(
        tmp_path,
        cloud=cloud,
        smart=smart,
        intelligence=intelligence,
    )

    service.scan_proactive()
    rules = {
        item.rule_id
        for item in service.store.insights(
            status=InsightStatus.OPEN,
            limit=100,
        )
    }

    assert "vehicle_identity_mismatch" not in rules


def test_vehicle_vin_plate_conflict_is_proactive_high_signal(
    tmp_path: Path,
) -> None:
    cloud = StubCloud(
        [
            {
                "id": "DOC-PLATE-BAD",
                "name": "Счёт на автомобиль",
                "version": 1,
                "project_id": "dragon-tory",
                "created_at": "2026-09-20T00:00:00+00:00",
            }
        ]
    )
    smart = StubSmart(
        vehicles=[
            {
                "id": "CAR-1",
                "garage_number": "10",
                "plate_number": "A001AA25",
                "vin": "JF1SJABC1GH123456",
                "make_model": "Subaru",
                "driver_employee_id": None,
                "active": True,
                "insurance_days_left": 100,
            },
            {
                "id": "CAR-2",
                "garage_number": "11",
                "plate_number": "B777BB25",
                "vin": "JT123456789012345",
                "make_model": "Toyota",
                "driver_employee_id": None,
                "active": True,
                "insurance_days_left": 100,
            },
        ],
        dna={"DOC-PLATE-BAD": {"kind": "счёт"}},
    )
    intelligence = StubIntelligence(
        {
            "DOC-PLATE-BAD": {
                "kind": "счёт",
                "summary_local": "",
                "entities": {
                    "vin": ["JF1SJABC1GH123456"],
                    "plate_number": ["В777ВВ25"],
                    "counterparties": [],
                    "employees": [],
                    "amounts": [],
                },
                "checks": {"warnings": []},
                "deadlines": [],
            }
        }
    )
    service = make_service(
        tmp_path,
        cloud=cloud,
        smart=smart,
        intelligence=intelligence,
    )

    service.scan_proactive()
    insights = service.store.insights(
        status=InsightStatus.OPEN,
        limit=100,
    )
    mismatch = next(
        item for item in insights
        if item.rule_id == "vehicle_identity_mismatch"
    )

    assert mismatch.severity is InsightSeverity.HIGH
    assert mismatch.confidence >= 0.90
    assert mismatch.evidence[0]["garage_vehicle_id"] == "CAR-1"
    assert mismatch.evidence[0]["other_vehicle_id"] == "CAR-2"
