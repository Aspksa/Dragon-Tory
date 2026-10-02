from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from tooru.cognition.models import InsightStatus

router = APIRouter(prefix="/v1/cognition", tags=["cognition"])


class ReasoningFeedbackRequest(BaseModel):
    feedback: str = Field(pattern="^(helpful|unhelpful|corrected)$")
    note: str = Field(default="", max_length=4_000)


class InsightStatusRequest(BaseModel):
    status: InsightStatus


@router.get("/status")
def cognition_status(request: Request) -> dict:
    automation = request.app.state.cognition_automation
    return request.app.state.cognition.status(
        automation_running=bool(automation.running)
    ).model_dump(mode="json")


@router.get("/policy")
def cognition_policy(request: Request) -> dict:
    return request.app.state.cognition.policy().model_dump(mode="json")


@router.get("/experiences")
def cognition_experiences(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1_000),
    task_bucket: str | None = Query(default=None, max_length=120),
) -> dict:
    items = request.app.state.cognition.store.experiences(
        limit=limit,
        task_bucket=task_bucket,
    )
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "count": len(items),
    }


@router.post("/experiences/{experience_id}/feedback")
def cognition_feedback(
    experience_id: str,
    payload: ReasoningFeedbackRequest,
    request: Request,
) -> dict:
    try:
        item = request.app.state.cognition.feedback(
            experience_id,
            feedback=payload.feedback,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Reasoning experience not found.",
        ) from exc
    return item.model_dump(mode="json")


@router.get("/insights")
def cognition_insights(
    request: Request,
    status: InsightStatus | None = InsightStatus.OPEN,
    limit: int = Query(default=100, ge=1, le=1_000),
) -> dict:
    items = request.app.state.cognition.store.insights(
        status=status,
        limit=limit,
    )
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "count": len(items),
    }


@router.post("/insights/{insight_id}/status")
def cognition_insight_status(
    insight_id: str,
    payload: InsightStatusRequest,
    request: Request,
) -> dict:
    try:
        item = request.app.state.cognition.store.set_insight_status(
            insight_id,
            payload.status,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Cognition insight not found.",
        ) from exc
    return item.model_dump(mode="json")


@router.get("/graph")
def cognition_graph(
    request: Request,
    limit: int = Query(default=500, ge=1, le=5_000),
) -> dict:
    return request.app.state.cognition.store.graph(limit=limit)


@router.post("/cycle")
async def cognition_cycle(request: Request) -> dict:
    automation = request.app.state.cognition_automation
    if automation.running:
        raise HTTPException(
            status_code=409,
            detail="Cognition cycle is already running.",
        )
    return await automation.run_once()
