import asyncio
import hashlib
import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request, status
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


class ChatDocumentResponse(BaseModel):
    chat_id: str
    title: str
    document_id: str
    name: str
    kind: str | None = None
    extraction_method: str | None = None
    ocr_used: bool = False
    indexed_chunks: int = 0
    ai_studied: bool = False
    provider: str | None = None
    model: str | None = None
    memory_status: str | None = None
    memory_id: str | None = None
    summary: str = ""
    error: str | None = None


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


def _safe_chat_filename(value: str) -> str:
    decoded = unquote(value).replace("\\", "/")
    name = Path(decoded).name.strip().strip(".")
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не указано имя файла.",
        )
    return name[:255]


async def _receive_chat_file(
    request: Request,
    *,
    max_bytes: int,
) -> tuple[Path, int, str]:
    temp = (
        request.app.state.cloud_store.incoming_dir
        / f"{uuid.uuid4().hex}.chat-upload"
    )
    size_bytes = 0
    digest = hashlib.sha256()
    try:
        with temp.open("wb") as target:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "Файл слишком большой. Максимальный размер: "
                            f"{max_bytes // (1024 * 1024)} МБ."
                        ),
                    )
                digest.update(chunk)
                target.write(chunk)
        if size_bytes < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Получен пустой файл.",
            )
        return temp, size_bytes, digest.hexdigest()
    except Exception:
        temp.unlink(missing_ok=True)
        raise


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


async def _refresh_chat_working_memory(
    request: Request,
    chat_id: str,
) -> None:
    store = request.app.state.chat_store
    chat = store.get(chat_id)
    total = int(chat.get("message_count") or 0)
    covered = int(chat.get("summary_message_count") or 0)
    target = max(0, total - 20)
    pending = target - covered
    if pending < 20:
        return

    all_messages = store.messages(chat_id)
    batch_end = min(target, covered + 40)
    batch = all_messages[covered:batch_end]
    messages = [
        ConversationMessage(role=item["role"], content=item["content"])
        for item in batch
        if item["role"] in {"user", "assistant"}
    ]
    if not messages:
        return
    try:
        summary = await request.app.state.chat_pipeline.summarize_conversation(
            existing_summary=str(chat.get("summary") or ""),
            messages=messages,
        )
    except Exception:  # noqa: BLE001 - summary failure must not break chat
        return
    store.update_summary(
        chat_id,
        summary=summary,
        covered_messages=batch_end,
    )


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
            conversation_summary=str(
                request.app.state.chat_store.get(chat_id).get("summary") or ""
            ),
            session_id=chat_id,
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
    await _refresh_chat_working_memory(request, chat_id)
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


@router.post(
    "/documents",
    response_model=ChatDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_chat_document(
    request: Request,
    name: str = Query(min_length=1, max_length=512),
    chat_id: str | None = Query(default=None, max_length=128),
) -> ChatDocumentResponse:
    store = request.app.state.chat_store
    try:
        chat_item = store.get(chat_id) if chat_id else store.create()
    except ChatNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден.",
        ) from exc

    resolved_chat_id = str(chat_item["id"])
    safe_name = _safe_chat_filename(name)
    temp, size_bytes, sha256 = await _receive_chat_file(
        request,
        max_bytes=request.app.state.settings.cloud_max_upload_bytes,
    )

    document = None
    try:
        document = request.app.state.cloud_store.register_upload(
            temp,
            name=safe_name,
            content_type=request.headers.get(
                "content-type",
                "application/octet-stream",
            ).split(";", 1)[0],
            size_bytes=size_bytes,
            sha256=sha256,
            source="chat-upload",
        )
        document_id = str(document["id"])
        request.app.state.cloud_smart.ensure_document(document_id)
        request.app.state.cloud_smart.record_provenance(
            document_id,
            "uploaded_via_chat",
            actor="user",
            source_ref=resolved_chat_id,
            details={
                "name": safe_name,
                "chat_id": resolved_chat_id,
                "version": document["version"],
            },
        )
        store.add_message(
            resolved_chat_id,
            role="user",
            content=f"📎 Документ: {safe_name}",
        )
        store.auto_title(resolved_chat_id, safe_name)

        try:
            studied = await request.app.state.chat_document_assistant.study(
                document_id,
                chat_id=resolved_chat_id,
            )
            answer = (
                f"✅ Изучил документ «{safe_name}».\n\n"
                f"Тип: {studied.get('kind') or 'документ'}.\n"
                f"Извлечение: {studied.get('extraction_method') or '—'}"
                f"{' · OCR' if studied.get('ocr_used') else ''}.\n"
                f"Индекс: {studied.get('indexed_chunks') or 0} фрагментов.\n"
                f"AI: {'изучил' if studied.get('ai_studied') else 'локальный анализ'}.\n"
                f"Память: {studied.get('memory_status') or '—'}.\n"
                f"Tory Document ID: {document_id}.\n\n"
                + str(studied.get("summary") or "")
            )
            if studied.get("ai_error"):
                answer += (
                    "\n\n⚠️ Внешний AI временно недоступен, "
                    "но локальный индекс и анализ сохранены."
                )
            store.add_message(
                resolved_chat_id,
                role="assistant",
                content=answer,
            )
            current = store.get(resolved_chat_id)
            return ChatDocumentResponse(
                chat_id=resolved_chat_id,
                title=current["title"],
                document_id=document_id,
                name=safe_name,
                kind=studied.get("kind"),
                extraction_method=studied.get("extraction_method"),
                ocr_used=bool(studied.get("ocr_used")),
                indexed_chunks=int(studied.get("indexed_chunks") or 0),
                ai_studied=bool(studied.get("ai_studied")),
                provider=studied.get("provider"),
                model=studied.get("model"),
                memory_status=studied.get("memory_status"),
                memory_id=studied.get("memory_id"),
                summary=str(studied.get("summary") or ""),
                error=studied.get("ai_error"),
            )
        except Exception as exc:  # noqa: BLE001 - keep uploaded file accessible
            error_text = f"{type(exc).__name__}: {str(exc)[:700]}"
            answer = (
                f"📎 Документ «{safe_name}» сохранён в «Мой диск», "
                "но полностью изучить его пока не удалось.\n"
                f"Tory Document ID: {document_id}.\n"
                f"Причина: {error_text}"
            )
            store.add_message(
                resolved_chat_id,
                role="assistant",
                content=answer,
            )
            current = store.get(resolved_chat_id)
            return ChatDocumentResponse(
                chat_id=resolved_chat_id,
                title=current["title"],
                document_id=document_id,
                name=safe_name,
                error=error_text,
            )
    finally:
        temp.unlink(missing_ok=True)


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
    working = store.working_memory(chat_id, recent_limit=40)
    history = _history_to_messages(working["recent_messages"])
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
            await _refresh_chat_working_memory(request, chat_id)
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
