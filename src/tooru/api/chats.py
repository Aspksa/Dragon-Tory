from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from tooru.chat.store import ChatNotFoundError

router = APIRouter(prefix="/v1/chats", tags=["chats"])


class ChatCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ChatRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def _not_found(exc: ChatNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Чат не найден.",
    )


@router.get("")
def list_chats(
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    items = request.app.state.chat_store.list(
        query=query,
        limit=limit,
    )
    return {"items": items, "count": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_chat(
    payload: ChatCreateRequest,
    request: Request,
) -> dict:
    return request.app.state.chat_store.create(
        payload.title or "Новый чат"
    )


@router.get("/{chat_id}")
def get_chat(chat_id: str, request: Request) -> dict:
    try:
        chat = request.app.state.chat_store.get(chat_id)
        messages = request.app.state.chat_store.messages(chat_id)
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc
    return {**chat, "messages": messages}


@router.patch("/{chat_id}")
def rename_chat(
    chat_id: str,
    payload: ChatRenameRequest,
    request: Request,
) -> dict:
    try:
        return request.app.state.chat_store.rename(
            chat_id,
            payload.title,
        )
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: str, request: Request) -> None:
    try:
        request.app.state.chat_store.delete(chat_id)
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc
