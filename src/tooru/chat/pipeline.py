from dataclasses import dataclass

from tooru.ai.base import AIRequest
from tooru.ai.router import AIRouter
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import MemoryGuardian
from tooru.memory.models import (
    ConversationMessage,
    MemoryContextRequest,
    MemoryGuardianRequest,
    MemoryScope,
)

PROJECT_ID = "dragon-tory"
AI_PROVIDER = "deepseek"

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
            + "\n\n"
            + context.rendered_context
        )

        response = await self.router.generate(
            AI_PROVIDER,
            AIRequest(
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=2_000,
            ),
        )

        memory_status = await self._remember(
            user_message=message,
            assistant_message=response.text,
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
        assistant_message: str,
        remember: bool,
    ) -> str:
        if not remember:
            return "disabled"

        try:
            result = await self.guardian.process(
                MemoryGuardianRequest(
                    owner_id="local-user",
                    scope=MemoryScope.PROJECT,
                    project_id=PROJECT_ID,
                    messages=[
                        ConversationMessage(
                            role="user",
                            content=user_message,
                        ),
                        ConversationMessage(
                            role="assistant",
                            content=assistant_message,
                        ),
                    ],
                    auto_apply=True,
                    use_ai=True,
                    primary_provider=AI_PROVIDER,
                    reviewer_provider=AI_PROVIDER,
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep chat answer
            return f"memory-error:{type(exc).__name__}"

        return (
            f"applied={len(result.applied)}, "
            f"pending={result.pending_count}, "
            f"blocked={result.blocked_count}"
        )
