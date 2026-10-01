from __future__ import annotations

from typing import Any

from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope

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
            f"Дата работы: {dna.get('work_date') or '—'}.",
            f"Часы: {dna.get('work_hours') or 0}.",
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


def sync_vehicle(memory_intake, item: dict[str, Any]) -> None:
    memory_intake.ingest(
        vehicle_memory(item),
        reason="Garage record changed; refresh durable project context.",
    )


def sync_weekend_work(memory_intake, dna: dict[str, Any]) -> None:
    memory = weekend_work_memory(dna)
    if memory is None:
        return
    memory_intake.ingest(
        memory,
        reason="Weekend-work DNA changed; refresh durable timesheet context.",
    )
