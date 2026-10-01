from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(
    prefix="/v1/observability",
    tags=["observability"],
)


@router.get("/summary")
def observability_summary(
    request: Request,
    limit: int = Query(default=50, ge=10, le=200),
    hours: int = Query(default=24, ge=1, le=168),
) -> dict:
    return request.app.state.observability.summary(
        limit=limit,
        hours=hours,
    )


@router.get("/traces/{trace_id}")
def observability_trace(
    trace_id: str,
    request: Request,
) -> dict:
    items = request.app.state.observability.recent(
        trace_id=trace_id,
        limit=200,
    )
    return {
        "trace_id": trace_id,
        "items": items,
        "count": len(items),
    }
