import re
from dataclasses import dataclass

from tooru.ai.base import AIRequest
from tooru.ai.prompt_guard import UNTRUSTED_CONTENT_POLICY, wrap_untrusted_text
from tooru.ai.router import AIRouter
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import MemoryGuardian
from tooru.memory.models import (
    ConversationMessage,
    MemoryContextRequest,
    MemoryGuardianRequest,
    MemoryScope,
)
from tooru.observability.context import observation_context

PROJECT_ID = "dragon-tory"
AI_PROVIDER = "deepseek"

_PERSONAL_MEMORY_SIGNAL = re.compile(
    r"\b("
    r"я предпочитаю|мне нравится|мне удобнее|у меня|меня зовут|"
    r"я живу|я работаю|мой день рождения|моя машина|мой автомобиль|"
    r"мой ноутбук|мой компьютер|моя семья|i prefer|i like|i live|"
    r"my name is|i work"
    r")\b",
    re.IGNORECASE,
)
_PROJECT_MEMORY_SIGNAL = re.compile(
    r"\b("
    r"проект|тоору|dragon tory|дракончик|репозитор|github|"
    r"модул|интерфейс|верси|обновлен|код|api|база данных|"
    r"договор|сч[её]т|оферт|служебн|приказ|распоряж|"
    r"project|repository|module|interface"
    r")",
    re.IGNORECASE,
)

RESPONSE_MODE_PROMPTS = {
    "brief": "Отвечай кратко и по существу, без лишних деталей.",
    "normal": "Дай ясный и достаточно подробный ответ.",
    "detailed": "Дай подробный структурированный ответ с важными деталями.",
    "code": (
        "Если задача связана с программированием, делай упор на готовый код, "
        "точные шаги и короткие пояснения. Код оформляй в Markdown-блоках."
    ),
    "analysis": (
        "Проведи глубокий анализ: раздели факты, предположения, риски и "
        "практические выводы. Не выдумывай отсутствующие данные."
    ),
}


def route_user_memory(
    user_message: str,
) -> dict[MemoryScope, list[ConversationMessage]]:
    routed: dict[MemoryScope, list[ConversationMessage]] = {
        MemoryScope.PERSONAL: [],
        MemoryScope.PROJECT: [],
    }
    parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?。！？])\s+|[;\n]+", user_message)
        if part.strip()
    ]
    for part in parts or [user_message.strip()]:
        if not part:
            continue
        is_project = bool(_PROJECT_MEMORY_SIGNAL.search(part))
        is_personal = bool(_PERSONAL_MEMORY_SIGNAL.search(part))
        scope = (
            MemoryScope.PERSONAL
            if is_personal and not is_project
            else MemoryScope.PROJECT
        )
        routed[scope].append(
            ConversationMessage(role="user", content=part)
        )
    return routed


@dataclass(slots=True)
class ChatPipelineResult:
    answer: str
    provider: str
    model: str
    context_memories: int
    memory_status: str


class ChatPipeline:
    """Chat path: memory context -> DeepSeek -> Guardian."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        router: AIRouter,
        guardian: MemoryGuardian,
    ) -> None:
        self.memory = memory
        self.router = router
        self.guardian = guardian

    async def run(
        self,
        *,
        message: str,
        remember: bool,
        history: list[ConversationMessage],
        response_mode: str = "normal",
    ) -> ChatPipelineResult:
        context = self.memory.context_pack(
            MemoryContextRequest(
                owner_id="local-user",
                query=message,
                project_id=PROJECT_ID,
                include_personal=True,
                personal_limit=8,
                project_limit=12,
                max_chars=12_000,
            )
        )

        messages = [
            {"role": item.role, "content": item.content}
            for item in history[-20:]
            if item.role in {"user", "assistant"}
        ]
        messages.append({"role": "user", "content": message})

        mode_instruction = RESPONSE_MODE_PROMPTS.get(
            response_mode,
            RESPONSE_MODE_PROMPTS["normal"],
        )
        system_prompt = (
            "Ты Дракончик Тоору — локальный персональный ИИ-помощник. "
            "Отвечай на русском языке, если пользователь не попросил иначе. "
            "Используй личную и проектную память ниже как контекст и не "
            "выдумывай отсутствующие факты. Если память конфликтует с "
            "текущим сообщением пользователя, уточни это. "
            + mode_instruction
            + " "
            + UNTRUSTED_CONTENT_POLICY
            + "\n\nПамять для справки:\n"
            + wrap_untrusted_text(
                context.rendered_context,
                source="long-term-memory",
            )
        )

        with observation_context(
            module="chat",
            source_type="chat",
            source_id="user-message",
            new_trace=True,
        ):
            if self.router.observability is not None:
                self.router.observability.event(
                    category="source",
                    stage="source",
                    operation="chat_message",
                    status="success",
                    module="chat",
                    source_type="chat",
                    source_id="user-message",
                    message="Сообщение пользователя передано Тоору.",
                )
            response = await self.router.generate(
                AI_PROVIDER,
                AIRequest(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=2_000,
                ),
                module="chat",
                operation="chat_response",
            )

            memory_status = await self._remember(
                user_message=message,
                remember=remember,
            )

        return ChatPipelineResult(
            answer=response.text,
            provider=response.provider,
            model=response.model,
            context_memories=context.total_memories,
            memory_status=memory_status,
        )

    async def _remember(
        self,
        *,
        user_message: str,
        remember: bool,
    ) -> str:
        if not remember:
            return "disabled"

        routed = route_user_memory(user_message)
        summaries: list[str] = []
        try:
            for scope in (MemoryScope.PERSONAL, MemoryScope.PROJECT):
                messages = routed[scope]
                if not messages:
                    continue
                result = await self.guardian.process(
                    MemoryGuardianRequest(
                        owner_id="local-user",
                        scope=scope,
                        project_id=(
                            PROJECT_ID
                            if scope is MemoryScope.PROJECT
                            else None
                        ),
                        messages=messages,
                        auto_apply=True,
                        use_ai=True,
                        primary_provider=AI_PROVIDER,
                        reviewer_provider=AI_PROVIDER,
                    )
                )
                summaries.append(
                    f"{scope.value}:applied={len(result.applied)},"
                    f"pending={result.pending_count},"
                    f"blocked={result.blocked_count}"
                )
        except Exception as exc:  # noqa: BLE001 - keep chat answer
            return f"memory-error:{type(exc).__name__}"

        return "; ".join(summaries) if summaries else "no-durable-signal"
