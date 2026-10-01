from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from tooru.memory.models import (
    MemoryAutomationStatus,
    MemoryConsolidateRequest,
    MemoryConsolidateResponse,
    MemoryContextPack,
    MemoryContextRequest,
    MemoryCreate,
    MemoryDelete,
    MemoryEvidence,
    MemoryEvidenceCreate,
    MemoryExtractRequest,
    MemoryExtractResponse,
    MemoryFeedback,
    MemoryGuardianAuditEvent,
    MemoryGuardianAutomationStatus,
    MemoryGuardianOutcome,
    MemoryGuardianQueueAction,
    MemoryGuardianQueueItem,
    MemoryGuardianQueueStatus,
    MemoryGuardianRequest,
    MemoryGuardianResult,
    MemoryGuardianStatus,
    MemoryIntelligenceRequest,
    MemoryIntelligenceResult,
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


@router.get("/health")
def memory_health(
    request: Request,
    deep: Annotated[bool, Query()] = False,
) -> dict:
    return request.app.state.memory.store.health_report(deep=deep)


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


@router.post("/intelligence", response_model=MemoryIntelligenceResult)
async def memory_intelligence(
    payload: MemoryIntelligenceRequest,
    request: Request,
) -> MemoryIntelligenceResult:
    return await request.app.state.memory_intelligence.process(payload)


@router.post("/guardian/process", response_model=MemoryGuardianResult)
async def guardian_process(
    payload: MemoryGuardianRequest,
    request: Request,
) -> MemoryGuardianResult:
    return await request.app.state.memory_guardian.process(payload)


@router.get("/guardian/status", response_model=MemoryGuardianStatus)
def guardian_status(request: Request) -> MemoryGuardianStatus:
    return request.app.state.memory_guardian.status()


@router.get("/guardian/events", response_model=list[MemoryGuardianAuditEvent])
def guardian_events(
    request: Request,
    outcome: Annotated[MemoryGuardianOutcome | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MemoryGuardianAuditEvent]:
    return request.app.state.memory.store.guardian_events(
        outcome=outcome,
        limit=limit,
    )


@router.get("/guardian/queue", response_model=list[MemoryGuardianQueueItem])
def guardian_queue(
    request: Request,
    queue_status: Annotated[MemoryGuardianQueueStatus | None, Query()] = None,
    due_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MemoryGuardianQueueItem]:
    return request.app.state.memory_guardian.queue_items(
        status=queue_status,
        due_only=due_only,
        limit=limit,
    )


@router.post(
    "/guardian/queue/{queue_id}/retry",
    response_model=MemoryGuardianQueueItem,
)
async def guardian_retry(
    queue_id: str,
    request: Request,
) -> MemoryGuardianQueueItem:
    try:
        return await request.app.state.memory_guardian.retry_queue_item(queue_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.post(
    "/guardian/queue/{queue_id}/approve",
    response_model=MemoryGuardianQueueItem,
)
def guardian_approve(
    queue_id: str,
    payload: MemoryGuardianQueueAction,
    request: Request,
) -> MemoryGuardianQueueItem:
    try:
        return request.app.state.memory_guardian.approve_queue_item(
            queue_id,
            reason=payload.reason,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/guardian/queue/{queue_id}/reject",
    response_model=MemoryGuardianQueueItem,
)
def guardian_reject(
    queue_id: str,
    payload: MemoryGuardianQueueAction,
    request: Request,
) -> MemoryGuardianQueueItem:
    try:
        return request.app.state.memory_guardian.reject_queue_item(
            queue_id,
            reason=payload.reason,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.post(
    "/guardian/automation/run",
    response_model=MemoryGuardianAutomationStatus,
)
async def guardian_automation_run(request: Request) -> MemoryGuardianAutomationStatus:
    return await request.app.state.memory_guardian_automation.run_once()


@router.get(
    "/guardian/automation/status",
    response_model=MemoryGuardianAutomationStatus,
)
def guardian_automation_status(request: Request) -> MemoryGuardianAutomationStatus:
    return request.app.state.memory_guardian_automation.status()


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


@router.get("/maintenance/status", response_model=MemoryAutomationStatus)
def maintenance_status(request: Request) -> MemoryAutomationStatus:
    return request.app.state.memory_automation.status()


@router.post("/sync", response_model=MemorySyncResponse)
def sync_memory(payload: MemorySyncRequest, request: Request) -> MemorySyncResponse:
    return request.app.state.memory.sync(payload)


@router.get("/{memory_id}/links", response_model=list[MemoryLink])
def get_memory_links(
    memory_id: str,
    request: Request,
    relation: Annotated[MemoryLinkType | None, Query()] = None,
) -> list[MemoryLink]:
    return request.app.state.memory.links_for(memory_id, relation)


@router.get("/{memory_id}/history", response_model=list[MemoryRevision])
def get_memory_history(
    memory_id: str,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
) -> list[MemoryRevision]:
    try:
        return request.app.state.memory.history(memory_id, owner_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.get("/{memory_id}/evidence", response_model=list[MemoryEvidence])
def get_memory_evidence(
    memory_id: str,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MemoryEvidence]:
    try:
        return request.app.state.memory.evidence(
            memory_id,
            owner_id=owner_id,
            limit=limit,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.post(
    "/{memory_id}/evidence",
    response_model=MemoryEvidence,
    status_code=status.HTTP_201_CREATED,
)
def add_memory_evidence(
    memory_id: str,
    payload: MemoryEvidenceCreate,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
) -> MemoryEvidence:
    try:
        return request.app.state.memory.add_evidence(
            memory_id,
            payload,
            owner_id=owner_id,
        )
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
