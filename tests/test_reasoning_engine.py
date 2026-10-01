from pathlib import Path
from types import SimpleNamespace

import pytest

from tooru.ai.router import AIRouter
from tooru.api.chat import ChatRequest
from tooru.chat.pipeline import ChatPipeline
from tooru.chat.reasoning import (
    CognitiveReasoning,
    ReasoningConfig,
    ReasoningMode,
    ReasoningRoute,
    ResultVerification,
)
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope
from tooru.memory.store import SQLiteMemoryStore


class SequenceRouter:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.operations: list[str] = []
        self.observability = None

    async def generate(self, provider, request, *, module, operation):
        self.operations.append(operation)
        if not self.responses:
            raise RuntimeError("no fake response")
        return SimpleNamespace(
            text=self.responses.pop(0),
            provider=provider,
            model="fake-deepseek",
        )


class ContextMemory:
    def context_pack(self, request):
        return SimpleNamespace(
            rendered_context="<tooru_memory></tooru_memory>",
            total_memories=0,
            personal_hits=[],
            project_hits=[],
        )


class NoopGuardian:
    async def process(self, request):
        return SimpleNamespace(
            applied=[],
            pending_count=0,
            blocked_count=0,
        )

    def ingest_structured(self, memory, *, reason, auto_apply):
        return SimpleNamespace(memory_id=None, queue_id=None)


def make_guardian(tmp_path: Path) -> tuple[MemoryEngine, MemoryGuardian]:
    store = SQLiteMemoryStore(tmp_path / "reasoning.sqlite3")
    engine = MemoryEngine(store, HashEmbeddingProvider(128))
    engine.initialize()
    intelligence = MemoryIntelligence(
        engine,
        AIRouter(),
        IntelligenceConfig(),
    )
    return engine, MemoryGuardian(
        intelligence,
        store,
        GuardianConfig(),
    )


def test_complexity_gate_skips_small_talk_and_detects_work() -> None:
    reasoning = CognitiveReasoning(
        router=SequenceRouter([]),
        memory=ContextMemory(),
        guardian=NoopGuardian(),
    )

    assert not reasoning.should_plan(
        "Привет",
        response_mode="normal",
        recent_history=[],
    )
    assert reasoning.should_plan(
        "Проверь архитектуру памяти и исправь ошибки.",
        response_mode="normal",
        recent_history=[],
    )
    assert reasoning.should_plan(
        "Делай",
        response_mode="normal",
        recent_history=[
            "Нужно провести подробный анализ архитектуры проекта "
            "и реализовать исправления с тестами." * 5
        ],
    )


@pytest.mark.asyncio
async def test_pipeline_uses_plan_verifier_and_revised_answer() -> None:
    router = SequenceRouter(
        [
            (
                '{"objective":"Исправить модуль","known_facts":[],'
                '"missing_information":[],"steps":["Проверить","Исправить"],'
                '"success_criteria":["Ошибка устранена"],"risks":[],'
                '"confidence":0.9}'
            ),
            "Первоначальный ответ.",
            (
                '{"passed":true,"score":0.7,"issues":["Пропущена проверка"],'
                '"unmet_criteria":["Ошибка не подтверждена тестом"],'
                '"contradictions":[],"revised_answer":"Исправленный ответ."}'
            ),
        ]
    )
    pipeline = ChatPipeline(
        memory=ContextMemory(),
        router=router,
        guardian=NoopGuardian(),
    )
    pipeline.reasoning.config.verifier_escalation_score = 0.0

    result = await pipeline.run(
        message="Проверь и исправь архитектуру модуля.",
        remember=False,
        history=[],
        response_mode="normal",
    )

    assert result.answer == "Исправленный ответ."
    assert router.operations == [
        "reasoning_plan",
        "chat_response",
        "result_verify",
    ]


@pytest.mark.asyncio
async def test_verified_repeated_experience_creates_guardian_candidate(
    tmp_path: Path,
) -> None:
    engine, guardian = make_guardian(tmp_path)
    episode_ids: list[str] = []
    for index in range(3):
        episode = engine.add(
            MemoryCreate(
                scope=MemoryScope.PROJECT,
                project_id="dragon-tory",
                kind=MemoryKind.EPISODE,
                content=(
                    "Задача пользователя: проверить договор поставки. "
                    f"Результат Тоору: договор проверен по чек-листу {index}."
                ),
                confidence=0.96,
                importance=0.6,
                tags=["episode", "verified-outcome"],
            )
        )
        episode_ids.append(episode.id)

    router = SequenceRouter(
        [
            (
                '{"should_create":true,'
                '"key":"experience.contract_review",'
                '"content":"При проверке договора сначала сверять стороны, '
                'сроки, сумму, предмет и подтверждающие документы.",'
                '"confidence":0.93,'
                '"reason":"Повторяется в нескольких проверенных эпизодах."}'
            )
        ]
    )
    reasoning = CognitiveReasoning(
        router=router,
        memory=engine,
        guardian=guardian,
        config=ReasoningConfig(
            min_verified_episodes=3,
            similar_episode_score=0.0,
            existing_rule_score=1.0,
        ),
    )

    status = await reasoning.learn_from_experience(
        task="Проверь договор поставки.",
        answer="Договор проверен.",
        verification=ResultVerification(
            passed=True,
            score=0.95,
        ),
        episode_id=episode_ids[-1],
        session_id="chat-learning",
    )

    assert status == "learning:rule-pending=1"
    assert guardian.status().queued_pending == 1
    queued = guardian.queue_items(limit=10)
    assert queued[0].decision.kind is MemoryKind.SKILL
    assert queued[0].decision.key == "experience.contract_review"

def test_reasoning_router_uses_chain_for_simple_chat() -> None:
    reasoning = CognitiveReasoning(
        router=SequenceRouter([]),
        memory=ContextMemory(),
        guardian=NoopGuardian(),
    )

    route = reasoning.route(
        "Привет, как дела?",
        response_mode="normal",
        recent_history=[],
    )

    assert route.mode is ReasoningMode.CHAIN
    assert route.branch_count == 0
    assert "fast-path" in route.reasons



def test_memory_uncertainty_can_force_tree_without_long_prompt() -> None:
    reasoning = CognitiveReasoning(
        router=SequenceRouter([]),
        memory=ContextMemory(),
        guardian=NoopGuardian(),
    )
    hit = SimpleNamespace(
        uncertainty_score=0.82,
        memory=SimpleNamespace(id="memory-uncertain"),
    )

    route = reasoning.route(
        "Кто сейчас водитель?",
        response_mode="normal",
        recent_history=[],
        memory_hits=[hit],
    )

    assert route.mode is ReasoningMode.TREE
    assert "high-memory-uncertainty" in route.reasons

def test_reasoning_router_uses_tree_for_high_complexity() -> None:
    reasoning = CognitiveReasoning(
        router=SequenceRouter([]),
        memory=ContextMemory(),
        guardian=NoopGuardian(),
    )
    message = (
        "Проанализируй архитектуру памяти, сравни три варианта, "
        "проверь противоречия, оцени риски, исправь ошибки, "
        "спроектируй миграцию и добавь автотесты.\n"
        "Нужно выбрать лучший подход с альтернативами.\n"
        "Проверь влияние на Guardian и граф.\n"
        "Учти обратную совместимость."
    )

    route = reasoning.route(
        message,
        response_mode="analysis",
        recent_history=[],
    )

    assert route.mode is ReasoningMode.TREE
    assert route.branch_count >= 3
    assert route.max_depth >= 3


def test_reasoning_router_uses_hybrid_for_moderate_work() -> None:
    reasoning = CognitiveReasoning(
        router=SequenceRouter([]),
        memory=ContextMemory(),
        guardian=NoopGuardian(),
        config=ReasoningConfig(
            hybrid_complexity_threshold=0.25,
            tree_complexity_threshold=0.90,
        ),
    )

    route = reasoning.route(
        "Проверь модуль и сравни два варианта исправления.",
        response_mode="normal",
        recent_history=[],
    )

    assert route.mode is ReasoningMode.HYBRID
    assert route.branch_count == 3


def test_verifier_can_escalate_chain_or_hybrid_to_tree() -> None:
    reasoning = CognitiveReasoning(
        router=SequenceRouter([]),
        memory=ContextMemory(),
        guardian=NoopGuardian(),
    )
    route = ReasoningRoute(
        mode=ReasoningMode.HYBRID,
        complexity=0.5,
        memory_uncertainty=0.2,
        contradiction_count=0,
        branch_count=3,
        max_depth=2,
        reasons=["moderate-complexity"],
    )
    verification = ResultVerification(
        passed=True,
        score=0.72,
        uncertainty=0.44,
        contradictions=[],
    )

    assert reasoning.should_escalate_after_verification(
        route,
        verification,
    )


@pytest.mark.asyncio
async def test_pipeline_tree_mode_builds_tree_before_answer() -> None:
    router = SequenceRouter(
        [
            (
                '{"objective":"Разобрать сложную архитектуру",'
                '"known_facts":[],"missing_information":[],'
                '"steps":["Сравнить варианты"],'
                '"success_criteria":["Выбран подтверждённый вариант"],'
                '"risks":[],"confidence":0.8}'
            ),
            (
                '{"branches":['
                '{"title":"A","approach":"Вариант A","evidence_for":[],'
                '"evidence_against":[],"risks":[],"confidence":0.7},'
                '{"title":"B","approach":"Вариант B","evidence_for":[],'
                '"evidence_against":[],"risks":[],"confidence":0.6},'
                '{"title":"C","approach":"Вариант C","evidence_for":[],'
                '"evidence_against":[],"risks":[],"confidence":0.5}],'
                '"recommended_branch":"A","uncertainty":0.2}'
            ),
            "Итоговый ответ по сложной задаче.",
            (
                '{"passed":true,"score":0.95,"issues":[],'
                '"unmet_criteria":[],"contradictions":[],'
                '"alternative_explanations":[],"counterfactual_checks":[],'
                '"uncertainty":0.1,"revised_answer":null}'
            ),
        ]
    )
    pipeline = ChatPipeline(
        memory=ContextMemory(),
        router=router,
        guardian=NoopGuardian(),
    )

    result = await pipeline.run(
        message=(
            "Проанализируй архитектуру, сравни варианты, проверь риски, "
            "исправь ошибки, спроектируй миграцию и добавь тесты.\n"
            "Сравни альтернативы.\nПроверь противоречия.\n"
            "Учти обратную совместимость."
        ),
        remember=False,
        history=[],
        response_mode="analysis",
    )

    assert result.answer == "Итоговый ответ по сложной задаче."
    assert router.operations == [
        "reasoning_plan",
        "reasoning_tree",
        "chat_response",
        "result_verify",
    ]


@pytest.mark.asyncio
async def test_pipeline_hybrid_escalates_only_after_bad_verifier() -> None:
    router = SequenceRouter(
        [
            (
                '{"objective":"Проверить решение","known_facts":[],'
                '"missing_information":[],"steps":["Проверить"],'
                '"success_criteria":["Ответ подтверждён"],"risks":[],'
                '"confidence":0.75}'
            ),
            "Линейный ответ.",
            (
                '{"passed":true,"score":0.7,"issues":["Есть сомнение"],'
                '"unmet_criteria":[],"contradictions":["Два источника"],'
                '"alternative_explanations":["Вариант B"],'
                '"counterfactual_checks":[],"uncertainty":0.45,'
                '"revised_answer":null}'
            ),
            (
                '{"branches":['
                '{"title":"A","approach":"Проверить A","evidence_for":[],'
                '"evidence_against":[],"risks":[],"confidence":0.55},'
                '{"title":"B","approach":"Проверить B","evidence_for":[],'
                '"evidence_against":[],"risks":[],"confidence":0.8},'
                '{"title":"C","approach":"Проверить C","evidence_for":[],'
                '"evidence_against":[],"risks":[],"confidence":0.4}],'
                '"recommended_branch":"B","uncertainty":0.2}'
            ),
            "Ответ после дерева.",
            (
                '{"passed":true,"score":0.94,"issues":[],'
                '"unmet_criteria":[],"contradictions":[],'
                '"alternative_explanations":[],"counterfactual_checks":[],'
                '"uncertainty":0.12,"revised_answer":null}'
            ),
        ]
    )
    pipeline = ChatPipeline(
        memory=ContextMemory(),
        router=router,
        guardian=NoopGuardian(),
    )
    pipeline.reasoning.config.hybrid_complexity_threshold = 0.20
    pipeline.reasoning.config.tree_complexity_threshold = 0.95

    result = await pipeline.run(
        message="Проверь решение и сравни варианты.",
        remember=False,
        history=[],
        response_mode="normal",
    )

    assert result.answer == "Ответ после дерева."
    assert router.operations == [
        "reasoning_plan",
        "chat_response",
        "result_verify",
        "reasoning_tree",
        "tree_synthesis",
        "result_verify",
    ]

@pytest.mark.asyncio
async def test_simple_chain_uses_single_ai_response() -> None:
    router = SequenceRouter(["Привет! Чем помочь?"])
    pipeline = ChatPipeline(
        memory=ContextMemory(),
        router=router,
        guardian=NoopGuardian(),
    )

    result = await pipeline.run(
        message="Привет",
        remember=False,
        history=[],
        response_mode="normal",
    )

    assert result.answer == "Привет! Чем помочь?"
    assert router.operations == ["chat_response"]

def test_chat_api_has_no_manual_reasoning_mode_switch() -> None:
    assert "reasoning_mode" not in ChatRequest.model_fields
    assert "reasoning_tree" not in ChatRequest.model_fields

