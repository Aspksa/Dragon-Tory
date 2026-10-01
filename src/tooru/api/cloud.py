from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from tooru.ai.base import AIRequest
from tooru.cloud.intelligence import (
    UnsupportedDocumentError,
    extract_document,
    preview_document,
)

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


class AskDocumentRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4_000)


class VaultPassphrase(BaseModel):
    passphrase: str = Field(min_length=12, max_length=1_024)


class DocumentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    folder_id: str | None = Field(default=None, max_length=128)
    move_to_root: bool = False
    favorite: bool | None = None
    description: str | None = Field(default=None, max_length=5_000)
    tags: list[str] | None = Field(default=None, max_length=50)


def _require_local(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Сейф Тори можно разблокировать только локально.",
        )


def _cleanup_temp(path: Path) -> None:
    path.unlink(missing_ok=True)


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


@router.get("/vault/status")
def vault_status(request: Request) -> dict:
    return request.app.state.cloud_vault.status()


@router.post("/vault/setup")
def vault_setup(payload: VaultPassphrase, request: Request) -> dict:
    _require_local(request)
    try:
        return request.app.state.cloud_vault.setup(payload.passphrase)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/vault/unlock")
def vault_unlock(payload: VaultPassphrase, request: Request) -> dict:
    _require_local(request)
    try:
        return request.app.state.cloud_vault.unlock(payload.passphrase)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post("/vault/lock")
def vault_lock(request: Request) -> dict:
    _require_local(request)
    return request.app.state.cloud_vault.lock()


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
        result = store.register_upload(
            temp,
            name=safe_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            folder_id=_folder_value(folder_id),
        )
        request.app.state.cloud_smart.ensure_document(result["id"])
        request.app.state.cloud_smart.record_provenance(
            result["id"],
            "uploaded",
            actor="user",
            details={"name": result["name"], "version": result["version"]},
        )
        return result
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
        result = request.app.state.cloud_store.update_document(
            document_id,
            name=payload.name,
            folder_id=folder,
            favorite=payload.favorite,
            description=payload.description,
            tags=payload.tags,
        )
        request.app.state.cloud_smart.record_provenance(
            document_id,
            "document_metadata_updated",
            actor="user",
            details={"name": result["name"], "folder_id": result["folder_id"]},
        )
        return result
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


@router.get("/search")
def search_document_content(
    request: Request,
    query: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    smart = request.app.state.cloud_smart
    items = request.app.state.cloud_store.search_chunks(
        query,
        limit=limit * 3,
    )
    allowed = [
        item
        for item in items
        if smart.permission(item["document_id"], "content_read")
    ][:limit]
    return {"items": allowed}


@router.get("/files/{document_id}/preview")
def preview_file(document_id: str, request: Request) -> dict:
    store = request.app.state.cloud_store
    try:
        item = store.get(document_id)
        path, cleanup = store.materialize_plaintext(document_id)
        try:
            preview = preview_document(
                path,
                name=item["name"],
                content_type=item["content_type"],
            )
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)
        return {
            "document_id": document_id,
            "name": item["name"],
            "version": item["version"],
            **preview,
        }
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc
    except UnsupportedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc


@router.post("/files/{document_id}/index")
def index_file(document_id: str, request: Request) -> dict:
    store = request.app.state.cloud_store
    try:
        item = store.get(document_id)
        if not request.app.state.cloud_smart.permission(
            document_id,
            "content_read",
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "ИИ-договор не разрешает Тоору читать содержимое "
                    "этого документа."
                ),
            )
        path, cleanup = store.materialize_plaintext(document_id)
        try:
            extracted = extract_document(
                path,
                name=item["name"],
                content_type=item["content_type"],
            )
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)
        chunks = [
            {
                "label": chunk.label,
                "page": chunk.page,
                "text": chunk.text,
            }
            for chunk in extracted
            if chunk.text.strip()
        ]
        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Из документа не удалось извлечь текст. "
                    "Для сканов позже потребуется OCR."
                ),
            )
        updated = store.replace_chunks(document_id, chunks)
        return {
            "ok": True,
            "document_id": document_id,
            "version": updated["version"],
            "chunk_count": len(chunks),
            "index_status": updated["ai_index_status"],
        }
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc
    except UnsupportedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        ) from exc


@router.post("/files/{document_id}/ask")
async def ask_document(
    document_id: str,
    payload: AskDocumentRequest,
    request: Request,
) -> dict:
    store = request.app.state.cloud_store
    try:
        item = store.get(document_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc

    smart = request.app.state.cloud_smart
    contract = smart.get_contract(document_id)
    if contract["expired"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Срок ИИ-договора этого документа истёк.",
        )
    if not (
        contract["content_read"]
        and contract["answer"]
        and contract["external_ai"]
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "ИИ-договор не разрешает передавать фрагменты документа "
                "во внешний ИИ для ответа."
            ),
        )
    if (
        item["ai_index_status"] != "ready"
        or item["indexed_version"] != item["version"]
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Сначала нажмите «Изучить документ», чтобы "
                "проиндексировать текущую версию локально."
            ),
        )
    if not request.app.state.ai_router.has_provider("deepseek"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DeepSeek не настроен.",
        )

    chunks = store.document_chunks(
        document_id,
        query=payload.question,
        limit=8,
    )
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="В индексе документа нет текста для ответа.",
        )

    sources: list[dict] = []
    context_parts: list[str] = []
    for chunk in chunks:
        source = {
            "label": chunk["label"],
            "page": chunk["page_no"],
            "chunk_no": chunk["chunk_no"],
        }
        sources.append(source)
        context_parts.append(
            f"[Источник {chunk['chunk_no']}: {chunk['label']}]\n"
            f"{chunk['text']}"
        )

    response = await request.app.state.ai_router.generate(
        "deepseek",
        AIRequest(
            system_prompt=(
                "Ты Дракончик Тоору. Отвечай только по переданным "
                "фрагментам документа. Не придумывай отсутствующие факты. "
                "Если данных недостаточно, прямо скажи об этом. "
                "Ссылайся на источники в виде [Источник N]."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Документ: {item['name']}\n"
                        f"Версия: {item['version']}\n\n"
                        + "\n\n".join(context_parts)
                        + "\n\nВопрос: "
                        + payload.question
                    ),
                }
            ],
            max_tokens=1_800,
        ),
    )
    smart.record_provenance(
        document_id,
        "ai_answer_generated",
        actor="tooru",
        details={
            "version": item["version"],
            "source_count": len(sources),
            "provider": response.provider,
            "memory_written": False,
        },
    )
    smart.consume_one_time_answer(document_id)
    return {
        "answer": response.text,
        "document_id": document_id,
        "version": item["version"],
        "provider": response.provider,
        "model": response.model,
        "sources": sources,
        "proof": {
            "document_id": document_id,
            "version": item["version"],
            "sha256": item["sha256"],
            "source_count": len(sources),
            "memory_written": False,
        },
    }


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
        result = request.app.state.cloud_store.update_passport(
            document_id,
            ai_access=payload.ai_access,
            confidentiality=payload.confidentiality,
            scope=payload.scope,
            project_id=payload.project_id,
        )
        request.app.state.cloud_smart.reconcile_contract(document_id)
        request.app.state.cloud_smart.emit_event(
            document_id,
            "passport_changed",
            actor="user",
            details={
                "confidentiality": result["confidentiality"],
                "ai_access": result["ai_access"],
                "scope": result["scope"],
            },
        )
        return result
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
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
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
        result = store.add_version(
            document_id,
            temp,
            name=safe_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        request.app.state.cloud_smart.emit_event(
            document_id,
            "version_changed",
            actor="user",
            details={"version": result["version"], "name": result["name"]},
        )
        return result
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        ) from exc
    finally:
        temp.unlink(missing_ok=True)


@router.post("/files/{document_id}/versions/{version}/restore")
def restore_version(
    document_id: str,
    version: int,
    request: Request,
) -> dict:
    try:
        result = request.app.state.cloud_store.restore_version(
            document_id,
            version,
        )
        request.app.state.cloud_smart.emit_event(
            document_id,
            "version_changed",
            actor="user",
            details={
                "version": result["version"],
                "restored_from_version": version,
            },
        )
        return result
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
        result = request.app.state.cloud_store.verify_integrity(document_id)
        if not result["ok"]:
            request.app.state.cloud_smart.emit_event(
                document_id,
                "integrity_failed",
                details={
                    "expected_sha256": result["expected_sha256"],
                    "actual_sha256": result["actual_sha256"],
                },
            )
        else:
            request.app.state.cloud_smart.record_provenance(
                document_id,
                "integrity_verified",
                details={"ok": True},
            )
        return result
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        ) from exc
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
        path, cleanup = store.materialize_plaintext(document_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        ) from exc
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл документа не найден.",
        ) from exc
    background = (
        BackgroundTask(_cleanup_temp, cleanup)
        if cleanup is not None
        else None
    )
    return FileResponse(
        path,
        media_type=item["content_type"],
        filename=item["name"],
        background=background,
    )


@router.get("/files/{document_id}/open")
def open_file_inline(document_id: str, request: Request) -> FileResponse:
    store = request.app.state.cloud_store
    try:
        item = store.get(document_id)
        path, cleanup = store.materialize_plaintext(document_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        ) from exc
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл документа не найден.",
        ) from exc

    background = (
        BackgroundTask(_cleanup_temp, cleanup)
        if cleanup is not None
        else None
    )
    return FileResponse(
        path,
        media_type=item["content_type"],
        filename=item["name"],
        content_disposition_type="inline",
        background=background,
    )


@router.delete("/files/{document_id}")
def trash_file(document_id: str, request: Request) -> dict:
    try:
        request.app.state.cloud_store.trash(document_id)
        request.app.state.cloud_smart.record_provenance(
            document_id,
            "trashed",
            actor="user",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ не найден.",
        ) from exc
    return {"ok": True, "document_id": document_id}


@router.post("/files/{document_id}/restore")
def restore_file(document_id: str, request: Request) -> dict:
    try:
        result = request.app.state.cloud_store.restore(document_id)
        request.app.state.cloud_smart.record_provenance(
            document_id,
            "restored_from_trash",
            actor="user",
        )
        return result
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
