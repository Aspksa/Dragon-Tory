from dataclasses import dataclass

from tooru.ai.base import AIRequest
from tooru.ai.router import AIRouteResult, AIRouter
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import MemoryGuardian
from tooru.memory.models import (
    ConversationMessage,
    MemoryContextRequest,
    MemoryGuardianRequest,
    MemoryScope,
)


@dataclass(slots=True)
class ChatPipelineResult:
    answer: str
    provider: str
    model: str
    context_memories: int
    memory_status: str
    routing_reason: str
    fallback_used: bool
    attempted_providers: list[str]


class ChatPipeline:
    """Full chat path: memory context -> AI router -> Guardian."""

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
        project_id: str | None,
        provider: str,
        remember: bool,
        history: list[ConversationMessage],
    ) -> ChatPipelineResult:
        context = self.memory.context_pack(
            MemoryContextRequest(
                owner_id="local-user",
                query=message,
                project_id=project_id,
                include_personal=True,
                personal_limit=8,
                project_limit=12 if project_id else 0,
                max_chars=12_000,
            )
        )

        messages = [
            {"role": item.role, "content": item.content}
            for item in history[-20:]
            if item.role in {"user", "assistant"}
        ]
        messages.append({"role": "user", "content": message})

        system_prompt = (
            "Ты Дракончик Тоору — локальный персональный ИИ-помощник. "
            "Отвечай на русском языке, если пользователь не попросил иначе. "
            "Используй память ниже как контекст и не выдумывай "
            "отсутствующие факты. Если память конфликтует с текущим "
            "сообщением пользователя, уточни это.\n\n"
            + context.rendered_context
        )

        route = await self.router.route(
            AIRequest(
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=2_000,
            ),
            preferred=provider,
            allow_fallback=True,
        )

        memory_status = await self._remember(
            route=route,
            user_message=message,
            project_id=project_id,
            remember=remember,
        )

        return ChatPipelineResult(
            answer=route.response.text,
            provider=route.response.provider,
            model=route.response.model,
            context_memories=context.total_memories,
            memory_status=memory_status,
            routing_reason=route.reason,
            fallback_used=route.fallback_used,
            attempted_providers=route.attempted_providers,
        )

    async def _remember(
        self,
        *,
        route: AIRouteResult,
        user_message: str,
        project_id: str | None,
        remember: bool,
    ) -> str:
        if not remember:
            return "disabled"

        primary_provider = (
            "deepseek"
            if self.router.has_provider("deepseek")
            else route.selected_provider
        )
        reviewer_provider = (
            "claude"
            if self.router.has_provider("claude")
            else None
        )
        scope = (
            MemoryScope.PROJECT
            if project_id
            else MemoryScope.PERSONAL
        )

        try:
            result = await self.guardian.process(
                MemoryGuardianRequest(
                    owner_id="local-user",
                    scope=scope,
                    project_id=project_id,
                    messages=[
                        ConversationMessage(
                            role="user",
                            content=user_message,
                        ),
                        ConversationMessage(
                            role="assistant",
                            content=route.response.text,
                        ),
                    ],
                    auto_apply=True,
                    use_ai=True,
                    primary_provider=primary_provider,
                    reviewer_provider=reviewer_provider,
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep chat answer
            return f"memory-error:{type(exc).__name__}"

        return (
            f"applied={len(result.applied)}, "
            f"pending={result.pending_count}, "
            f"blocked={result.blocked_count}"
        )
