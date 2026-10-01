from pathlib import Path

from tooru.ai.router import AIRouter
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope
from tooru.memory.store import SQLiteMemoryStore


def _gateway(tmp_path: Path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    engine = MemoryEngine(store, HashEmbeddingProvider(128))
    engine.initialize()
    intelligence = MemoryIntelligence(
        engine,
        AIRouter(),
        IntelligenceConfig(
            primary_provider="deepseek",
            reviewer_provider="deepseek",
        ),
    )
    guardian = MemoryGuardian(
        intelligence,
        store,
        GuardianConfig(),
    )
    return engine, guardian, MemoryIntakeGateway(guardian)


def test_structured_medium_risk_memory_passes_through_guardian(
    tmp_path: Path,
) -> None:
    engine, guardian, gateway = _gateway(tmp_path)

    result = gateway.ingest(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.ENTITY,
            key="garage-vehicle:7",
            content="Автомобиль: Subaru Forester, гаражный номер 7.",
            source="tooru-garage-study",
            source_ref="vehicle-7",
            confidence=1.0,
            importance=0.72,
        ),
        reason="Garage sync.",
    )

    assert result.applied is True
    assert result.memory is not None
    assert result.memory.source == "tooru-garage-study"
    assert result.memory.source_ref == "vehicle-7"
    assert engine.get(result.memory.id).content.startswith("Автомобиль")
    evidence = engine.evidence(result.memory.id)
    assert len(evidence) == 1
    assert evidence[0].source_type == "tooru-garage-study"
    assert evidence[0].source_ref == "vehicle-7"
    assert guardian.status().applied == 1


def test_structured_high_risk_memory_waits_for_review(
    tmp_path: Path,
) -> None:
    _, guardian, gateway = _gateway(tmp_path)

    result = gateway.ingest(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.DECISION,
            key="project.architecture",
            content="Полностью заменить архитектуру проекта.",
            source="automation",
            confidence=1.0,
            importance=0.95,
        ),
        reason="Automated architecture change.",
    )

    assert result.applied is False
    assert result.memory is None
    assert result.decision.queue_id is not None
    assert guardian.status().queued_pending == 1
