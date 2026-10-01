from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from tooru.releases import release_notes_for
from tooru.update.service import UpdateError

router = APIRouter(prefix="/v1/update", tags=["update"])


class UpdateInstallRequest(BaseModel):
    force: bool = False


def _require_local(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Установка обновлений доступна только локально.",
        )


@router.get("/status")
def update_status(request: Request) -> dict:
    payload = request.app.state.update_service.status()
    payload["release"] = release_notes_for(payload.get("local_version"))
    return payload


@router.get("/history")
def update_history(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    items = request.app.state.update_service.history(limit=limit)
    enriched = []
    for item in items:
        enriched.append(
            {
                **item,
                "release": release_notes_for(item.get("to_version")),
            }
        )
    return {"items": enriched, "count": len(enriched)}


@router.post("/check")
def update_check(request: Request) -> dict:
    try:
        payload = request.app.state.update_service.check()
        payload["release"] = release_notes_for(payload.get("local_version"))
        return payload
    except UpdateError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/install")
def update_install(
    payload: UpdateInstallRequest,
    request: Request,
) -> dict:
    _require_local(request)
    try:
        return request.app.state.update_service.start_install(
            force=payload.force
        )
    except UpdateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Внутренняя ошибка запуска updater: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc
