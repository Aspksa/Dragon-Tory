from __future__ import annotations

import json
from typing import Any, ClassVar

from tooru.ai.base import AIRequest
from tooru.cloud.document_intelligence import OCRUnavailableError
from tooru.cloud.intelligence import UnsupportedDocumentError
from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope

PROJECT_ID = "dragon-tory"


class ModuleLearningService:
    DOCUMENT_MODULES: ClassVar[set[str]] = {"contracts", "invoice_offers"}
    STRUCTURED_MODULES: ClassVar[set[str]] = {"garage", "timesheet"}
    SUPPORTED_MODULES: ClassVar[set[str]] = (
        DOCUMENT_MODULES | STRUCTURED_MODULES
    )

    def __init__(
        self,
        *,
        memory,
        smart,
        intelligence,
        ai_router,
    ) -> None:
        self.memory = memory
        self.smart = smart
        self.intelligence = intelligence
        self.ai_router = ai_router

    async def study(self, module_id: str) -> dict[str, Any]:
        if module_id not in self.SUPPORTED_MODULES:
            raise KeyError(module_id)
        if module_id in self.DOCUMENT_MODULES:
            return await self._study_documents(module_id)
        if module_id == "garage":
            return self._study_garage()
        return self._study_timesheet()

    async def _study_documents(self, module_id: str) -> dict[str, Any]:
        profile = self.intelligence.module_profile(module_id)
        memory_ids: list[str] = []
        skipped: list[dict[str, str]] = []
        external_ai_count = 0

        for item in profile["items"]:
            document_id = item["id"]
            try:
                contract = self.smart.get_contract(document_id)
            except KeyError:
                skipped.append(
                    {"id": document_id, "reason": "ИИ-договор не найден"}
                )
                continue

            if contract["expired"]:
                skipped.append(
                    {"id": document_id, "reason": "ИИ-договор истёк"}
                )
                continue
            if not (contract["content_read"] and contract["memory"]):
                skipped.append(
                    {
                        "id": document_id,
                        "reason": (
                            "Для изучения нужны разрешения "
                            "content_read + memory"
                        ),
                    }
                )
                continue

            analysis = self._analysis_for(document_id)
            dna = self.smart.get_dna(document_id)
            local_summary = self._document_local_summary(
                module_id=module_id,
                item=item,
                dna=dna,
                analysis=analysis,
            )
            knowledge = local_summary
            mode = "local-structured"

            if (
                contract["answer"]
                and contract["external_ai"]
                and self.ai_router.has_provider("deepseek")
            ):
                try:
                    source = self.intelligence.version_text(
                        document_id,
                        int(item["version"]),
                    )
                    knowledge = await self._deep_summary(
                        module_id=module_id,
                        local_summary=local_summary,
                        source_text=source["text"][:45_000],
                    )
                    external_ai_count += 1
                    mode = "deepseek"
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
                    knowledge = local_summary

            memory = self.memory.add(
                MemoryCreate(
                    owner_id="local-user",
                    scope=MemoryScope.PROJECT,
                    project_id=PROJECT_ID,
                    kind=MemoryKind.SUMMARY,
                    content=knowledge,
                    key=f"document-knowledge:{document_id}",
                    source="tooru-module-study",
                    source_ref=(
                        f"{document_id}:v{item['version']}:"
                        f"{item.get('sha256') or ''}"
                    )[:500],
                    confidence=float(
                        analysis.get("confidence")
                        if analysis
                        else 0.8
                    ),
                    importance=0.82,
                    tags=[
                        "module-knowledge",
                        module_id,
                        "document",
                        str(dna.get("kind") or item["effective_kind"]),
                    ],
                )
            )
            memory_ids.append(memory.id)
            self.smart.record_provenance(
                document_id,
                "module_memory_studied",
                actor="tooru",
                details={
                    "module_id": module_id,
                    "document_version": item["version"],
                    "memory_id": memory.id,
                    "mode": mode,
                    "external_ai_used": mode == "deepseek",
                },
            )

        return {
            "module_id": module_id,
            "studied": len(memory_ids),
            "skipped": len(skipped),
            "external_ai_summaries": external_ai_count,
            "memory_ids": memory_ids,
            "skipped_items": skipped[:100],
            "scope": "project",
            "project_id": PROJECT_ID,
        }

    def _analysis_for(self, document_id: str) -> dict[str, Any]:
        try:
            return self.intelligence.get(document_id)
        except KeyError:
            analysis = self.intelligence.analyze(document_id)
            self.smart.apply_intelligence_defaults(
                document_id,
                analysis,
            )
            return analysis

    async def _deep_summary(
        self,
        *,
        module_id: str,
        local_summary: str,
        source_text: str,
    ) -> str:
        type_name = (
            "договора"
            if module_id == "contracts"
            else "счёта-оферты"
        )
        response = await self.ai_router.generate(
            "deepseek",
            AIRequest(
                system_prompt=(
                    "Ты Дракончик Тоору. Изучи документ предприятия и "
                    "сформируй долговременное проектное знание. "
                    "Пиши только факты из документа, не делай юридических "
                    "выводов и не придумывай отсутствующие условия. "
                    f"Для {type_name} выдели: стороны, предмет, номер/дату, "
                    "суммы и валюту, сроки, оплату, поставку, обязательства, "
                    "ответственность, прекращение/продление, важные условия "
                    "и ссылки на связанные документы. Формат — компактные "
                    "структурированные пункты, пригодные для памяти."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Локально извлечённые данные:\n"
                            + local_summary
                            + "\n\nТекст документа:\n"
                            + source_text
                        ),
                    }
                ],
                max_tokens=2_400,
            ),
        )
        return response.text.strip() or local_summary

    @staticmethod
    def _document_local_summary(
        *,
        module_id: str,
        item: dict[str, Any],
        dna: dict[str, Any],
        analysis: dict[str, Any],
    ) -> str:
        entities = analysis.get("entities") or {}
        deadlines = analysis.get("deadlines") or []
        values = [
            f"Модуль: {module_id}.",
            f"Документ: {item['name']}.",
            f"Tory Document ID: {item['id']}.",
            f"Версия: {item['version']}.",
            f"Тип: {dna.get('kind') or item.get('effective_kind') or '—'}.",
        ]
        if dna.get("counterparty"):
            values.append(f"Контрагент: {dna['counterparty']}.")
        if dna.get("document_number"):
            values.append(f"Номер: {dna['document_number']}.")
        if dna.get("document_date"):
            values.append(f"Дата: {dna['document_date']}.")
        if dna.get("amount_value") is not None:
            values.append(
                "Сумма: "
                f"{dna['amount_value']} {dna.get('amount_currency') or ''}."
            )
        if dna.get("terms_summary"):
            values.append(f"Ключевые условия: {dna['terms_summary']}.")
        if analysis.get("summary_local"):
            values.append(
                "Локальное резюме: "
                + str(analysis["summary_local"])[:1_500]
            )
        if deadlines:
            values.append(
                "Сроки: "
                + json.dumps(
                    deadlines[:20],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        if entities:
            compact = {
                key: value
                for key, value in entities.items()
                if value
            }
            if compact:
                values.append(
                    "Извлечённые сущности: "
                    + json.dumps(
                        compact,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )[:4_000]
                )
        return "\n".join(values)

    def _study_garage(self) -> dict[str, Any]:
        memory_ids: list[str] = []
        items = self.smart.list_vehicles(limit=1_000)
        for item in items:
            if not item.get("active", True):
                continue
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
            memory = self.memory.add(
                MemoryCreate(
                    owner_id="local-user",
                    scope=MemoryScope.PROJECT,
                    project_id=PROJECT_ID,
                    kind=MemoryKind.ENTITY,
                    content=content,
                    key=f"garage-vehicle:{item['id']}",
                    source="tooru-garage-study",
                    source_ref=item["id"],
                    confidence=1.0,
                    importance=0.72,
                    tags=["module-knowledge", "garage", "vehicle"],
                )
            )
            memory_ids.append(memory.id)
        return {
            "module_id": "garage",
            "studied": len(memory_ids),
            "skipped": len(items) - len(memory_ids),
            "external_ai_summaries": 0,
            "memory_ids": memory_ids,
            "skipped_items": [],
            "scope": "project",
            "project_id": PROJECT_ID,
        }

    def _study_timesheet(self) -> dict[str, Any]:
        memory_ids: list[str] = []
        timesheet = self.smart.weekend_timesheet()
        for item in timesheet["items"]:
            content = "\n".join(
                [
                    "Модуль: timesheet.",
                    f"Источник: {item['document_name']}.",
                    f"Tory Document ID: {item['document_id']}.",
                    f"Сотрудник: {item['employee_name']}.",
                    f"Подразделение: {item.get('department') or '—'}.",
                    f"Дата работы: {item.get('work_date') or '—'}.",
                    f"Часы: {item.get('work_hours') or 0}.",
                    f"Основание: {item.get('work_reason') or '—'}.",
                ]
            )
            memory = self.memory.add(
                MemoryCreate(
                    owner_id="local-user",
                    scope=MemoryScope.PROJECT,
                    project_id=PROJECT_ID,
                    kind=MemoryKind.EVENT,
                    content=content,
                    key=f"timesheet-entry:{item['document_id']}",
                    source="tooru-timesheet-study",
                    source_ref=item["document_id"],
                    confidence=1.0,
                    importance=0.68,
                    tags=[
                        "module-knowledge",
                        "timesheet",
                        "weekend-work",
                    ],
                )
            )
            memory_ids.append(memory.id)
        return {
            "module_id": "timesheet",
            "studied": len(memory_ids),
            "skipped": 0,
            "external_ai_summaries": 0,
            "memory_ids": memory_ids,
            "skipped_items": [],
            "scope": "project",
            "project_id": PROJECT_ID,
        }
