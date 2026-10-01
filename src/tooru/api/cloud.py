from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/cloud", tags=["cloud"])


AILevel = Literal["denied", "search", "read", "answer", "memory", "full"]
Confidentiality = Literal[
    "ordinary",
    "personal",
    "confidential",
    "highly_protected",
]
DocumentScope = Literal["personal", "project"]


class PassportUpdate(BaseModel):
    ai_access: AILevel | None = None
    confidentiality: Confidentiality | None = None
    scope: DocumentScope | None = None
    project_id: str | None = Field(default=None, max_length=128)


def _safe_filename(value: str) -> str:
    decoded = unquote(value).replace("\\", "/")
    name = Path(decoded).name.strip().strip(".")
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не указано имя файла.",
        )
    return name[:255]


@router.get("/files")
def list_files(
    request: Request,
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    store = request.app.state.cloud_store
    return {
        "items": store.list_documents(query=query, limit=limit),
        "stats": store.stats(),
    }


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    name: str = Query(min_length=1, max_length=512),
) -> dict:
    store = request.app.state.cloud_store
    max_bytes = request.app.state.settings.cloud_max_upload_bytes
    safe_name = _safe_filename(name)
    content_type = request.headers.get(
        "content-type",
        "application/octet-stream",
    ).split(";", 1)[0]

    temp = store.incoming_dir / f"{uuid4().hex}.upload"
    size_bytes = 0
    digest = hashlib.sha256()

    try:
        with temp.open("wb") as target:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "Файл слишком большой. Максимальный размер: "
                            f"{max_bytes // (1024 * 1024)} МБ."
                        ),
                    )
                digest.update(chunk)
                target.write(chunk)

        return store.register_upload(
            temp,
            name=safe_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )
    finally:
        temp.unlink(missing_ok=True)


@router.get("/files/{document_id}/passport")
def get_passport(document_id: str, request: Request) -> dict:
    try:
        return request.app.state.cloud_store.get(document_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc


@router.patch("/files/{document_id}/passport")
def update_passport(
    document_id: str,
    payload: PassportUpdate,
    request: Request,
) -> dict:
    try:
        return request.app.state.cloud_store.update_passport(
            document_id,
            ai_access=payload.ai_access,
            confidentiality=payload.confidentiality,
            scope=payload.scope,
            project_id=payload.project_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/files/{document_id}/verify")
def verify_file(document_id: str, request: Request) -> dict:
    try:
        return request.app.state.cloud_store.verify_integrity(document_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл документа не найден.",
        ) from exc


@router.get("/files/{document_id}/content")
def download_file(document_id: str, request: Request) -> FileResponse:
    store = request.app.state.cloud_store
    try:
        item = store.get(document_id)
        path = store.content_path(document_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл документа не найден.",
        ) from exc

    return FileResponse(
        path,
        media_type=item["content_type"],
        filename=item["name"],
    )


@router.delete("/files/{document_id}")
def trash_file(document_id: str, request: Request) -> dict:
    try:
        request.app.state.cloud_store.trash(document_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc
    return {"ok": True, "document_id": document_id}
