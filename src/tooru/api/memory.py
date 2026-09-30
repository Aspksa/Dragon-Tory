from fastapi import APIRouter, HTTPException, Query, Request, status

from tooru.memory.models import (
    MemoryConsolidateRequest,
    MemoryConsolidateResponse,
    MemoryContextPack,
    MemoryContextRequest,
    MemoryCreate,
    MemoryDelete,
    MemoryExtractRequest,
    MemoryExtractResponse,
    MemoryFeedback,
    MemoryItem,
    MemoryLink,
    MemoryLinkType,
    MemoryMaintenanceReport,
    MemoryRecallHit,
    MemoryRevision,
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


@router.post("/recall", response_model=list[MemoryRecallHit])
def recall_memory(
    payload: MemorySearch,
    request: Request,
) -> list[MemoryRecallHit]:
    return request.app.state.memory.recall(payload)


@router.post("/context", response_model=MemoryContextPack)
def build_memory_context(
    payload: MemoryContextRequest,
    request: Request,
) -> MemoryContextPack:
    return request.app.state.memory.context_pack(payload)


@router.post("/extract", response_model=MemoryExtractResponse)
def extract_memory(
    payload: MemoryExtractRequest,
    request: Request,
) -> MemoryExtractResponse:
    return request.app.state.memory.extract(payload)


@router.post("/consolidate", response_model=MemoryConsolidateResponse)
def consolidate_memory(
    payload: MemoryConsolidateRequest,
    request: Request,
) -> MemoryConsolidateResponse:
    return request.app.state.memory.consolidate(payload)


@router.post("/maintenance/run", response_model=MemoryMaintenanceReport)
async def run_maintenance(request: Request) -> MemoryMaintenanceReport:
    return await request.app.state.memory_automation.run_once()


@router.get("/maintenance/latest", response_model=MemoryMaintenanceReport | None)
def latest_maintenance(request: Request) -> MemoryMaintenanceReport | None:
    return request.app.state.memory_automation.latest_report


@router.post("/sync", response_model=MemorySyncResponse)
def sync_memory(payload: MemorySyncRequest, request: Request) -> MemorySyncResponse:
    return request.app.state.memory.sync(payload)


@router.get("/{memory_id}/links", response_model=list[MemoryLink])
def get_memory_links(
    memory_id: str,
    request: Request,
    relation: MemoryLinkType | None = Query(default=None),
) -> list[MemoryLink]:
    return request.app.state.memory.links_for(memory_id, relation)


@router.get("/{memory_id}/history", response_model=list[MemoryRevision])
def get_memory_history(
    memory_id: str,
    request: Request,
    owner_id: str = Query(default="local-user"),
) -> list[MemoryRevision]:
    try:
        return request.app.state.memory.history(memory_id, owner_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.post("/{memory_id}/feedback", response_model=MemoryItem)
def memory_feedback(
    memory_id: str,
    payload: MemoryFeedback,
    request: Request,
) -> MemoryItem:
    try:
        return request.app.state.memory.feedback(memory_id, payload)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


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
