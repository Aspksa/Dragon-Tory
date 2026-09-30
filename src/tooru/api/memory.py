from fastapi import APIRouter, Request

from tooru.memory.models import MemoryCreate, MemoryItem, MemorySearch

router = APIRouter(prefix="/v1/memory", tags=["memory"])


@router.post("", response_model=MemoryItem)
def create_memory(payload: MemoryCreate, request: Request) -> MemoryItem:
    return request.app.state.memory.add(payload)


@router.post("/search", response_model=list[MemoryItem])
def search_memory(payload: MemorySearch, request: Request) -> list[MemoryItem]:
    return request.app.state.memory.search(payload)
