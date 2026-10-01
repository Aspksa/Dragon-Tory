from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from tooru.update.service import UpdateError

router = APIRouter(prefix="/v1/update", tags=["update"])


class UpdateInstallRequest(BaseModel):
    force: bool = False


def _require_local(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Update installation is local-only.",
        )


@router.get("/status")
def update_status(request: Request) -> dict:
    return request.app.state.update_service.status()


@router.post("/check")
def update_check(request: Request) -> dict:
    try:
        return request.app.state.update_service.check()
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
        return request.app.state.update_service.start_install(force=payload.force)
    except UpdateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
