from fastapi import APIRouter

from tooru.core.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "name": settings.app_name,
        "version": settings.version,
    }
