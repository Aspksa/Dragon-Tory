from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from tooru.ai.base import AIRequest
from tooru.ai.prompt_guard import UNTRUSTED_CONTENT_POLICY, wrap_untrusted_text
from tooru.cloud.document_intelligence import OCRUnavailableError
from tooru.cloud.intelligence import (
    LEGACY_CONVERTIBLE_SUFFIXES,
    SUPPORTED_NATIVE_SUFFIXES,
    SUPPORTED_OCR_SUFFIXES,
    UnsupportedDocumentError,
)
from tooru.cloud.module_learning import ModuleLearningService

router = APIRouter(
    prefix="/v1/cloud/intelligence",
    tags=["cloud-intelligence"],
)


class ApplySuggestionsRequest(BaseModel):
    apply_tags: bool = True
    apply_kind_to_dna: bool = True


class VersionCompareRequest(BaseModel):
    first_version: int
    second_version: int
    question: str = (
        "Сравни версии документа по смыслу. Выдели изменения сумм, дат, "
        "обязательств, сроков и других существенных условий."
    )


class ModuleDraftRequest(BaseModel):
    task: str = Field(min_length=3, max_length=8_000)


def _service(request: Request):
    return request.app.state.document_intelligence


def _smart(request: Request):
    return request.app.state.cloud_smart


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ, версия или анализ не найден.",
        )
    if isinstance(exc, PermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    if isinstance(exc, OCRUnavailableError):
        return HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=str(exc),
        )
    if isinstance(exc, UnsupportedDocumentError):
        return HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )
    if isinstance(exc, FileNotFoundError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    )


@router.get("/status")
def intelligence_status(request: Request) -> dict[str, Any]:
    return {
        "ocr": _service(request).ocr_status(),
        "converter": _service(request).converter_status(),
        "analysis": {
            "local_first": True,
            "external_ai_required": False,
            "stores_full_raw_text": False,
        },
        "supported_native": sorted(
            suffix.removeprefix(".").upper()
            for suffix in SUPPORTED_NATIVE_SUFFIXES
        ),
        "supported_ocr": sorted(
            suffix.removeprefix(".").upper()
            for suffix in SUPPORTED_OCR_SUFFIXES
        ),
        "supported_via_converter": sorted(
            suffix.removeprefix(".").upper()
            for suffix in LEGACY_CONVERTIBLE_SUFFIXES
        ),
    }


@router.post("/files/{document_id}/analyze")
def analyze_document(document_id: str, request: Request) -> dict[str, Any]:
    try:
        if not _smart(request).permission(document_id, "content_read"):
            raise PermissionError(
                "ИИ-договор не разрешает локальный анализ содержимого."
            )
        result = _service(request).analyze(document_id)
        automation = _smart(request).apply_intelligence_defaults(
            document_id,
            result,
        )
        result["automation"] = automation
        if str(result.get("kind") or "").casefold() == "служебная записка":
            result["memo_card"] = request.app.state.memo_organizer.process(
                document_id
            )
        _smart(request).record_provenance(
            document_id,
            "document_intelligence_analyzed",
            actor="tooru-local",
            details={
                "version": result["version"],
                "kind": result["kind"],
                "ocr_used": result["ocr_used"],
                "extraction_method": result["extraction_method"],
                "external_ai_used": False,
            },
        )
        return result
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/analyze-pending")
def analyze_pending(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    service = _service(request)
    smart = _smart(request)
    pending = service.collection_items(
        "attention:unanalyzed",
        limit=limit,
    )
    analyzed: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for document in pending:
        document_id = document["id"]
        try:
            if not smart.permission(document_id, "content_read"):
                skipped.append(
                    {
                        "document_id": document_id,
                        "reason": "ИИ-договор запрещает чтение.",
                    }
                )
                continue
            result = service.analyze(document_id)
            automation = smart.apply_intelligence_defaults(
                document_id,
                result,
            )
            memo_card = None
            if str(result.get("kind") or "").casefold() == "служебная записка":
                memo_card = request.app.state.memo_organizer.process(document_id)
            analyzed.append(
                {
                    "document_id": document_id,
                    "name": document["name"],
                    "kind": result["kind"],
                    "ocr_used": result["ocr_used"],
                    "automation": automation,
                    "memo_card": memo_card,
                }
            )
            smart.record_provenance(
                document_id,
                "document_intelligence_analyzed",
                actor="tooru-local",
                details={
                    "version": result["version"],
                    "kind": result["kind"],
                    "ocr_used": result["ocr_used"],
                    "external_ai_used": False,
                },
            )
        except (
            KeyError,
            PermissionError,
            UnsupportedDocumentError,
            FileNotFoundError,
            ValueError,
            RuntimeError,
            OSError,
        ) as exc:
            skipped.append(
                {
                    "document_id": document_id,
                    "reason": str(exc),
                }
            )
    return {
        "analyzed": analyzed,
        "skipped": skipped,
        "requested_limit": limit,
    }


@router.get("/files/{document_id}/memo-card")
def get_memo_card(document_id: str, request: Request) -> dict[str, Any]:
    try:
        return request.app.state.memo_organizer.get(document_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/files/{document_id}/memo-process")
async def process_memo(
    document_id: str,
    request: Request,
) -> dict[str, Any]:
    try:
        if not _smart(request).permission(document_id, "content_read"):
            raise PermissionError(
                "ИИ-договор не разрешает Тоору читать содержимое записки."
            )
        try:
            analysis = _service(request).get(document_id)
        except KeyError:
            analysis = _service(request).analyze(document_id)
            _smart(request).apply_intelligence_defaults(document_id, analysis)
        if str(analysis.get("kind") or "").casefold() != "служебная записка":
            dna = _smart(request).get_dna(document_id)
            if str(dna.get("kind") or "").casefold() != "служебная записка":
                raise ValueError(
                    "Это правило применяется только к служебным запискам."
                )

        card = request.app.state.memo_organizer.process(document_id)
        learning = ModuleLearningService(
            memory_intake=request.app.state.memory_intake,
            smart=request.app.state.cloud_smart,
            intelligence=request.app.state.document_intelligence,
            ai_router=request.app.state.ai_router,
        )
        ai_study: dict[str, Any] | None = None
        if card.get("duplicate_of"):
            ai_study = {
                "memory_id": None,
                "reason": "Полная копия: повторное AI-запоминание не выполняется.",
                "external_ai_used": False,
            }
        elif card.get("is_template"):
            ai_study = {
                "memory_id": None,
                "reason": "Шаблон хранится отдельно и не создаёт факты проекта.",
                "external_ai_used": False,
            }
        else:
            try:
                ai_study = await learning.study_document("memos", document_id)
            except Exception as exc:  # noqa: BLE001 - local memo processing must survive AI
                ai_study = {
                    "memory_id": None,
                    "reason": f"{type(exc).__name__}: {str(exc)[:500]}",
                    "external_ai_used": False,
                }
        return {
            "ok": True,
            "document_id": document_id,
            "card": card,
            "ai_study": ai_study,
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/files/{document_id}")
def get_analysis(
    document_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    try:
        return _service(request).get(
            document_id,
            version=version,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/files/{document_id}/apply-suggestions")
def apply_suggestions(
    document_id: str,
    payload: ApplySuggestionsRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        service = _service(request)
        result = service.apply_suggestions(
            document_id,
            apply_tags=payload.apply_tags,
            apply_kind_to_dna=payload.apply_kind_to_dna,
        )
        if payload.apply_kind_to_dna:
            _smart(request).update_dna(
                document_id,
                {"kind": result["kind"]},
            )
        _smart(request).record_provenance(
            document_id,
            "intelligence_suggestions_applied",
            actor="user",
            details={
                "apply_tags": payload.apply_tags,
                "apply_kind_to_dna": payload.apply_kind_to_dna,
            },
        )
        return {
            "ok": True,
            "document_id": document_id,
            **result,
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/modules")
def document_modules(request: Request) -> dict[str, Any]:
    return {"items": _service(request).modules_overview()}


@router.get("/modules/{module_id}")
def document_module(module_id: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).module_profile(module_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/modules/{module_id}/study")
async def study_module(
    module_id: str,
    request: Request,
) -> dict[str, Any]:
    service = ModuleLearningService(
        memory_intake=request.app.state.memory_intake,
        smart=request.app.state.cloud_smart,
        intelligence=request.app.state.document_intelligence,
        ai_router=request.app.state.ai_router,
    )
    try:
        return await service.study(module_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/modules/{module_id}/draft")
async def draft_from_module(
    module_id: str,
    payload: ModuleDraftRequest,
    request: Request,
) -> dict[str, Any]:
    if module_id not in {"orders", "directives"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Создание проекта доступно только для приказов и распоряжений.",
        )
    if not request.app.state.ai_router.has_provider("deepseek"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DeepSeek не настроен.",
        )

    service = _service(request)
    smart = _smart(request)
    try:
        profile = service.module_profile(module_id)
        references: list[dict[str, Any]] = []
        source_parts: list[str] = []
        for item in profile["items"]:
            if len(references) >= 6:
                break
            contract = smart.get_contract(item["id"])
            if contract["expired"]:
                continue
            if not (
                contract["content_read"]
                and contract["answer"]
                and contract["external_ai"]
            ):
                continue
            try:
                source = service.version_text(
                    item["id"],
                    int(item["version"]),
                )
            except (
                KeyError,
                FileNotFoundError,
                UnsupportedDocumentError,
                OCRUnavailableError,
                ValueError,
            ):
                continue
            text = source["text"].strip()[:12_000]
            if not text:
                continue
            source_no = len(references) + 1
            references.append(
                {
                    "source_no": source_no,
                    "document_id": item["id"],
                    "name": item["name"],
                    "version": item["version"],
                    "sha256": source["sha256"],
                }
            )
            source_parts.append(
                f"[Образец {source_no}: {item['name']} · "
                f"v{item['version']}]\n"
                + wrap_untrusted_text(
                    text,
                    source=f"template:{item['id']}:v{item['version']}",
                )
            )

        if not references:
            raise PermissionError(
                "Нет образцов с разрешениями content_read + answer + "
                "external_ai. Разрешите их только тем приказам/распоряжениям, "
                "которые можно использовать как эталоны."
            )

        title = "приказа" if module_id == "orders" else "распоряжения"
        response = await request.app.state.ai_router.generate(
            "deepseek",
            AIRequest(
                system_prompt=(
                    f"Ты Дракончик Тоору. Подготовь проект {title} предприятия. "
                    "Используй переданные документы только как эталоны структуры, "
                    "формулировок и оформления. Не переноси из образцов имена, "
                    "даты, номера, суммы или факты, если пользователь их не дал. "
                    "Не придумывай обязательные реквизиты: оставляй понятные "
                    "плейсхолдеры в квадратных скобках. Сохраняй деловой стиль. "
                    "В конце перечисли, какие поля нужно проверить человеку. "
                    + UNTRUSTED_CONTENT_POLICY
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "\n\n".join(source_parts)
                            + "\n\nЗадача для нового документа:\n"
                            + payload.task
                        ),
                    }
                ],
                max_tokens=2_800,
            ),
            module=module_id,
            operation="administrative_draft",
            source_type="module",
            source_id=module_id,
        )
        for reference in references:
            smart.record_provenance(
                reference["document_id"],
                "module_draft_reference_used",
                actor="tooru",
                details={
                    "module_id": module_id,
                    "version": reference["version"],
                    "memory_written": False,
                    "training_performed": False,
                },
            )

        return {
            "module_id": module_id,
            "document_type": title,
            "draft": response.text,
            "references": references,
            "provider": response.provider,
            "model": response.model,
            "memory_written": False,
            "training_performed": False,
            "reference_based_generation": True,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/collections")
def smart_collections(request: Request) -> dict[str, Any]:
    return {"items": _service(request).smart_collections()}


@router.get("/collections/{collection_id}/files")
def smart_collection_files(
    collection_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    try:
        return {
            "collection_id": collection_id,
            "items": _service(request).collection_items(
                collection_id,
                limit=limit,
            ),
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/deadlines")
def document_deadlines(
    request: Request,
    limit: int = Query(default=300, ge=1, le=1_000),
) -> dict[str, Any]:
    return {"items": _service(request).deadlines(limit=limit)}


@router.get("/search")
def smart_search(
    request: Request,
    query: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=100, ge=1, le=300),
) -> dict[str, Any]:
    return {
        "query": query,
        "items": _service(request).smart_search(
            query,
            limit=limit,
        ),
    }


@router.get("/files/{document_id}/versions/diff")
def local_version_diff(
    document_id: str,
    request: Request,
    first_version: int = Query(ge=1),
    second_version: int = Query(ge=1),
) -> dict[str, Any]:
    try:
        if not _smart(request).permission(document_id, "content_read"):
            raise PermissionError(
                "ИИ-договор не разрешает читать версии документа."
            )
        return _service(request).local_version_diff(
            document_id,
            first_version,
            second_version,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/files/{document_id}/versions/semantic-compare")
async def semantic_version_compare(
    document_id: str,
    payload: VersionCompareRequest,
    request: Request,
) -> dict[str, Any]:
    smart = _smart(request)
    try:
        contract = smart.get_contract(document_id)
        if contract["expired"]:
            raise PermissionError("Срок ИИ-договора истёк.")
        if not (
            contract["content_read"]
            and contract["compare"]
            and contract["external_ai"]
        ):
            raise PermissionError(
                "ИИ-договор не разрешает смысловое сравнение через DeepSeek."
            )
        if not request.app.state.ai_router.has_provider("deepseek"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DeepSeek не настроен.",
            )

        service = _service(request)
        first = service.version_text(
            document_id,
            payload.first_version,
        )
        second = service.version_text(
            document_id,
            payload.second_version,
        )
        local_diff = service.local_version_diff(
            document_id,
            payload.first_version,
            payload.second_version,
        )

        first_text = first["text"][:28_000]
        second_text = second["text"][:28_000]
        response = await request.app.state.ai_router.generate(
            "deepseek",
            AIRequest(
                system_prompt=(
                    "Ты Дракончик Тоору. Сравни две версии одного документа. "
                    "Не придумывай отсутствующие факты. Отдельно перечисли "
                    "изменения дат, сумм, обязательств, сроков, рисков и "
                    "добавленных/удалённых существенных условий. "
                    "Для выводов указывай [Версия A] или [Версия B]. "
                    + UNTRUSTED_CONTENT_POLICY
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Версия A: v{first['version']} "
                            f"SHA-256 {first['sha256']}\n"
                            + wrap_untrusted_text(
                                first_text,
                                source=(
                                    f"document:{document_id}:"
                                    f"v{first['version']}"
                                ),
                            )
                            + "\n\n"
                            + f"Версия B: v{second['version']} "
                            f"SHA-256 {second['sha256']}\n"
                            + wrap_untrusted_text(
                                second_text,
                                source=(
                                    f"document:{document_id}:"
                                    f"v{second['version']}"
                                ),
                            )
                            + "\n\n"
                            "Локально найденные структурные отличия:\n"
                            + str(local_diff)
                            + "\n\nЗадача: "
                            + payload.question
                        ),
                    }
                ],
                max_tokens=2_400,
            ),
            module="drive",
            operation="document_version_compare",
            source_type="document",
            source_id=document_id,
            document_id=document_id,
        )
        smart.record_provenance(
            document_id,
            "semantic_version_compare",
            actor="tooru",
            details={
                "first_version": payload.first_version,
                "second_version": payload.second_version,
                "provider": response.provider,
                "sha256_a": first["sha256"],
                "sha256_b": second["sha256"],
                "memory_written": False,
            },
        )
        smart.consume_one_time_answer(document_id)
        return {
            "answer": response.text,
            "document_id": document_id,
            "version_a": payload.first_version,
            "version_b": payload.second_version,
            "sha256_a": first["sha256"],
            "sha256_b": second["sha256"],
            "local_diff": local_diff,
            "provider": response.provider,
            "model": response.model,
            "memory_written": False,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc
