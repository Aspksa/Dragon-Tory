from pathlib import Path
from types import SimpleNamespace

import pytest

from tooru.ai.router import AIRouter
from tooru.chat.pipeline import ChatPipeline
from tooru.chat.reasoning import (
    CognitiveReasoning,
    ReasoningConfig,
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
                '{"passed":false,"score":0.7,"issues":["Пропущена проверка"],'
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
    assert queued[0].decision.kind is MemoryKind.INSTRUCTION
    assert queued[0].decision.key == "experience.contract_review"
