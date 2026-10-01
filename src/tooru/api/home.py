from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(include_in_schema=False)
_WEB = Path(__file__).resolve().parents[1] / "web"
_INDEX = _WEB / "index.html"
_STYLES = _WEB / "styles.css"
_APP_JS = _WEB / "app.js"
_CYTOSCAPE = _WEB / "vendor" / "cytoscape.min.js"


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"))


@router.get("/assets/styles.css")
def styles_asset() -> FileResponse:
    return FileResponse(
        _STYLES,
        media_type="text/css; charset=utf-8",
    )


@router.get("/assets/app.js")
def app_asset() -> FileResponse:
    return FileResponse(
        _APP_JS,
        media_type="application/javascript; charset=utf-8",
    )


@router.get("/assets/cytoscape.min.js")
def cytoscape_asset() -> FileResponse:
    return FileResponse(
        _CYTOSCAPE,
        media_type="application/javascript; charset=utf-8",
    )
