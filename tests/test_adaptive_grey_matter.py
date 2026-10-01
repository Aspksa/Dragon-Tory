from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tooru.ai.router import AIRouter
from tooru.memory.adaptive import select_retrieval_strategy
from tooru.memory.benchmark import RetrievalBenchmarkCase, evaluate_retrieval
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.grey_matter import GreyMatterService
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import (
    MemoryCreate,
    MemoryFeedback,
    MemoryKind,
    MemoryLinkType,
    MemoryRetrievalStrategy,
    MemoryScope,
    MemorySearch,
    MemoryStatus,
)
from tooru.memory.store import SQLiteMemoryStore


def make_stack(tmp_path: Path):
    store = SQLiteMemoryStore(tmp_path / "adaptive-grey.sqlite3")
    engine = MemoryEngine(store, HashEmbeddingProvider(128))
    engine.initialize()
    guardian = MemoryGuardian(
        MemoryIntelligence(
            engine,
            AIRouter(),
            IntelligenceConfig(),
        ),
        store,
        GuardianConfig(),
    )
    grey = GreyMatterService(
        memory=engine,
        intake=MemoryIntakeGateway(guardian),
    )
    return engine, guardian, grey


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "Почему автомобиль не запускается и какая причина?",
            MemoryRetrievalStrategy.CAUSAL,
        ),
        ("Найди VIN JF1SJABC1GH123456", MemoryRetrievalStrategy.LEXICAL),
        ("Что было актуально в 2024 году?", MemoryRetrievalStrategy.TEMPORAL),
        (
            "Кто связан с автомобилем и какой водитель закреплён?",
            MemoryRetrievalStrategy.GRAPH,
        ),
        (
            "Найди похожий по смыслу случай ремонта автомобиля",
            MemoryRetrievalStrategy.SEMANTIC,
        ),
        ("Где лежит договор?", MemoryRetrievalStrategy.BALANCED),
    ],
)
def test_auto_retrieval_strategy(query: str, expected) -> None:
    selected = select_retrieval_strategy(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query=query,
        )
    )
    assert selected is expected


def test_recall_exposes_selected_strategy(tmp_path: Path) -> None:
    engine, _, _ = make_stack(tmp_path)
    target = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="VIN JF1SJABC1GH123456 относится к Subaru Forester.",
        )
    )

    hits = engine.recall(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="VIN JF1SJABC1GH123456",
            limit=5,
        ),
        track_usage=False,
    )

    assert hits[0].memory.id == target.id
    assert hits[0].strategy is MemoryRetrievalStrategy.LEXICAL


def test_temporal_as_of_prefers_fact_valid_at_requested_date(
    tmp_path: Path,
) -> None:
    engine, _, _ = make_stack(tmp_path)
    old = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            key="driver.history.old",
            content="Водитель автомобиля номер семь — Иванов.",
            valid_from="2024-01-01T00:00:00+00:00",
            valid_to="2024-12-31T23:59:59+00:00",
            confidence=0.95,
        )
    )
    engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            key="driver.history.new",
            content="Водитель автомобиля номер семь — Петров.",
            valid_from="2025-01-01T00:00:00+00:00",
            confidence=0.95,
        )
    )

    hits = engine.recall(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="Кто был водителем автомобиля номер семь в 2024 году?",
            as_of="2024-06-01T00:00:00+00:00",
            limit=5,
        ),
        track_usage=False,
    )

    assert hits[0].memory.id == old.id
    assert hits[0].strategy is MemoryRetrievalStrategy.TEMPORAL


def test_truth_feedback_builds_calibration_report(tmp_path: Path) -> None:
    engine, _, grey = make_stack(tmp_path)
    item = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Контрольный факт для калибровки.",
            source="benchmark-source",
            confidence=0.72,
        )
    )

    grey.record_truth_feedback(item.id, confirmed=True)
    grey.record_truth_feedback(item.id, confirmed=True)
    grey.record_truth_feedback(item.id, confirmed=False)
    grey.record_truth_feedback(item.id, confirmed=True)

    report = grey.calibration_report(buckets=5)

    assert report.sample_count == 4
    assert 0.0 <= report.brier_score <= 1.0
    assert 0.0 <= report.expected_calibration_error <= 1.0
    assert sum(bucket.count for bucket in report.buckets) == 4
    assert engine.store.health_report()["truth_feedback_events"] == 4


def test_contradiction_clusters_keep_competing_active_facts(
    tmp_path: Path,
) -> None:
    engine, _, grey = make_stack(tmp_path)
    first = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            key="pressure.a",
            content="Давление в шине 2.2 бар.",
            confidence=0.8,
        )
    )
    second = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            key="pressure.b",
            content="Давление в шине 2.3 бар.",
            confidence=0.8,
        )
    )
    engine.store.add_link(
        first.id,
        second.id,
        MemoryLinkType.CONTRADICTS,
        1.0,
    )

    clusters = grey.contradiction_clusters()

    assert len(clusters) == 1
    assert {member.memory_id for member in clusters[0].members} == {
        first.id,
        second.id,
    }
    assert all(
        member.status is MemoryStatus.ACTIVE
        for member in clusters[0].members
    )
    assert clusters[0].unresolved is True


def test_entity_merge_requires_guardian_then_finalizes(tmp_path: Path) -> None:
    engine, guardian, grey = make_stack(tmp_path)
    canonical = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.ENTITY,
            key="company.romashka.primary",
            content="ООО Ромашка",
            importance=0.8,
        )
    )
    duplicate = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.ENTITY,
            key="company.romashka.duplicate",
            content="Ромашка ООО",
            importance=0.7,
        )
    )

    proposal = grey.propose_entity_merge(canonical.id, duplicate.id)

    assert proposal.applied is False
    assert proposal.queue_id is not None
    assert not engine.links_for(canonical.id, MemoryLinkType.SAME_ENTITY)

    guardian.approve_queue_item(
        proposal.queue_id,
        reason="Тестовое подтверждение объединения.",
    )
    result = grey.finalize_entity_merge(
        canonical.id,
        duplicate.id,
        proposal.queue_id,
    )

    assert result.applied is True
    assert any(
        link.target_id == duplicate.id
        for link in engine.links_for(
            canonical.id,
            MemoryLinkType.SAME_ENTITY,
        )
    )


def test_temporal_causality_rejects_reversed_time_and_learns_weight(
    tmp_path: Path,
) -> None:
    engine, _, grey = make_stack(tmp_path)
    cause = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.EVENT,
            content="Аккумулятор разрядился.",
            event_at="2026-01-01T08:00:00+00:00",
        )
    )
    effect = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.EVENT,
            content="Автомобиль не запустился.",
            event_at="2026-01-01T09:00:00+00:00",
        )
    )
    link = grey.link_cause(cause.id, effect.id, weight=0.70)
    stronger = grey.reinforce_causal_link(
        cause.id,
        effect.id,
        confirmed=True,
    )

    assert link.weight == pytest.approx(0.70)
    assert stronger.weight == pytest.approx(0.78)

    late_cause = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.EVENT,
            content="Позднее событие.",
            event_at="2026-01-01T10:00:00+00:00",
        )
    )
    with pytest.raises(ValueError, match="after effect"):
        grey.link_cause(late_cause.id, effect.id)


def test_adaptive_forgetting_archives_weak_note_but_protects_fact(
    tmp_path: Path,
) -> None:
    engine, _, grey = make_stack(tmp_path)
    weak = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.NOTE,
            content="Старая малозначимая служебная заметка.",
            confidence=0.4,
            importance=0.15,
        )
    )
    protected = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Критический факт остаётся в памяти.",
            importance=0.1,
        )
    )
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    with engine.store._connect() as conn:
        conn.execute(
            "UPDATE memory_items SET updated_at = ? WHERE id IN (?, ?)",
            (old, weak.id, protected.id),
        )

    report = grey.adaptive_forgetting(archive_after_days=180)

    assert report.archived >= 1
    assert report.protected >= 1
    assert engine.get(weak.id).status is MemoryStatus.ARCHIVED
    assert engine.get(protected.id).status is MemoryStatus.ACTIVE


def test_adaptive_forgetting_reinforces_useful_episode(
    tmp_path: Path,
) -> None:
    engine, _, grey = make_stack(tmp_path)
    episode = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.EPISODE,
            content="Успешная диагностика автомобиля.",
            importance=0.4,
            confidence=0.95,
        )
    )
    for _ in range(5):
        engine.feedback(
            episode.id,
            MemoryFeedback(helpful=True),
        )

    report = grey.adaptive_forgetting()

    assert report.reinforced >= 1
    assert engine.get(episode.id).importance > 0.4


def test_retrieval_benchmark_reports_quality_and_strategy(
    tmp_path: Path,
) -> None:
    engine, _, _ = make_stack(tmp_path)
    target = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Контрольная запись BENCH-0042 для поиска.",
        )
    )
    for index in range(40):
        engine.store.add(
            MemoryCreate(
                scope=MemoryScope.PROJECT,
                project_id="dragon-tory",
                kind=MemoryKind.NOTE,
                content=f"Шумовая запись номер {index}.",
            )
        )

    report = evaluate_retrieval(
        engine,
        [
            RetrievalBenchmarkCase(
                query="Найди BENCH-0042",
                expected_memory_id=target.id,
            )
        ],
        corpus_size=41,
    )

    assert report.corpus_size == 41
    assert report.query_count == 1
    assert report.hit_at_1 == 1.0
    assert report.hit_at_5 == 1.0
    assert report.mean_reciprocal_rank == 1.0
    assert sum(report.strategies.values()) == 1
