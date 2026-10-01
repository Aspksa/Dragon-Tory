import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tooru.ai.router import AIRouter
from tooru.chat.reasoning import CognitiveReasoning, ReasoningPlan
from tooru.memory.embedding import FastEmbedProvider, HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.grey_matter import GreyMatterService
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.maintenance import MemoryAutomation
from tooru.memory.models import (
    MemoryCreate,
    MemoryKind,
    MemoryLinkType,
    MemoryScope,
    MemorySearch,
)
from tooru.memory.store import SQLiteMemoryStore


def make_stack(tmp_path: Path):
    store = SQLiteMemoryStore(tmp_path / "grey-matter.sqlite3")
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
    intake = MemoryIntakeGateway(guardian)
    grey = GreyMatterService(memory=engine, intake=intake)
    return engine, guardian, grey


def test_fastembed_provider_supports_local_semantic_vectors(monkeypatch) -> None:
    class FakeVector:
        def __init__(self, values):
            self.values = values

        def tolist(self):
            return list(self.values)

    class FakeTextEmbedding:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def embed(self, texts):
            for index, _text in enumerate(texts, start=1):
                yield FakeVector([float(index), 0.5, 0.25])

    monkeypatch.setitem(
        sys.modules,
        "fastembed",
        SimpleNamespace(TextEmbedding=FakeTextEmbedding),
    )

    provider = FastEmbedProvider(
        model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dimensions=384,
    )
    vectors = provider.embed(["автомобиль", "машина"])

    assert provider.name == "fastembed"
    assert provider.model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert provider.dimensions == 3
    assert vectors[0] == [1.0, 0.5, 0.25]
    assert vectors[1] == [2.0, 0.5, 0.25]


def test_entity_alias_resolution_and_scope_isolation(tmp_path: Path) -> None:
    engine, _, grey = make_stack(tmp_path)
    entity = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.ENTITY,
            content="ООО Ромашка",
            importance=0.8,
        )
    )

    alias = grey.learn_entity_alias(
        entity.id,
        "Ромашка ООО",
        confidence=0.97,
    )
    resolved = grey.resolve_entity(
        "Ромашка",
        scope=MemoryScope.PROJECT,
        project_id="dragon-tory",
    )

    assert alias.canonical_memory_id == entity.id
    assert resolved.canonical_memory_id == entity.id
    assert resolved.confidence == pytest.approx(0.97)

    personal = engine.add(
        MemoryCreate(
            scope=MemoryScope.PERSONAL,
            kind=MemoryKind.ENTITY,
            content="Ромашка",
        )
    )
    personal_resolved = grey.resolve_entity(
        "Ромашка",
        scope=MemoryScope.PERSONAL,
        project_id=None,
    )
    assert personal_resolved.canonical_memory_id == personal.id


def test_hierarchical_consolidation_creates_part_of_links(tmp_path: Path) -> None:
    engine, _, grey = make_stack(tmp_path)
    first = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Гаражный номер 7 относится к Subaru Forester.",
            importance=0.7,
        )
    )
    second = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.TASK,
            content="Проверить страховку Subaru Forester.",
            importance=0.7,
        )
    )

    report = grey.consolidate_scope(
        scope=MemoryScope.PROJECT,
        project_id="dragon-tory",
    )

    summaries = engine.store.scope_items(
        owner_id="local-user",
        scope=MemoryScope.PROJECT,
        project_id="dragon-tory",
        kinds={MemoryKind.SUMMARY},
    )
    assert report.summaries_created == 1
    assert summaries
    summary_id = summaries[0].id
    assert any(
        link.target_id == summary_id
        for link in engine.links_for(first.id, MemoryLinkType.PART_OF)
    )
    assert any(
        link.target_id == summary_id
        for link in engine.links_for(second.id, MemoryLinkType.PART_OF)
    )


def test_causal_memory_and_three_hop_reasoning(tmp_path: Path) -> None:
    engine, _, grey = make_stack(tmp_path)

    chain = grey.record_causal_chain(
        problem="Subaru не запускается.",
        cause="Аккумулятор разряжен.",
        action="Заменили аккумулятор.",
        result="Subaru снова запускается.",
    )

    assert all(chain[key]["memory_id"] for key in chain)
    cause_id = chain["cause"]["memory_id"]
    result_id = chain["result"]["memory_id"]
    path = grey.multi_hop(cause_id, depth=3, limit=20)

    assert result_id in {node.memory_id for node in path}
    assert any(
        link.relation is MemoryLinkType.CAUSES
        for link in engine.links_for(cause_id)
    )


def test_uncertainty_and_source_reliability_learning(tmp_path: Path) -> None:
    engine, _, grey = make_stack(tmp_path)
    fact = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Давление в шине 2.2 бар.",
            source="sensor-x",
            confidence=0.55,
            importance=0.6,
        )
    )
    alternative = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Давление в шине 2.5 бар.",
            source="manual-check",
            confidence=0.8,
            importance=0.6,
        )
    )
    engine.store.add_link(
        fact.id,
        alternative.id,
        MemoryLinkType.CONTRADICTS,
        1.0,
    )

    before = engine.truth(fact.id)
    uncertainty = grey.uncertainty(fact.id)
    for _ in range(4):
        grey.record_source_feedback(fact.id, confirmed=True)
    after = engine.truth(fact.id)

    assert uncertainty.conflict_count == 1
    assert uncertainty.alternatives
    assert after.source_reliability_score > before.source_reliability_score
    assert after.trust_score > before.trust_score


def test_goal_task_memory_tracks_dependencies(tmp_path: Path) -> None:
    engine, _, grey = make_stack(tmp_path)
    goal = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.GOAL,
            content="Подготовить автомобиль к зиме.",
            importance=0.8,
        )
    )
    tires = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.TASK,
            content="Купить зимние шины.",
            tags=["task:open"],
        )
    )
    install = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.TASK,
            content="Установить зимние шины.",
            tags=["task:open"],
        )
    )
    grey.link_task_to_goal(goal.id, tires.id)
    grey.link_task_to_goal(goal.id, install.id)
    grey.link_task_dependency(install.id, tires.id)

    progress = grey.goal_progress(goal.id)
    assert progress.open_tasks == 1
    assert progress.blocked_tasks == 1

    grey.set_task_state(tires.id, "done")
    progress = grey.goal_progress(goal.id)
    assert progress.completed_tasks == 1
    assert progress.open_tasks == 1
    assert progress.blocked_tasks == 0

    grey.set_task_state(install.id, "done")
    progress = grey.goal_progress(goal.id)
    assert progress.completion == 1.0


def test_two_hop_graph_signal_reaches_recall(tmp_path: Path) -> None:
    engine, _, _ = make_stack(tmp_path)
    first = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.ENTITY,
            content="Уникальный автомобиль Альфа.",
            importance=0.8,
        )
    )
    middle = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.RELATIONSHIP,
            content="Водитель автомобиля Альфа — Петров.",
            importance=0.5,
        )
    )
    distant = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Страховой полис Петрова заканчивается в декабре.",
            importance=0.4,
        )
    )
    engine.store.add_link(
        first.id,
        middle.id,
        MemoryLinkType.RELATED,
        1.0,
    )
    engine.store.add_link(
        middle.id,
        distant.id,
        MemoryLinkType.RELATED,
        1.0,
    )

    hits = engine.recall(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="Уникальный автомобиль Альфа",
            limit=10,
        ),
        track_usage=False,
    )
    by_id = {hit.memory.id: hit for hit in hits}

    assert distant.id in by_id
    assert by_id[distant.id].graph_score > 0


def test_chat_correction_becomes_guarded_lesson(tmp_path: Path) -> None:
    engine, _, grey = make_stack(tmp_path)

    status = grey.learn_chat_correction(
        user_message="Нет, правильно: водитель Петров, а не Иванов.",
        previous_assistant="Водитель автомобиля — Иванов.",
        session_id="chat-correction",
    )

    assert status == "correction:lesson-applied=1"
    lessons = engine.store.scope_items(
        owner_id="local-user",
        scope=MemoryScope.PROJECT,
        project_id="dragon-tory",
        kinds={MemoryKind.LESSON},
    )
    assert len(lessons) == 1
    assert "Петров" in lessons[0].content


def test_fix_command_is_not_mistaken_for_chat_correction(
    tmp_path: Path,
) -> None:
    _, _, grey = make_stack(tmp_path)

    status = grey.learn_chat_correction(
        user_message="Исправь код модуля памяти и добавь тест.",
        previous_assistant="Предыдущий технический ответ.",
        session_id="chat-fix-command",
    )

    assert status == "correction:no-signal"


def test_explicit_fact_correction_is_not_silently_applied(tmp_path: Path) -> None:
    engine, guardian, grey = make_stack(tmp_path)
    wrong = engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.FACT,
            content="Водитель автомобиля №7 — Иванов.",
            key="garage.vehicle7.driver",
            importance=0.8,
        )
    )

    result = grey.register_correction(
        wrong.id,
        "Водитель автомобиля №7 — Петров.",
        reason="Пользователь подтвердил нового водителя.",
    )

    assert result["corrected_memory_id"] is None
    assert result["queue_id"] is not None
    assert guardian.status().queued_pending == 1
    assert engine.get(wrong.id).content.endswith("Иванов.")


@pytest.mark.asyncio
async def test_memory_automation_runs_grey_matter_sleep_cycle(
    tmp_path: Path,
) -> None:
    engine, _, _ = make_stack(tmp_path)
    engine.add(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.NOTE,
            content="Материал для фоновой консолидации.",
        )
    )

    class FakeGrey:
        def __init__(self):
            self.calls = []

        def consolidate_scope(self, **kwargs):
            self.calls.append(kwargs)

    fake = FakeGrey()
    automation = MemoryAutomation(
        engine,
        interval_seconds=3600,
        archive_after_days=180,
        archive_max_importance=0.3,
        archive_max_access_count=1,
        auto_consolidate_threshold=1000,
        consolidate_cooldown_hours=24,
        grey_matter=fake,
    )

    await automation.run_once()

    assert fake.calls
    assert fake.calls[0]["project_id"] == "dragon-tory"
    assert fake.calls[0]["create_summary"] is False


class VerifyRouter:
    def __init__(self):
        self.observability = None

    async def generate(self, provider, request, *, module, operation):
        assert operation == "result_verify"
        return SimpleNamespace(
            text=(
                '{"passed":true,"score":0.91,"issues":[],'
                '"unmet_criteria":[],"contradictions":[],'
                '"alternative_explanations":["Возможна другая причина."],'
                '"counterfactual_checks":["Если датчик ошибочен, вывод меняется."],'
                '"uncertainty":0.18,"revised_answer":null}'
            )
        )


@pytest.mark.asyncio
async def test_verifier_returns_counterfactual_and_uncertainty(
    tmp_path: Path,
) -> None:
    engine, guardian, _ = make_stack(tmp_path)
    reasoning = CognitiveReasoning(
        router=VerifyRouter(),
        memory=engine,
        guardian=guardian,
    )
    verification = await reasoning.verify(
        task="Проверь причину неисправности.",
        plan=ReasoningPlan(
            objective="Проверить причину",
            steps=["Сверить факты"],
        ),
        answer="Причина — аккумулятор.",
        context="Есть измерение напряжения.",
    )

    assert verification.passed is True
    assert verification.uncertainty == pytest.approx(0.18)
    assert verification.alternative_explanations
    assert verification.counterfactual_checks


def test_learned_skill_is_high_impact_guardian_memory(tmp_path: Path) -> None:
    _, guardian, _ = make_stack(tmp_path)
    decision = guardian.ingest_structured(
        MemoryCreate(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            kind=MemoryKind.SKILL,
            content=(
                "При проверке договора сначала сверять стороны, предмет, "
                "сроки, сумму и доказательства."
            ),
            source="experience-learning",
            confidence=0.95,
            importance=0.75,
            tags=["skill-memory"],
        ),
        reason="Repeated verified experience.",
    )

    assert decision.queue_id is not None
    assert decision.memory_id is None
