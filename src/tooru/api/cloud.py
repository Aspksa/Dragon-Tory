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


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: str | None = Field(default=None, max_length=128)


class FolderRename(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DocumentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    folder_id: str | None = Field(default=None, max_length=128)
    move_to_root: bool = False
    favorite: bool | None = None
    description: str | None = Field(default=None, max_length=5_000)
    tags: list[str] | None = Field(default=None, max_length=50)


def _safe_filename(value: str) -> str:
    decoded = unquote(value).replace("\\", "/")
    name = Path(decoded).name.strip().strip(".")
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не указано имя файла.",
        )
    return name[:255]


def _folder_value(value: str | None) -> str | None:
    if not value or value == "root":
        return None
    return value


async def _receive_file(
    request: Request,
    *,
    max_bytes: int,
) -> tuple[Path, int, str]:
    store = request.app.state.cloud_store
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
        return temp, size_bytes, digest.hexdigest()
    except Exception:
        temp.unlink(missing_ok=True)
        raise


@router.get("/files")
def list_files(
    request: Request,
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=200, ge=1, le=500),
    folder_id: str = Query(default="root", max_length=128),
    favorites_only: bool = False,
    sort: str = Query(default="updated", max_length=32),
) -> dict:
    store = request.app.state.cloud_store
    folder = _folder_value(folder_id)
    return {
        "items": store.list_documents(
            query=query,
            limit=limit,
            folder_id=folder,
            favorites_only=favorites_only,
            sort=sort,
        ),
        "folders": store.list_folders(parent_id=folder),
        "stats": store.stats(),
        "folder_id": folder,
    }


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    name: str = Query(min_length=1, max_length=512),
    folder_id: str = Query(default="root", max_length=128),
) -> dict:
    store = request.app.state.cloud_store
    safe_name = _safe_filename(name)
    max_bytes = request.app.state.settings.cloud_max_upload_bytes
    content_type = request.headers.get(
        "content-type",
        "application/octet-stream",
    ).split(";", 1)[0]
    temp, size_bytes, sha256 = await _receive_file(
        request,
        max_bytes=max_bytes,
    )
    try:
        return store.register_upload(
            temp,
            name=safe_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            folder_id=_folder_value(folder_id),
        )
    finally:
        temp.unlink(missing_ok=True)


@router.patch("/files/{document_id}")
def update_document(
    document_id: str,
    payload: DocumentUpdate,
    request: Request,
) -> dict:
    try:
        folder: str | None | object = ...
        if payload.move_to_root:
            folder = None
        elif payload.folder_id is not None:
            folder = _folder_value(payload.folder_id)
        return request.app.state.cloud_store.update_document(
            document_id,
            name=payload.name,
            folder_id=folder,
            favorite=payload.favorite,
            description=payload.description,
            tags=payload.tags,
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


@router.get("/trash")
def list_trash(request: Request) -> dict:
    store = request.app.state.cloud_store
    return {
        "items": store.list_trashed(),
        "stats": store.stats(),
    }


@router.post("/folders", status_code=status.HTTP_201_CREATED)
def create_folder(payload: FolderCreate, request: Request) -> dict:
    try:
        return request.app.state.cloud_store.create_folder(
            payload.name,
            parent_id=payload.parent_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.patch("/folders/{folder_id}")
def rename_folder(
    folder_id: str,
    payload: FolderRename,
    request: Request,
) -> dict:
    try:
        return request.app.state.cloud_store.rename_folder(
            folder_id,
            payload.name,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Папка не найдена.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


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


@router.get("/files/{document_id}/versions")
def list_versions(document_id: str, request: Request) -> dict:
    try:
        return {
            "items": request.app.state.cloud_store.list_versions(document_id)
        }
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc


@router.post("/files/{document_id}/versions")
async def add_version(
    document_id: str,
    request: Request,
    name: str = Query(min_length=1, max_length=512),
) -> dict:
    store = request.app.state.cloud_store
    try:
        store.get(document_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc

    safe_name = _safe_filename(name)
    max_bytes = request.app.state.settings.cloud_max_upload_bytes
    content_type = request.headers.get(
        "content-type",
        "application/octet-stream",
    ).split(";", 1)[0]
    temp, size_bytes, sha256 = await _receive_file(
        request,
        max_bytes=max_bytes,
    )
    try:
        return store.add_version(
            document_id,
            temp,
            name=safe_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
    finally:
        temp.unlink(missing_ok=True)


@router.post("/files/{document_id}/versions/{version}/restore")
def restore_version(
    document_id: str,
    version: int,
    request: Request,
) -> dict:
    try:
        return request.app.state.cloud_store.restore_version(
            document_id,
            version,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Версия документа не найдена.",
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Файл выбранной версии отсутствует.",
        ) from exc


@router.get("/files/{document_id}/activity")
def document_activity(document_id: str, request: Request) -> dict:
    try:
        return {
            "items": request.app.state.cloud_store.activity(document_id)
        }
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
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


@router.post("/files/{document_id}/restore")
def restore_file(document_id: str, request: Request) -> dict:
    try:
        return request.app.state.cloud_store.restore(document_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Файл отсутствует в корзине.",
        ) from exc
