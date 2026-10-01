from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from tooru.ai.base import AIRequest
from tooru.ai.prompt_guard import UNTRUSTED_CONTENT_POLICY, wrap_untrusted_text
from tooru.ai.router import AIRouter
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import MemoryGuardian
from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope, MemorySearch

AI_PROVIDER = "deepseek"
PROJECT_ID = "dragon-tory"


class ReasoningPlan(BaseModel):
    objective: str = Field(min_length=1, max_length=2_000)
    known_facts: list[str] = Field(default_factory=list, max_length=12)
    missing_information: list[str] = Field(default_factory=list, max_length=12)
    steps: list[str] = Field(min_length=1, max_length=12)
    success_criteria: list[str] = Field(default_factory=list, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    used_fallback: bool = False


class ResultVerification(BaseModel):
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list, max_length=20)
    unmet_criteria: list[str] = Field(default_factory=list, max_length=20)
    contradictions: list[str] = Field(default_factory=list, max_length=20)
    revised_answer: str | None = Field(default=None, max_length=20_000)
    used_fallback: bool = False


class ExperienceRuleCandidate(BaseModel):
    should_create: bool = False
    key: str | None = Field(default=None, max_length=200)
    content: str = Field(default="", max_length=4_000)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=2_000)


@dataclass(slots=True)
class ReasoningConfig:
    verification_learning_threshold: float = 0.85
    min_verified_episodes: int = 3
    similar_episode_score: float = 0.42
    existing_rule_score: float = 0.55


class CognitiveReasoning:
    """Planner, verifier and guarded experience learner for complex chat tasks."""

    _complex_signal = re.compile(
        r"\b("
        r"проанализ|исслед|проверь|сравни|спроектир|разработ|реализ|"
        r"исправ|оптимиз|рефактор|интегрир|мигрир|автотест|архитект|"
        r"создай проект|собери проект|документ|договор|табел|гараж|"
        r"analy[sz]|implement|refactor|debug|design|architecture|migrat"
        r")",
        re.IGNORECASE,
    )
    _continuation_signal = re.compile(
        r"^\s*(делай|делац|продолжай|дальше|исправляй|начинай|делаем)\s*[.!?]*\s*$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        router: AIRouter,
        memory: MemoryEngine,
        guardian: MemoryGuardian,
        config: ReasoningConfig | None = None,
    ) -> None:
        self.router = router
        self.memory = memory
        self.guardian = guardian
        self.config = config or ReasoningConfig()

    def should_plan(
        self,
        message: str,
        *,
        response_mode: str,
        recent_history: list[str] | None = None,
    ) -> bool:
        text = message.strip()
        if response_mode in {"analysis", "code", "detailed"}:
            return True
        if len(text) >= 280 or text.count("\n") >= 3:
            return True
        if self._complex_signal.search(text):
            return True
        if self._continuation_signal.match(text):
            previous = " ".join((recent_history or [])[-2:])
            return len(previous) >= 240 or bool(self._complex_signal.search(previous))
        action_count = len(
            re.findall(
                r"\b(сделай|добавь|проверь|исправь|обнови|создай|удали|"
                r"проанализируй|сравни|подключи)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        return action_count >= 2
