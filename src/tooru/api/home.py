from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)
_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"))
