from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from tooru.memory.models import (
    EntityAlias,
    EntityResolution,
    GoalProgress,
    GraphPathNode,
    GreyMatterReport,
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
    MemoryScope,
    MemorySearch,
    MemorySyncRequest,
    MemorySyncResponse,
    MemoryTruthAssessment,
    MemoryUncertaintyAssessment,
    MemoryUpdate,
)
from tooru.memory.store import MemoryConflictError, MemoryNotFoundError

router = APIRouter(prefix="/v1/memory", tags=["memory"])


class EntityResolveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    scope: MemoryScope = MemoryScope.PROJECT
    project_id: str | None = Field(default="dragon-tory", max_length=200)


class EntityAliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=500)
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CausalChainRequest(BaseModel):
    problem: str = Field(min_length=1, max_length=10_000)
    cause: str = Field(min_length=1, max_length=10_000)
    action: str = Field(min_length=1, max_length=10_000)
    result: str = Field(min_length=1, max_length=10_000)
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    scope: MemoryScope = MemoryScope.PROJECT
    project_id: str | None = Field(default="dragon-tory", max_length=200)
    source_ref: str | None = Field(default=None, max_length=500)


class TaskStateRequest(BaseModel):
    state: str = Field(pattern="^(open|done|blocked)$")
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)


class CorrectionRequest(BaseModel):
    corrected_content: str = Field(min_length=1, max_length=100_000)
    reason: str = Field(default="User correction.", max_length=2_000)
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)


class SourceFeedbackRequest(BaseModel):
    confirmed: bool
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)


class GreyConsolidateRequest(BaseModel):
    owner_id: str = Field(default="local-user", min_length=1, max_length=200)
    scope: MemoryScope = MemoryScope.PROJECT
    project_id: str | None = Field(default="dragon-tory", max_length=200)
    limit: int = Field(default=500, ge=2, le=2_000)


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


@router.get("/grey-matter/status")
def grey_matter_status(request: Request) -> dict:
    embedder = request.app.state.memory.embedder
    return {
        "version": "01.00.00",
        "embedding_provider": embedder.name,
        "embedding_model": embedder.model,
        "embedding_dimensions": embedder.dimensions,
        "semantic_embeddings_active": embedder.name != "hash",
        "capabilities": [
            "semantic-memory",
            "hierarchical-memory",
            "entity-resolution",
            "causal-memory",
            "uncertainty",
            "sleep-consolidation",
            "goal-task-memory",
            "multi-hop-graph",
            "source-reliability",
            "correction-learning",
            "counterfactual-verification",
            "skill-memory",
        ],
    }


@router.post(
    "/grey-matter/entities/resolve",
    response_model=EntityResolution,
)
def resolve_entity(
    payload: EntityResolveRequest,
    request: Request,
) -> EntityResolution:
    try:
        return request.app.state.grey_matter.resolve_entity(
            payload.query,
            owner_id=payload.owner_id,
            scope=payload.scope,
            project_id=payload.project_id,
        )
    except (MemoryNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/grey-matter/entities/{memory_id}/aliases",
    response_model=EntityAlias,
)
def learn_entity_alias(
    memory_id: str,
    payload: EntityAliasRequest,
    request: Request,
) -> EntityAlias:
    try:
        return request.app.state.grey_matter.learn_entity_alias(
            memory_id,
            payload.alias,
            owner_id=payload.owner_id,
            confidence=payload.confidence,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/grey-matter/causal-chain")
def record_causal_chain(
    payload: CausalChainRequest,
    request: Request,
) -> dict:
    return request.app.state.grey_matter.record_causal_chain(
        problem=payload.problem,
        cause=payload.cause,
        action=payload.action,
        result=payload.result,
        owner_id=payload.owner_id,
        scope=payload.scope,
        project_id=payload.project_id,
        source_ref=payload.source_ref,
    )


@router.post("/grey-matter/goals/{goal_id}/tasks/{task_id}")
def link_goal_task(
    goal_id: str,
    task_id: str,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
) -> dict:
    try:
        request.app.state.grey_matter.link_task_to_goal(
            goal_id,
            task_id,
            owner_id=owner_id,
        )
        return {"ok": True, "goal_id": goal_id, "task_id": task_id}
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/grey-matter/tasks/{task_id}/state")
def set_grey_task_state(
    task_id: str,
    payload: TaskStateRequest,
    request: Request,
) -> MemoryItem:
    try:
        return request.app.state.grey_matter.set_task_state(
            task_id,
            payload.state,
            owner_id=payload.owner_id,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/grey-matter/goals/{goal_id}/progress",
    response_model=GoalProgress,
)
def grey_goal_progress(
    goal_id: str,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
) -> GoalProgress:
    try:
        return request.app.state.grey_matter.goal_progress(
            goal_id,
            owner_id=owner_id,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/grey-matter/corrections/{memory_id}")
def grey_register_correction(
    memory_id: str,
    payload: CorrectionRequest,
    request: Request,
) -> dict:
    try:
        return request.app.state.grey_matter.register_correction(
            memory_id,
            payload.corrected_content,
            owner_id=payload.owner_id,
            reason=payload.reason,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.post("/grey-matter/sources/{memory_id}/feedback")
def grey_source_feedback(
    memory_id: str,
    payload: SourceFeedbackRequest,
    request: Request,
) -> dict:
    try:
        return {
            "items": request.app.state.grey_matter.record_source_feedback(
                memory_id,
                confirmed=payload.confirmed,
                owner_id=payload.owner_id,
            )
        }
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.post(
    "/grey-matter/consolidate",
    response_model=GreyMatterReport,
)
def grey_consolidate(
    payload: GreyConsolidateRequest,
    request: Request,
) -> GreyMatterReport:
    return request.app.state.grey_matter.consolidate_scope(
        owner_id=payload.owner_id,
        scope=payload.scope,
        project_id=payload.project_id,
        limit=payload.limit,
    )


@router.get(
    "/{memory_id}/uncertainty",
    response_model=MemoryUncertaintyAssessment,
)
def memory_uncertainty(
    memory_id: str,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
) -> MemoryUncertaintyAssessment:
    try:
        return request.app.state.grey_matter.uncertainty(
            memory_id,
            owner_id=owner_id,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.get(
    "/{memory_id}/multi-hop",
    response_model=list[GraphPathNode],
)
def memory_multi_hop(
    memory_id: str,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
    depth: Annotated[int, Query(ge=1, le=6)] = 3,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[GraphPathNode]:
    try:
        return request.app.state.grey_matter.multi_hop(
            memory_id,
            owner_id=owner_id,
            depth=depth,
            limit=limit,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.get("/{memory_id}/links", response_model=list[MemoryLink])
def get_memory_links(
    memory_id: str,
    request: Request,
    relation: Annotated[MemoryLinkType | None, Query()] = None,
) -> list[MemoryLink]:
    return request.app.state.memory.links_for(memory_id, relation)


@router.get("/{memory_id}/truth", response_model=MemoryTruthAssessment)
def get_memory_truth(
    memory_id: str,
    request: Request,
    owner_id: Annotated[str, Query()] = "local-user",
) -> MemoryTruthAssessment:
    try:
        return request.app.state.memory.truth(
            memory_id,
            owner_id=owner_id,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


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
