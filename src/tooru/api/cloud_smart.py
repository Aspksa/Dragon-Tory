from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from tooru.ai.base import AIRequest
from tooru.cloud.intelligence import (
    UnsupportedDocumentError,
    extract_document,
)

router = APIRouter(prefix="/v1/cloud/smart", tags=["cloud-smart"])

RelationType = Literal[
    "related",
    "derived_from",
    "replaces",
    "supports",
    "attachment",
    "same_subject",
    "reference",
]
WatchEvent = Literal[
    "version_changed",
    "integrity_failed",
    "passport_changed",
    "relation_added",
    "seal_failed",
]


class DNAUpdate(BaseModel):
    kind: str | None = Field(default=None, max_length=120)
    origin: str | None = Field(default=None, max_length=500)
    external_ref: str | None = Field(default=None, max_length=1_000)
    important_date: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=5_000)
    counterparty: str | None = Field(default=None, max_length=500)
    document_number: str | None = Field(default=None, max_length=200)
    document_date: str | None = Field(default=None, max_length=80)
    amount_value: float | None = None
    amount_currency: str | None = Field(default=None, max_length=20)
    terms_summary: str | None = Field(default=None, max_length=5_000)
    counterparty_id: str | None = Field(default=None, max_length=128)
    document_subtype: str | None = Field(default=None, max_length=200)
    employee_name: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=300)
    work_date: str | None = Field(default=None, max_length=80)
    work_hours: float | None = Field(default=None, ge=0, le=24)
    work_reason: str | None = Field(default=None, max_length=2_000)


class CounterpartyUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    short_name: str = Field(default="", max_length=300)
    inn: str = Field(default="", max_length=32)
    kpp: str = Field(default="", max_length=32)
    ogrn: str = Field(default="", max_length=32)
    legal_address: str = Field(default="", max_length=1_000)
    postal_address: str = Field(default="", max_length=1_000)
    bank_name: str = Field(default="", max_length=500)
    bik: str = Field(default="", max_length=32)
    settlement_account: str = Field(default="", max_length=64)
    correspondent_account: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=120)
    contact_person: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=5_000)


class EmployeeUpsert(BaseModel):
    full_name: str = Field(min_length=1, max_length=300)
    personnel_number: str = Field(default="", max_length=80)
    position: str = Field(default="", max_length=300)
    department: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=300)
    driver_license: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=5_000)
    active: bool = True


class VehicleUpsert(BaseModel):
    garage_number: str = Field(default="", max_length=100)
    plate_number: str = Field(default="", max_length=100)
    vin: str = Field(default="", max_length=64)
    make_model: str = Field(default="", max_length=300)
    driver_employee_id: str | None = Field(default=None, max_length=128)
    notes: str = Field(default="", max_length=5_000)
    active: bool = True


class AIContractUpdate(BaseModel):
    metadata_search: bool | None = None
    content_read: bool | None = None
    answer: bool | None = None
    compare: bool | None = None
    memory: bool | None = None
    propose_edits: bool | None = None
    external_ai: bool | None = None
    clean_room: bool | None = None
    one_time_answer: bool | None = None
    expires_at: str | None = Field(default=None, max_length=80)


class RelationCreate(BaseModel):
    target_id: str = Field(min_length=1, max_length=128)
    relation_type: RelationType = "related"
    note: str = Field(default="", max_length=1_000)


class WatchCreate(BaseModel):
    event_type: WatchEvent
    config: dict[str, Any] = Field(default_factory=dict)


class SnapshotCreate(BaseModel):
    label: str = Field(default="Снимок диска", max_length=255)


class SmartAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4_000)


class CompareRequest(BaseModel):
    other_document_id: str = Field(min_length=1, max_length=128)
    question: str = Field(
        default="Сравни документы и перечисли существенные различия.",
        min_length=2,
        max_length=4_000,
    )


def _smart(request: Request):
    return request.app.state.cloud_smart


def _cloud(request: Request):
    return request.app.state.cloud_store


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Документ или объект не найден.",
        )
    if isinstance(exc, PermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    if isinstance(exc, UnsupportedDocumentError):
        return HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    )


def _rank_chunks(chunks, question: str, *, limit: int = 8) -> list:
    terms = {
        term.lower().strip(".,:;!?()[]{}")
        for term in question.replace("\n", " ").split(" ")
        if len(term.strip()) >= 2
    }
    scored = []
    for index, chunk in enumerate(chunks):
        haystack = chunk.text.lower()
        score = sum(haystack.count(term) for term in terms)
        scored.append((score, -index, chunk))
    scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
    selected = [item[2] for item in scored[:limit] if item[2].text.strip()]
    return selected


def _ephemeral_chunks(
    document_id: str,
    question: str,
    request: Request,
    *,
    limit: int = 8,
):
    cloud = _cloud(request)
    item = cloud.get(document_id)
    path, cleanup = cloud.materialize_plaintext(document_id)
    try:
        chunks = extract_document(
            path,
            name=item["name"],
            content_type=item["content_type"],
        )
    finally:
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)
    return item, _rank_chunks(chunks, question, limit=limit)


@router.get("/employees")
def list_employees(
    request: Request,
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=500, ge=1, le=1_000),
) -> dict[str, Any]:
    return {
        "items": _smart(request).list_employees(
            query=query,
            limit=limit,
        )
    }


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeUpsert,
    request: Request,
) -> dict[str, Any]:
    try:
        return _smart(request).create_employee(payload.model_dump())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/employees/{employee_id}")
def update_employee(
    employee_id: str,
    payload: EmployeeUpsert,
    request: Request,
) -> dict[str, Any]:
    try:
        return _smart(request).update_employee(
            employee_id,
            payload.model_dump(),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/garage")
def list_garage(
    request: Request,
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=500, ge=1, le=1_000),
) -> dict[str, Any]:
    return {
        "items": _smart(request).list_vehicles(
            query=query,
            limit=limit,
        )
    }


@router.post("/garage", status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleUpsert,
    request: Request,
) -> dict[str, Any]:
    try:
        return _smart(request).create_vehicle(payload.model_dump())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/garage/{vehicle_id}")
def update_vehicle(
    vehicle_id: str,
    payload: VehicleUpsert,
    request: Request,
) -> dict[str, Any]:
    try:
        return _smart(request).update_vehicle(
            vehicle_id,
            payload.model_dump(),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/counterparties")
def list_counterparties(
    request: Request,
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=300, ge=1, le=1_000),
) -> dict[str, Any]:
    return {
        "items": _smart(request).list_counterparties(
            query=query,
            limit=limit,
        )
    }


@router.post(
    "/counterparties",
    status_code=status.HTTP_201_CREATED,
)
def create_counterparty(
    payload: CounterpartyUpsert,
    request: Request,
) -> dict[str, Any]:
    try:
        return _smart(request).create_counterparty(payload.model_dump())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/counterparties/{counterparty_id}")
def get_counterparty(
    counterparty_id: str,
    request: Request,
) -> dict[str, Any]:
    try:
        return _smart(request).get_counterparty(counterparty_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/counterparties/{counterparty_id}")
def update_counterparty(
    counterparty_id: str,
    payload: CounterpartyUpsert,
    request: Request,
) -> dict[str, Any]:
    try:
        return _smart(request).update_counterparty(
            counterparty_id,
            payload.model_dump(),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/timesheet/weekend-work")
def weekend_work_timesheet(
    request: Request,
    year: int | None = Query(default=None, ge=2000, le=2200),
    month: int | None = Query(default=None, ge=1, le=12),
) -> dict[str, Any]:
    return _smart(request).weekend_timesheet(
        year=year,
        month=month,
    )


@router.get("/files/{document_id}/dna")
def get_dna(document_id: str, request: Request) -> dict:
    try:
        return _smart(request).get_dna(document_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/files/{document_id}/dna")
def update_dna(
    document_id: str,
    payload: DNAUpdate,
    request: Request,
) -> dict:
    try:
        return _smart(request).update_dna(
            document_id,
            payload.model_dump(exclude_unset=True),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/files/{document_id}/ai-contract")
def get_ai_contract(document_id: str, request: Request) -> dict:
    try:
        return _smart(request).get_contract(document_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/files/{document_id}/ai-contract")
def update_ai_contract(
    document_id: str,
    payload: AIContractUpdate,
    request: Request,
) -> dict:
    try:
        return _smart(request).update_contract(
            document_id,
            payload.model_dump(exclude_unset=True),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/files/{document_id}/relations")
def list_relations(document_id: str, request: Request) -> dict:
    try:
        smart = _smart(request)
        return {
            "items": smart.list_relations(document_id),
            "suggestions": smart.suggest_relations(document_id),
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/files/{document_id}/relations",
    status_code=status.HTTP_201_CREATED,
)
def add_relation(
    document_id: str,
    payload: RelationCreate,
    request: Request,
) -> dict:
    try:
        return _smart(request).add_relation(
            document_id,
            payload.target_id,
            payload.relation_type,
            payload.note,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/relations/{relation_id}")
def delete_relation(relation_id: str, request: Request) -> dict:
    if not _smart(request).delete_relation(relation_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Связь не найдена.",
        )
    return {"ok": True, "relation_id": relation_id}


@router.get("/graph")
def knowledge_graph(
    request: Request,
    limit: int = Query(default=300, ge=1, le=1_000),
) -> dict:
    return _smart(request).graph(limit=limit)


@router.get("/files/{document_id}/card")
def knowledge_card(document_id: str, request: Request) -> dict:
    try:
        return _smart(request).knowledge_card(document_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/files/{document_id}/timeline")
def document_timeline(document_id: str, request: Request) -> dict:
    try:
        return {"items": _smart(request).timeline(document_id)}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/files/{document_id}/watchers",
    status_code=status.HTTP_201_CREATED,
)
def create_watcher(
    document_id: str,
    payload: WatchCreate,
    request: Request,
) -> dict:
    try:
        return _smart(request).create_watch(
            document_id,
            payload.event_type,
            config=payload.config,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/files/{document_id}/watchers")
def list_watchers(document_id: str, request: Request) -> dict:
    try:
        return {"items": _smart(request).list_watches(document_id)}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/watchers/{rule_id}")
def delete_watcher(rule_id: str, request: Request) -> dict:
    if not _smart(request).delete_watch(rule_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Наблюдатель не найден.",
        )
    return {"ok": True, "rule_id": rule_id}


@router.get("/alerts")
def list_alerts(
    request: Request,
    include_resolved: bool = False,
) -> dict:
    return {
        "items": _smart(request).alerts(
            include_resolved=include_resolved,
        )
    }


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, request: Request) -> dict:
    if not _smart(request).resolve_alert(alert_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сигнал не найден.",
        )
    return {"ok": True, "alert_id": alert_id}


@router.post("/snapshots", status_code=status.HTTP_201_CREATED)
def create_snapshot(
    payload: SnapshotCreate,
    request: Request,
) -> dict:
    return _smart(request).create_snapshot(payload.label)


@router.get("/snapshots")
def list_snapshots(request: Request) -> dict:
    return {"items": _smart(request).list_snapshots()}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str, request: Request) -> dict:
    try:
        return _smart(request).get_snapshot(snapshot_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/snapshots/{snapshot_id}/restore")
def restore_snapshot(snapshot_id: str, request: Request) -> dict:
    try:
        return _smart(request).restore_snapshot(snapshot_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/files/{document_id}/seal")
def seal_document(document_id: str, request: Request) -> dict:
    try:
        return _smart(request).seal(document_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/files/{document_id}/seal")
def latest_seal(document_id: str, request: Request) -> dict:
    try:
        seal = _smart(request).latest_seal(document_id)
        return {"seal": seal}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/files/{document_id}/seal/verify")
def verify_seal(
    document_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
) -> dict:
    try:
        return _smart(request).verify_seal(
            document_id,
            version=version,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/files/{document_id}/clean-room")
async def clean_room(
    document_id: str,
    payload: SmartAskRequest,
    request: Request,
) -> dict:
    smart = _smart(request)
    try:
        contract = smart.get_contract(document_id)
        if contract["expired"]:
            raise PermissionError("Срок ИИ-договора истёк.")
        required = ("content_read", "answer", "external_ai", "clean_room")
        if not all(contract[name] for name in required):
            raise PermissionError(
                "ИИ-договор не разрешает режим «Чистая комната»."
            )
        if not request.app.state.ai_router.has_provider("deepseek"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DeepSeek не настроен.",
            )

        item, chunks = _ephemeral_chunks(
            document_id,
            payload.question,
            request,
            limit=7,
        )
        if not chunks:
            raise ValueError("В документе не найден текст для анализа.")

        sources = []
        context_parts = []
        for number, chunk in enumerate(chunks, start=1):
            text = chunk.text[:3_500]
            sources.append(
                {
                    "source_no": number,
                    "label": chunk.label,
                    "page": chunk.page,
                    "characters_sent": len(text),
                }
            )
            context_parts.append(
                f"[Источник {number}: {chunk.label}]\n{text}"
            )

        response = await request.app.state.ai_router.generate(
            "deepseek",
            AIRequest(
                system_prompt=(
                    "Ты Дракончик Тоору в режиме Чистой комнаты. "
                    "Используй только переданные фрагменты. "
                    "Не придумывай отсутствующие факты. "
                    "Не проси сохранять данные в память. "
                    "Ссылайся на [Источник N]."
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
            "clean_room_used",
            actor="tooru",
            details={
                "version": item["version"],
                "source_count": len(sources),
                "persistent_index_created": False,
                "memory_written": False,
            },
        )
        smart.consume_one_time_answer(document_id)
        return {
            "answer": response.text,
            "document_id": document_id,
            "version": item["version"],
            "sources": sources,
            "clean_room": True,
            "retained_document_content": False,
            "persistent_index_created": False,
            "memory_written": False,
            "provider": response.provider,
            "model": response.model,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/files/{document_id}/compare")
async def compare_documents(
    document_id: str,
    payload: CompareRequest,
    request: Request,
) -> dict:
    smart = _smart(request)
    other_id = payload.other_document_id
    try:
        for candidate in (document_id, other_id):
            contract = smart.get_contract(candidate)
            if contract["expired"]:
                raise PermissionError(
                    f"Срок ИИ-договора истёк для {candidate}."
                )
            required = ("content_read", "compare", "external_ai")
            if not all(contract[name] for name in required):
                raise PermissionError(
                    f"ИИ-договор документа {candidate} "
                    "не разрешает сравнение через внешний ИИ."
                )
        if not request.app.state.ai_router.has_provider("deepseek"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DeepSeek не настроен.",
            )

        first, first_chunks = _ephemeral_chunks(
            document_id,
            payload.question,
            request,
            limit=5,
        )
        second, second_chunks = _ephemeral_chunks(
            other_id,
            payload.question,
            request,
            limit=5,
        )

        context: list[str] = []
        sources: list[dict[str, Any]] = []
        counter = 1
        for side, item, chunks in (
            ("A", first, first_chunks),
            ("B", second, second_chunks),
        ):
            for chunk in chunks:
                text = chunk.text[:2_800]
                context.append(
                    f"[Источник {counter} · Документ {side} · "
                    f"{chunk.label}]\n{text}"
                )
                sources.append(
                    {
                        "source_no": counter,
                        "document_id": item["id"],
                        "document_name": item["name"],
                        "label": chunk.label,
                        "page": chunk.page,
                    }
                )
                counter += 1

        response = await request.app.state.ai_router.generate(
            "deepseek",
            AIRequest(
                system_prompt=(
                    "Сравни два документа только по переданным источникам. "
                    "Разделяй подтверждённые различия и то, чего нельзя "
                    "установить. Для каждого важного вывода указывай "
                    "[Источник N]."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Документ A: {first['name']}\n"
                            f"Документ B: {second['name']}\n\n"
                            + "\n\n".join(context)
                            + "\n\nЗадача: "
                            + payload.question
                        ),
                    }
                ],
                max_tokens=2_200,
            ),
        )
        for candidate in (document_id, other_id):
            smart.record_provenance(
                candidate,
                "documents_compared",
                actor="tooru",
                details={
                    "other_document_id": (
                        other_id if candidate == document_id else document_id
                    ),
                    "memory_written": False,
                },
            )
            smart.consume_one_time_answer(candidate)
        return {
            "answer": response.text,
            "document_a": {
                "id": first["id"],
                "name": first["name"],
                "version": first["version"],
            },
            "document_b": {
                "id": second["id"],
                "name": second["name"],
                "version": second["version"],
            },
            "sources": sources,
            "memory_written": False,
            "provider": response.provider,
            "model": response.model,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc
