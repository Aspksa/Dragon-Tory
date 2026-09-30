from fastapi import APIRouter, HTTPException, Query, Request, status

from tooru.memory.models import (
    MemoryCreate,
    MemoryDelete,
    MemoryItem,
    MemorySearch,
    MemorySyncRequest,
    MemorySyncResponse,
    MemoryUpdate,
)
from tooru.memory.store import MemoryConflictError, MemoryNotFoundError

router = APIRouter(prefix="/v1/memory", tags=["memory"])


@router.post("", response_model=MemoryItem)
def create_memory(payload: MemoryCreate, request: Request) -> MemoryItem:
    return request.app.state.memory.add(payload)


@router.post("/search", response_model=list[MemoryItem])
def search_memory(payload: MemorySearch, request: Request) -> list[MemoryItem]:
    return request.app.state.memory.search(payload)


@router.post("/sync", response_model=MemorySyncResponse)
def sync_memory(payload: MemorySyncRequest, request: Request) -> MemorySyncResponse:
    return request.app.state.memory.sync(payload)


@router.get("/{memory_id}", response_model=MemoryItem)
def get_memory(
    memory_id: str,
    request: Request,
    owner_id: str = Query(default="local-user"),
) -> MemoryItem:
    try:
        return request.app.state.memory.get(memory_id, owner_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.patch("/{memory_id}", response_model=MemoryItem)
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    request: Request,
    owner_id: str = Query(default="local-user"),
) -> MemoryItem:
    try:
        return request.app.state.memory.update(memory_id, owner_id, payload)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except MemoryConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete("/{memory_id}", response_model=MemoryItem)
def delete_memory(
    memory_id: str,
    payload: MemoryDelete,
    request: Request,
) -> MemoryItem:
    try:
        return request.app.state.memory.delete(memory_id, payload)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except MemoryConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
