import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from tooru.chat.store import ChatNotFoundError
from tooru.chat.workflows import (
    create_weekend_work_document,
    is_weekend_work_request,
)
from tooru.memory.models import ConversationMessage

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    chat_id: str | None = None
    request_id: str | None = Field(default=None, max_length=100)
    message: str = Field(min_length=1, max_length=20_000)
    remember: bool = True
    response_mode: str = Field(
        default="normal",
        pattern="^(brief|normal|detailed|code|analysis)$",
    )


class RetryRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=100)
    remember: bool = True
    response_mode: str = Field(
        default="normal",
        pattern="^(brief|normal|detailed|code|analysis)$",
    )


class ChatResponse(BaseModel):
    chat_id: str
    title: str
    answer: str
    provider: str
    model: str
    context_memories: int
    memory_status: str
    created_document_id: str | None = None
    created_document_path: str | None = None


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


def _history_to_messages(
    items: list[dict],
) -> list[ConversationMessage]:
    return [
        ConversationMessage(
            role=item["role"],
            content=item["content"],
        )
        for item in items[-40:]
        if item["role"] in {"user", "assistant"}
    ]


async def _run_generation(
    *,
    request: Request,
    request_id: str,
    chat_id: str,
    message: str,
    remember: bool,
    history: list[ConversationMessage],
    response_mode: str,
    replace_after_sequence: int | None = None,
) -> ChatResponse:
    existing = request.app.state.chat_tasks.get(request_id)
    if existing is not None and not existing.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Запрос с таким идентификатором уже выполняется.",
        )

    task = asyncio.create_task(
        request.app.state.chat_pipeline.run(
            message=message,
            remember=remember,
            history=history,
            response_mode=response_mode,
        )
    )
    request.app.state.chat_tasks[request_id] = task

    try:
        result = await task
    except asyncio.CancelledError as exc:
        raise HTTPException(
            status_code=499,
            detail="Генерация остановлена пользователем.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_friendly_ai_error(exc),
        ) from exc
    finally:
        request.app.state.chat_tasks.pop(request_id, None)

    if replace_after_sequence is None:
        request.app.state.chat_store.add_message(
            chat_id,
            role="assistant",
            content=result.answer,
        )
    else:
        request.app.state.chat_store.replace_after(
            chat_id,
            sequence=replace_after_sequence,
            assistant_content=result.answer,
        )
    chat = request.app.state.chat_store.get(chat_id)
    return ChatResponse(
        chat_id=chat_id,
        title=chat["title"],
        answer=result.answer,
        provider=result.provider,
        model=result.model,
        context_memories=result.context_memories,
        memory_status=result.memory_status,
    )


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

    store = request.app.state.chat_store
    try:
        if payload.chat_id:
            chat_item = store.get(payload.chat_id)
        else:
            chat_item = store.create()
    except ChatNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден.",
        ) from exc

    chat_id = str(chat_item["id"])
    history = _history_to_messages(store.messages(chat_id, limit=40))
    store.add_message(
        chat_id,
        role="user",
        content=payload.message,
    )
    store.auto_title(chat_id, payload.message)

    if is_weekend_work_request(payload.message):
        try:
            created = await create_weekend_work_document(
                request=request,
                message=payload.message,
            )
            answer = (
                created["draft"]
                + "\n\n---\n"
                + "✅ Документ создан и сохранён.\n"
                + f"Путь: {created['path']}\n"
                + f"Tory Document ID: {created['document_id']}\n"
                + (
                    f"Эталонов предприятия использовано: "
                    f"{len(created['references'])}.\n"
                )
                + (
                    "Часы для табеля: "
                    + (
                        str(created["work_hours"])
                        if created["work_hours"] is not None
                        else "[нужно заполнить]"
                    )
                )
            )
            store.add_message(
                chat_id,
                role="assistant",
                content=answer,
            )
            chat_item = store.get(chat_id)
            return ChatResponse(
                chat_id=chat_id,
                title=chat_item["title"],
                answer=answer,
                provider=created["provider"],
                model=created["model"],
                context_memories=0,
                memory_status="workflow:weekend-work",
                created_document_id=created["document_id"],
                created_document_path=created["path"],
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Не удалось создать документ: {exc}",
            ) from exc

    request_id = payload.request_id or str(uuid.uuid4())
    return await _run_generation(
        request=request,
        request_id=request_id,
        chat_id=chat_id,
        message=payload.message,
        remember=payload.remember,
        history=history,
        response_mode=payload.response_mode,
    )


@router.post(
    "/{chat_id}/retry",
    response_model=ChatResponse,
)
async def retry_chat(
    chat_id: str,
    payload: RetryRequest,
    request: Request,
) -> ChatResponse:
    if not request.app.state.ai_router.has_provider("deepseek"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DeepSeek не настроен.",
        )

    try:
        message, history_items, user_sequence = (
            request.app.state.chat_store.retry_context(chat_id)
        )
    except ChatNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    request_id = payload.request_id or str(uuid.uuid4())
    return await _run_generation(
        request=request,
        request_id=request_id,
        chat_id=chat_id,
        message=message,
        remember=payload.remember,
        history=_history_to_messages(history_items),
        response_mode=payload.response_mode,
        replace_after_sequence=user_sequence,
    )


@router.post("/cancel/{request_id}")
async def cancel_generation(
    request_id: str,
    request: Request,
) -> dict:
    task = request.app.state.chat_tasks.get(request_id)
    if task is None or task.done():
        return {"cancelled": False}
    task.cancel()
    return {"cancelled": True}
