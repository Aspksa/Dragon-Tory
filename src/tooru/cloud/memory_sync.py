from __future__ import annotations

from typing import Any

from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope
from tooru.observability.context import observation_context

PROJECT_ID = "dragon-tory"


def vehicle_memory(item: dict[str, Any]) -> MemoryCreate:
    content = "\n".join(
        [
            "Модуль: garage.",
            f"Автомобиль ID: {item['id']}.",
            f"Гаражный номер: {item.get('garage_number') or '—'}.",
            f"Госномер: {item.get('plate_number') or '—'}.",
            f"VIN: {item.get('vin') or '—'}.",
            f"Марка/модель: {item.get('make_model') or '—'}.",
            f"Закреплённый водитель: {item.get('driver_name') or '—'}.",
            f"Топливо: {item.get('fuel_type') or '—'}.",
            (
                "Расход ГСМ лето: "
                f"{item.get('fuel_rate_summer') if item.get('fuel_rate_summer') is not None else '—'} л/100 км."
            ),
            (
                "Расход ГСМ зима: "
                f"{item.get('fuel_rate_winter') if item.get('fuel_rate_winter') is not None else '—'} л/100 км."
            ),
            f"Шины лето: {item.get('tire_size_summer') or '—'}.",
            f"Шины зима: {item.get('tire_size_winter') or '—'}.",
            (
                "Страховка: "
                f"{item.get('insurance_type') or '—'}; "
                f"полис {item.get('insurance_policy') or '—'}; "
                f"с {item.get('insurance_start') or '—'} "
                f"по {item.get('insurance_end') or '—'}."
            ),
            f"Примечание: {item.get('notes') or '—'}.",
        ]
    )
    return MemoryCreate(
        owner_id="local-user",
        scope=MemoryScope.PROJECT,
        project_id=PROJECT_ID,
        kind=MemoryKind.ENTITY,
        content=content,
        key=f"garage-vehicle:{item['id']}",
        source="tooru-garage-auto-sync",
        source_ref=str(item["id"]),
        confidence=1.0,
        importance=0.72,
        tags=["module-knowledge", "garage", "vehicle", "auto-sync"],
    )


def weekend_work_memory(dna: dict[str, Any]) -> MemoryCreate | None:
    if str(dna.get("kind") or "").strip().casefold() != "служебная записка":
        return None
    if (
        str(dna.get("document_subtype") or "").strip().casefold()
        != "работа в выходной день"
    ):
        return None
    if dna.get("work_date_conflict"):
        return None

    document = dna.get("document") or {}
    document_id = str(dna.get("document_id") or document.get("id") or "")
    if not document_id:
        return None

    document_name = str(document.get("name") or document_id)
    employee = str(dna.get("employee_name") or "").strip() or "Сотрудник не указан"
    content = "\n".join(
        [
            "Модуль: timesheet.",
            f"Источник: {document_name}.",
            f"Tory Document ID: {document_id}.",
            f"Сотрудник: {employee}.",
            f"Подразделение: {dna.get('department') or '—'}.",
            "Даты работы: "
            + (
                ", ".join(str(value) for value in (dna.get("work_dates") or []))
                or str(dna.get("work_date") or "—")
            )
            + ".",
            f"Часы на запись: {dna.get('work_hours') or 0}.",
            f"Основание: {dna.get('work_reason') or '—'}.",
        ]
    )
    return MemoryCreate(
        owner_id="local-user",
        scope=MemoryScope.PROJECT,
        project_id=PROJECT_ID,
        kind=MemoryKind.EVENT,
        content=content,
        key=f"timesheet-entry:{document_id}",
        source="tooru-timesheet-auto-sync",
        source_ref=document_id,
        confidence=1.0,
        importance=0.68,
        tags=[
            "module-knowledge",
            "timesheet",
            "weekend-work",
            "auto-sync",
        ],
    )


def sync_vehicle(memory_intake, item: dict[str, Any]):
    source_id = str(item["id"])
    with observation_context(
        module="garage",
        source_type="garage",
        source_id=source_id,
        new_trace=True,
    ):
        observability = getattr(memory_intake.guardian, "observability", None)
        if observability is not None:
            observability.event(
                category="source",
                stage="source",
                operation="garage_record_changed",
                status="success",
                module="garage",
                source_type="garage",
                source_id=source_id,
                message="Изменение гаража передано в проектную память.",
            )
        return memory_intake.ingest(
            vehicle_memory(item),
            reason="Garage record changed; refresh durable project context.",
        )


def sync_weekend_work(memory_intake, dna: dict[str, Any]):
    memory = weekend_work_memory(dna)
    if memory is None:
        return None
    document_id = str(memory.source_ref or "")
    with observation_context(
        module="timesheet",
        source_type="document",
        source_id=document_id,
        document_id=document_id,
        new_trace=True,
    ):
        observability = getattr(memory_intake.guardian, "observability", None)
        if observability is not None:
            observability.event(
                category="source",
                stage="source",
                operation="weekend_work_changed",
                status="success",
                module="timesheet",
                source_type="document",
                source_id=document_id,
                document_id=document_id,
                message="Запись работы в выходной передана в память табеля.",
            )
        return memory_intake.ingest(
            memory,
            reason="Weekend-work DNA changed; refresh durable timesheet context.",
        )
