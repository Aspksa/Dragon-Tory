from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from tooru.ai.router import AIRoutingError
from tooru.memory.models import ConversationMessage

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    project_id: str | None = Field(default="dragon-tory", max_length=200)
    provider: str = Field(default="auto", pattern="^(auto|deepseek|claude)$")
    remember: bool = True
    history: list[ConversationMessage] = Field(
        default_factory=list,
        max_length=40,
    )


class ChatResponse(BaseModel):
    answer: str
    provider: str
    model: str
    context_memories: int
    memory_status: str
    routing_reason: str
    fallback_used: bool
    attempted_providers: list[str]


def _friendly_ai_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "not enough money" in lowered or "insufficient" in lowered:
        return "Недостаточно средств на балансе ИИ-провайдера."
    if "authentication" in lowered or "api key" in lowered:
        return "Ошибка API-ключа. Проверьте ключ в разделе «Настройки»."
    if "rate limit" in lowered or "429" in lowered:
        return "Лимит запросов ИИ временно исчерпан. Повторите позже."
    return f"Ошибка ИИ: {text}"


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    try:
        result = await request.app.state.chat_pipeline.run(
            message=payload.message,
            project_id=payload.project_id,
            provider=payload.provider,
            remember=payload.remember,
            history=payload.history,
        )
    except AIRoutingError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_friendly_ai_error(exc),
        ) from exc

    return ChatResponse(
        answer=result.answer,
        provider=result.provider,
        model=result.model,
        context_memories=result.context_memories,
        memory_status=result.memory_status,
        routing_reason=result.routing_reason,
        fallback_used=result.fallback_used,
        attempted_providers=result.attempted_providers,
    )
