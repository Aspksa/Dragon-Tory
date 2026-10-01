from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from tooru.ai.base import AIRequest
from tooru.ai.prompt_guard import UNTRUSTED_CONTENT_POLICY, wrap_untrusted_text
from tooru.cloud.document_intelligence import OCRUnavailableError
from tooru.cloud.intelligence import UnsupportedDocumentError
from tooru.cloud.memory_sync import sync_weekend_work

logger = logging.getLogger(__name__)

_WEEKEND_RE = re.compile(
    r"(?:работ[ауы]?\s+в\s+выходн|выходн(?:ой|ого)\s+день)",
    re.IGNORECASE,
)
_DAY_RE = re.compile(
    r"\b(?:на\s+)?(0?[1-9]|[12]\d|3[01])(?:[-./](0?[1-9]|1[0-2])(?:[-./]((?:19|20)\d{2}))?)?\b"
)
_HOURS_RE = re.compile(
    r"\b(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:ч(?:ас(?:а|ов)?)?|часов)\b",
    re.IGNORECASE,
)
_DRIVER_RE = re.compile(
    r"(?:водителю|сотруднику|работнику)\s+(.+?)(?=\s+(?:на|в)\s+\d{1,2}\b|[,.!?]|$)",
    re.IGNORECASE,
)

_MONTHS_RU = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)


def is_weekend_work_request(message: str) -> bool:
    return bool(_WEEKEND_RE.search(message))


def _resolve_date(message: str) -> tuple[int, int, int]:
    now = datetime.now().astimezone()
    match = _DAY_RE.search(message)
    if match is None:
        return now.year, now.month, now.day
    day = int(match.group(1))
    month = int(match.group(2) or now.month)
    year = int(match.group(3) or now.year)
    date(year, month, day)
    return year, month, day


def _resolve_employee(
    message: str,
    employees: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lowered = message.casefold()
    exact = [
        item
        for item in employees
        if item.get("full_name")
        and item["full_name"].casefold() in lowered
    ]
    if len(exact) == 1:
        return exact[0]

    for item in employees:
        full_name = str(item.get("full_name") or "").strip()
        if not full_name:
            continue
        surname = full_name.split()[0].casefold()
        if len(surname) >= 3 and re.search(
            rf"\b{re.escape(surname)}\b",
            lowered,
        ):
            return item

    match = _DRIVER_RE.search(message)
    if match is None:
        return None
    fragment = match.group(1).strip().casefold()
    matches = [
        item
        for item in employees
        if fragment in str(item.get("full_name") or "").casefold()
        or fragment in str(item.get("personnel_number") or "").casefold()
    ]
    return matches[0] if len(matches) == 1 else None


def _requested_hours(message: str) -> float | None:
    match = _HOURS_RE.search(message)
    if match is None:
        return None
    value = float(match.group(1).replace(",", "."))
    return value if 0 <= value <= 24 else None


async def create_weekend_work_document(
    *,
    request: Any,
    message: str,
) -> dict[str, Any]:
    smart = request.app.state.cloud_smart
    cloud = request.app.state.cloud_store
    intelligence = request.app.state.document_intelligence
    ai_router = request.app.state.ai_router

    year, month, day = _resolve_date(message)
    employees = smart.list_employees(limit=1_000)
    employee = _resolve_employee(message, employees)
    employee_name = (
        str(employee["full_name"])
        if employee is not None
        else (_DRIVER_RE.search(message).group(1).strip()
              if _DRIVER_RE.search(message) else "Сотрудник не указан")
    )
    department = (
        str(employee.get("department") or "")
        if employee is not None
        else ""
    )
    vehicles = (
        smart.list_vehicles(query=employee_name, limit=20)
        if employee_name != "Сотрудник не указан"
        else []
    )
    vehicle = next(
        (
            item
            for item in vehicles
            if item.get("driver_employee_id")
            and employee is not None
            and item["driver_employee_id"] == employee["id"]
        ),
        vehicles[0] if len(vehicles) == 1 else None,
    )

    references: list[dict[str, Any]] = []
    source_parts: list[str] = []
    profile = intelligence.module_profile("memos")
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
            source = intelligence.version_text(
                item["id"],
                int(item["version"]),
            )
        except (
            KeyError,
            FileNotFoundError,
            PermissionError,
            UnsupportedDocumentError,
            OCRUnavailableError,
            ValueError,
            RuntimeError,
            OSError,
        ):
            continue
        text = source["text"].strip()[:10_000]
        if not text:
            continue
        number = len(references) + 1
        references.append(
            {
                "source_no": number,
                "document_id": item["id"],
                "name": item["name"],
                "version": item["version"],
            }
        )
        source_parts.append(
            f"[Образец {number}: {item['name']}]\n"
            + wrap_untrusted_text(
                text,
                source=f"weekend-template:{item['id']}:v{item['version']}",
            )
        )

    work_date = f"{year:04d}-{month:02d}-{day:02d}"
    vehicle_text = ""
    if vehicle is not None:
        vehicle_text = (
            f"Автомобиль: {vehicle.get('make_model') or '—'}; "
            f"госномер: {vehicle.get('plate_number') or '—'}; "
            f"гаражный №: {vehicle.get('garage_number') or '—'}."
        )

    prompt = (
        f"Нужно подготовить служебную записку «Работа в выходной день».\n"
        f"Сотрудник: {employee_name}.\n"
        f"Подразделение: {department or '[указать]'}.\n"
        f"Дата работы: {work_date}.\n"
        f"{vehicle_text}\n"
        f"Исходный запрос пользователя: {message}\n"
        "Не придумывай ФИО руководителя, табельный номер, часы, причины или "
        "другие факты, которых нет в запросе/справочниках. Оставляй такие "
        "места в квадратных скобках."
    )
    if source_parts:
        prompt = "\n\n".join(source_parts) + "\n\n" + prompt

    if ai_router.has_provider("deepseek"):
        response = await ai_router.generate(
            "deepseek",
            AIRequest(
                system_prompt=(
                    "Ты Дракончик Тоору. Создай только готовый текст "
                    "служебной записки в стиле предприятия. Используй "
                    "переданные образцы как эталоны структуры и языка, но "
                    "не копируй из них чужие персональные данные и факты. "
                    + UNTRUSTED_CONTENT_POLICY
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2_200,
            ),
        )
        draft = response.text.strip()
        provider = response.provider
        model = response.model
    else:
        draft = (
            "СЛУЖЕБНАЯ ЗАПИСКА\n\n"
            "Работа в выходной день\n\n"
            f"Сотрудник: {employee_name}\n"
            f"Подразделение: {department or '[указать]'}\n"
            f"Дата работы: {work_date}\n"
            f"{vehicle_text}\n"
            "Количество часов: [указать]\n"
            "Основание / выполняемая работа: [указать]\n"
        ).strip()
        provider = "local-template"
        model = "weekend-work-v1"

    folder = cloud.ensure_folder_path(
        [
            "Служебные записки",
            f"{year} год",
            _MONTHS_RU[month],
            "Работа выходной",
        ]
    )
    safe_name = re.sub(
        r"[^0-9A-Za-zА-Яа-яЁё _.-]+",
        "",
        employee_name,
    ).strip() or "Сотрудник"
    filename = f"{safe_name} Р-В {day:02d}.md"
    item = cloud.register_generated_text(
        name=filename,
        content=draft,
        folder_id=folder["id"] if folder else None,
        source="tooru-chat-weekend-work",
    )

    hours = _requested_hours(message)
    dna = smart.update_dna(
        item["id"],
        {
            "kind": "служебная записка",
            "document_subtype": "Работа в выходной день",
            "employee_name": employee_name,
            "department": department,
            "work_date": work_date,
            "work_hours": hours,
            "work_reason": message[:2_000],
            "origin": "Создано Тоору из чата",
            "notes": (
                f"Использовано эталонов: {len(references)}. "
                "Автоматически сохранено в структуру год/месяц."
            ),
        },
        actor="tooru-chat",
    )
    memory_written = False
    try:
        memory_result = sync_weekend_work(
            request.app.state.memory_intake,
            dna,
        )
        memory_written = bool(
            memory_result is not None and memory_result.memory is not None
        )
    except Exception as sync_exc:
        logger.warning("Weekend-work memory auto-sync failed: %s", sync_exc)

    smart.record_provenance(
        item["id"],
        "chat_document_created",
        actor="tooru",
        details={
            "workflow": "weekend_work",
            "references": references,
            "employee_id": employee["id"] if employee else None,
            "vehicle_id": vehicle["id"] if vehicle else None,
            "memory_written": memory_written,
            "training_performed": False,
        },
    )
    path = (
        f"Служебные записки / {year} год / "
        f"{_MONTHS_RU[month]} / Работа выходной / {filename}"
    )
    return {
        "document_id": item["id"],
        "name": filename,
        "path": path,
        "draft": draft,
        "employee": employee,
        "vehicle": vehicle,
        "work_date": work_date,
        "work_hours": hours,
        "references": references,
        "provider": provider,
        "model": model,
    }
