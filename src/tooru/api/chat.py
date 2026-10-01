from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from tooru.memory.models import ConversationMessage

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
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


def _friendly_ai_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "not enough money" in lowered or "insufficient" in lowered:
        return "Недостаточно средств на балансе Cloud.ru."
    if "authentication" in lowered or "api key" in lowered:
        return "Ошибка API-ключа DeepSeek. Проверьте ключ в «Настройках»."
    if "rate limit" in lowered or "429" in lowered:
        return "Лимит запросов DeepSeek временно исчерпан. Повторите позже."
    return f"Ошибка DeepSeek: {text}"


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    if not request.app.state.ai_router.has_provider("deepseek"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "DeepSeek не настроен. Откройте «Настройки» "
                "и сохраните Cloud.ru Key Secret."
            ),
        )

    try:
        result = await request.app.state.chat_pipeline.run(
            message=payload.message,
            remember=payload.remember,
            history=payload.history,
        )
    except Exception as exc:
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
    )
