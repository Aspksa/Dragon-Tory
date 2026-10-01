from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(include_in_schema=False)
_WEB = Path(__file__).resolve().parents[1] / "web"
_INDEX = _WEB / "index.html"
_CYTOSCAPE = _WEB / "vendor" / "cytoscape.min.js"


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"))


@router.get("/assets/cytoscape.min.js")
def cytoscape_asset() -> FileResponse:
    return FileResponse(
        _CYTOSCAPE,
        media_type="application/javascript; charset=utf-8",
    )
