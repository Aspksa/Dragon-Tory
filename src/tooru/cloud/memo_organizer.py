from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tooru.memory.models import MemoryCreate, MemoryKind, MemoryScope

PROJECT_ID = "dragon-tory"

_DATE_RE = re.compile(
    r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}\b"
    r"|\b(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])\b"
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_DOC_DATE_RE = re.compile(
    r"(?im)(?:служебн(?:ая|ой)\s+записк[а-я]*[^\n]{0,90}?\bот\b|"
    r"(?:дата|от)\s*[:№-]?)\s*"
    r"((?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}"
    r"|(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])"
    r"|(?:19|20)\d{2})"
)
_NUMBER_RE = re.compile(
    r"(?im)(?:служебн(?:ая|ой)\s+записк[а-я]*[^\n]{0,80}?№|"
    r"(?:номер|№)\s*)[:№\s-]*([A-ZА-Я0-9][A-ZА-Я0-9._/-]{0,80})"
)
_ORG_RE = re.compile(
    r"(?im)^\s*(?:организация|предприятие|компания)\s*[:\-]\s*([^\n\r]{2,250})"
)
_DEPARTMENT_RE = re.compile(
    r"(?im)^\s*(?:подразделение|отдел|служба)\s*[:\-]\s*([^\n\r]{2,250})"
)
_AUTHOR_RE = re.compile(
    r"(?im)^\s*(?:от кого|автор|инициатор)\s*[:\-]\s*([^\n\r]{2,250})"
)
_ADDRESSEE_RE = re.compile(
    r"(?im)^\s*(?:кому|адресат)\s*[:\-]\s*([^\n\r]{2,250})"
)
_SUBJECT_RE = re.compile(
    r"(?im)^\s*(?:тема|о чем|о чём)\s*[:\-]\s*([^\n\r]{3,400})"
)
_PLATE_RE = re.compile(
    r"\b[АВЕКМНОРСТУХABEKMHOPCTYX]\s?\d{3}\s?"
    r"[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s?\d{2,3}\b",
    re.IGNORECASE,
)
_INVENTORY_RE = re.compile(
    r"(?i)(?:инвентарн(?:ый|ого)\s+(?:номер|№)|инв\.?\s*№?)\s*"
    r"[:\-]?\s*([A-ZА-Я0-9][A-ZА-Я0-9._/-]{1,80})"
)
_VAT_RE = re.compile(r"(?i)\b(?:НДС|VAT)\b[^\n\r]{0,100}")
_REQUEST_RE = re.compile(
    r"(?i)\b(?:прошу|просим|предлагаю|просим\s+согласовать|"
    r"необходимо|требуется|ходатайствую)\b"
)
_RESULT_RE = re.compile(
    r"(?i)\b(?:выполнено|исполнено|согласовано|утверждено|оплачено|"
    r"выплачено|заключ[её]н|приобретено|поставлено|отремонтировано)\b"
)
_TEMPLATE_RE = re.compile(
    r"(?i)(?:шаблон|образец|бланк|template|sample|"
    r"\[\s*(?:фио|дата|номер|подразделение)\s*\]|"
    r"__+[./-]__+|<\s*(?:фио|дата|номер)[^>]*>)"
)

_TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "Премирование": ("премир", "премия"),
    "Надбавки и доплаты": ("надбав", "доплат"),
    "Компенсации": ("компенсац",),
    "Возмещение расходов": ("возмещ", "расход", "подотч"),
    "Командировки": ("командиров", "суточн"),
    "Подготовка доверенностей": ("доверенност",),
    "Согласование и изменение договоров": (
        "согласоват",
        "изменен",
        "изменить договор",
        "дополнительное соглашение",
    ),
    "Закупка товаров": ("закупк", "товар", "поставка", "приобрести"),
    "Закупка работ и услуг": ("работ", "услуг", "подряд"),
    "Ремонт и техническое состояние": (
        "ремонт",
        "техническ",
        "неисправ",
        "диагност",
    ),
    "Учёт имущества и ГСМ": (
        "имущество",
        "гсм",
        "топлив",
        "инвентар",
        "учет",
        "учёт",
    ),
    "Нарушения и дисциплинарные вопросы": (
        "нарушен",
        "дисциплинар",
        "объяснитель",
        "взыскан",
    ),
    "Работа в выходной день": (
        "работа в выходной",
        "выходной день",
        "привлечь к работе",
    ),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_service_memo_schema(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS service_memo_records (
            document_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            document_year TEXT NOT NULL,
            year_source TEXT NOT NULL,
            topic TEXT NOT NULL,
            topic_reason TEXT NOT NULL,
            is_template INTEGER NOT NULL DEFAULT 0,
            folder_id TEXT,
            folder_path TEXT NOT NULL,
            duplicate_of TEXT,
            possible_version_of TEXT,
            facts_json TEXT NOT NULL,
            discrepancies_json TEXT NOT NULL,
            review_json TEXT NOT NULL,
            memory_status TEXT NOT NULL DEFAULT '',
            memory_id TEXT,
            processed_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_memo_year_topic
        ON service_memo_records(document_year, topic)
        """
    )


def _snippet(text: str, start: int, end: int, radius: int = 130) -> str:
    value = text[max(0, start - radius) : min(len(text), end + radius)]
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:500]


def _normalized_stem(name: str) -> str:
    stem = Path(name).stem.casefold()
    stem = _YEAR_RE.sub("", stem)
    stem = re.sub(r"(?i)\b(?:копия|copy|версия|version|v\d+)\b", "", stem)
    return re.sub(r"[^a-zа-я0-9]+", "", stem)


class ServiceMemoOrganizer:
    """Apply service-memo-only study, sorting, evidence and memory rules."""

    def __init__(
        self,
        *,
        cloud_store,
        smart,
        intelligence,
        memory_intake,
    ) -> None:
        self.cloud_store = cloud_store
        self.smart = smart
        self.intelligence = intelligence
        self.memory_intake = memory_intake
        self.db_path = cloud_store.db_path

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def initialize(self) -> None:
        with self._connect() as db:
            ensure_service_memo_schema(db)

    @staticmethod
    def _fact(
        *,
        value: Any = "не указано",
        source: str = "",
        snippet: str = "",
    ) -> dict[str, Any]:
        return {
            "value": value if value not in (None, "", [], {}) else "не указано",
            "source": source or "не указано",
            "snippet": snippet or "не указано",
        }

    @staticmethod
    def _first_match(
        chunks,
        pattern: re.Pattern[str],
        *,
        group: int = 1,
    ) -> dict[str, Any]:
        for chunk in chunks:
            match = pattern.search(chunk.text)
            if match:
                return ServiceMemoOrganizer._fact(
                    value=match.group(group).strip(),
                    source=chunk.label,
                    snippet=_snippet(chunk.text, match.start(), match.end()),
                )
        return ServiceMemoOrganizer._fact()

    @staticmethod
    def _all_matches(
        chunks,
        pattern: re.Pattern[str],
        *,
        group: int = 1,
        limit: int = 50,
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for chunk in chunks:
            for match in pattern.finditer(chunk.text):
                value = match.group(group).strip()
                key = (value.casefold(), chunk.label.casefold())
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "value": value,
                        "source": chunk.label,
                        "snippet": _snippet(
                            chunk.text,
                            match.start(),
                            match.end(),
                        ),
                    }
                )
                if len(result) >= limit:
                    return result
        return result

    @staticmethod
    def _lines_with(
        chunks,
        pattern: re.Pattern[str],
        *,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for chunk in chunks:
            for line in chunk.text.splitlines():
                cleaned = " ".join(line.split())
                if not cleaned or not pattern.search(cleaned):
                    continue
                key = cleaned.casefold()
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "source": chunk.label,
                        "snippet": cleaned[:500],
                    }
                )
                if len(result) >= limit:
                    return result
        return result

    def _document_year(
        self,
        *,
        chunks,
        name: str,
    ) -> tuple[str, str, str]:
        date_fact = self._first_match(chunks, _DOC_DATE_RE)
        value = date_fact["value"]
        if value != "не указано":
            match = _YEAR_RE.search(str(value))
            if match:
                return (
                    match.group(0),
                    "document_date",
                    "Год определён по дате самой служебной записки.",
                )

        filename_years = _YEAR_RE.findall(name)
        if filename_years:
            return (
                filename_years[0],
                "filename",
                "Год определён по названию файла и требует визуальной проверки.",
            )
        return (
            "Год требует проверки",
            "unknown",
            "В дате записки и названии файла надёжный год не найден.",
        )

    @staticmethod
    def _topic(
        text: str,
        name: str,
    ) -> tuple[str, str, dict[str, int]]:
        text_lower = text.casefold()
        name_lower = name.casefold()
        scores: dict[str, int] = {}
        for topic, keywords in _TOPIC_RULES.items():
            content_score = sum(
                text_lower.count(keyword.casefold())
                for keyword in keywords
            )
            filename_score = sum(
                name_lower.count(keyword.casefold())
                for keyword in keywords
            )
            scores[topic] = content_score * 4 + filename_score
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ordered or ordered[0][1] <= 0:
            return (
                "Тема требует проверки",
                "Основная цель записки не совпала со справочником тем.",
                scores,
            )
        topic, score = ordered[0]
        tie = len(ordered) > 1 and ordered[1][1] == score
        if tie:
            return (
                "Тема требует проверки",
                "Найдено несколько тем с одинаковым весом; требуется проверка.",
                scores,
            )
        return (
            topic,
            "Тема выбрана по содержанию; название файла использовано только как подсказка.",
            scores,
        )

    @staticmethod
    def _summary(text: str) -> str:
        lines = [
            " ".join(line.split())
            for line in text.splitlines()
            if len(" ".join(line.split())) >= 12
        ]
        return " ".join(lines[:6])[:900] or "не указано"

    def _facts(
        self,
        *,
        chunks,
        analysis: dict[str, Any],
        name: str,
    ) -> dict[str, Any]:
        text = "\n\n".join(chunk.text for chunk in chunks)
        entities = analysis.get("entities") or {}

        document_date = self._first_match(chunks, _DOC_DATE_RE)
        document_number = self._first_match(chunks, _NUMBER_RE)
        organization = self._first_match(chunks, _ORG_RE)
        department = self._first_match(chunks, _DEPARTMENT_RE)
        author = self._first_match(chunks, _AUTHOR_RE)
        addressee = self._first_match(chunks, _ADDRESSEE_RE)
        subject = self._first_match(chunks, _SUBJECT_RE)

        requests = self._lines_with(chunks, _REQUEST_RE, limit=8)
        results = self._lines_with(chunks, _RESULT_RE, limit=8)
        goods_services = self._lines_with(
            chunks,
            re.compile(
                r"(?i)\b(?:товар|запчаст|поставка|закуп|работ|услуг|ремонт)\w*\b"
            ),
            limit=20,
        )
        vat = self._lines_with(chunks, _VAT_RE, limit=10)

        plates: list[str] = []
        inventory: list[str] = []
        vehicle_evidence: list[dict[str, str]] = []
        for chunk in chunks:
            for match in _PLATE_RE.finditer(chunk.text):
                value = " ".join(match.group(0).split()).upper()
                if value not in plates:
                    plates.append(value)
                    vehicle_evidence.append(
                        {
                            "value": value,
                            "source": chunk.label,
                            "snippet": _snippet(
                                chunk.text,
                                match.start(),
                                match.end(),
                            ),
                        }
                    )
            for match in _INVENTORY_RE.finditer(chunk.text):
                value = match.group(1).strip()
                if value not in inventory:
                    inventory.append(value)
                    vehicle_evidence.append(
                        {
                            "value": value,
                            "source": chunk.label,
                            "snippet": _snippet(
                                chunk.text,
                                match.start(),
                                match.end(),
                            ),
                        }
                    )

        employees = entities.get("employees") or []
        counterparties = entities.get("counterparties") or []
        dates = entities.get("dates") or []
        amounts = entities.get("amounts") or []
        references = entities.get("references") or []
        vins = entities.get("vin") or []

        employee_evidence = self._lines_with(
            chunks,
            re.compile(r"(?i)\b(?:сотрудник|работник|фио|водитель|исполнитель)\b"),
            limit=20,
        )
        counterparty_evidence = self._lines_with(
            chunks,
            re.compile(
                r"(?i)\b(?:контрагент|поставщик|исполнитель|заказчик|"
                r"продавец|покупатель)\b"
            ),
            limit=20,
        )
        amount_evidence = self._lines_with(
            chunks,
            re.compile(r"(?i)\b(?:сумма|стоимость|итого|руб|eur|usd|₽|€|\$)\b"),
            limit=20,
        )
        reference_evidence = self._lines_with(
            chunks,
            re.compile(r"(?i)\b(?:договор|приказ|распоряжение|сч[её]т|акт)\b"),
            limit=20,
        )

        return {
            "document_date": document_date,
            "document_number": document_number,
            "organization": organization,
            "department": department,
            "author": author,
            "addressee": addressee,
            "subject": subject,
            "summary": self._fact(
                value=self._summary(text),
                source="document",
                snippet=self._summary(text),
            ),
            "requested_action": self._fact(
                value=[item["snippet"] for item in requests] or "не указано",
                source="document",
                snippet=(requests[0]["snippet"] if requests else ""),
            ),
            "confirmed_result": self._fact(
                value=[item["snippet"] for item in results] or "не указано",
                source="document",
                snippet=(results[0]["snippet"] if results else ""),
            ),
            "employees_and_roles": {
                "value": employees or "не указано",
                "source": (
                    ", ".join(item["source"] for item in employee_evidence[:3])
                    if employee_evidence
                    else "не указано"
                ),
                "snippet": (
                    employee_evidence[0]["snippet"]
                    if employee_evidence
                    else "не указано"
                ),
                "evidence": employee_evidence,
            },
            "event_dates_and_periods": self._fact(
                value=dates or "не указано",
                source="document",
                snippet=(
                    next(
                        (
                            item["snippet"]
                            for item in self._lines_with(
                                chunks,
                                _DATE_RE,
                                limit=1,
                            )
                        ),
                        "",
                    )
                ),
            ),
            "vehicles": {
                "value": {
                    "vin": vins,
                    "plate_numbers": plates,
                    "inventory_numbers": inventory,
                }
                if (vins or plates or inventory)
                else "не указано",
                "source": (
                    ", ".join(
                        sorted({item["source"] for item in vehicle_evidence})
                    )
                    if vehicle_evidence
                    else "не указано"
                ),
                "snippet": (
                    vehicle_evidence[0]["snippet"]
                    if vehicle_evidence
                    else "не указано"
                ),
                "evidence": vehicle_evidence,
            },
            "counterparties": {
                "value": counterparties or "не указано",
                "source": (
                    ", ".join(
                        item["source"]
                        for item in counterparty_evidence[:3]
                    )
                    if counterparty_evidence
                    else "не указано"
                ),
                "snippet": (
                    counterparty_evidence[0]["snippet"]
                    if counterparty_evidence
                    else "не указано"
                ),
                "evidence": counterparty_evidence,
            },
            "goods_works_services": {
                "value": [item["snippet"] for item in goods_services]
                or "не указано",
                "source": (
                    ", ".join(item["source"] for item in goods_services[:3])
                    if goods_services
                    else "не указано"
                ),
                "snippet": (
                    goods_services[0]["snippet"]
                    if goods_services
                    else "не указано"
                ),
                "evidence": goods_services,
            },
            "amounts_and_vat": {
                "value": {
                    "amounts": amounts,
                    "vat_mentions": [
                        item["snippet"] for item in vat
                    ],
                }
                if (amounts or vat)
                else "не указано",
                "source": (
                    ", ".join(item["source"] for item in amount_evidence[:3])
                    if amount_evidence
                    else "не указано"
                ),
                "snippet": (
                    amount_evidence[0]["snippet"]
                    if amount_evidence
                    else "не указано"
                ),
                "evidence": amount_evidence + vat,
            },
            "related_documents": {
                "value": references or "не указано",
                "source": (
                    ", ".join(
                        item["source"]
                        for item in reference_evidence[:3]
                    )
                    if reference_evidence
                    else "не указано"
                ),
                "snippet": (
                    reference_evidence[0]["snippet"]
                    if reference_evidence
                    else "не указано"
                ),
                "evidence": reference_evidence,
            },
            "source_filename": self._fact(
                value=name,
                source="filename",
                snippet=name,
            ),
        }

    @staticmethod
    def _discrepancies(
        *,
        facts: dict[str, Any],
        name: str,
        document_year: str,
        chunks,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        discrepancies: list[dict[str, Any]] = []
        review: list[str] = []

        filename_years = set(_YEAR_RE.findall(name))
        if (
            document_year.isdigit()
            and filename_years
            and document_year not in filename_years
        ):
            discrepancies.append(
                {
                    "field": "year",
                    "filename": sorted(filename_years),
                    "document": document_year,
                    "reason": "Год в названии отличается от года записки.",
                }
            )

        date_candidates = ServiceMemoOrganizer._all_matches(
            chunks,
            _DOC_DATE_RE,
        )
        distinct_dates = sorted({item["value"] for item in date_candidates})
        if len(distinct_dates) > 1:
            discrepancies.append(
                {
                    "field": "document_date",
                    "values": date_candidates,
                    "reason": (
                        "В разных фрагментах найдены разные значения даты "
                        "самой служебной записки."
                    ),
                }
            )

        number_candidates = ServiceMemoOrganizer._all_matches(
            chunks,
            _NUMBER_RE,
        )
        distinct_numbers = sorted({item["value"] for item in number_candidates})
        if len(distinct_numbers) > 1:
            discrepancies.append(
                {
                    "field": "document_number",
                    "values": number_candidates,
                    "reason": (
                        "В разных фрагментах найдены разные номера записки."
                    ),
                }
            )

        amounts = facts["amounts_and_vat"]["value"]
        if isinstance(amounts, dict):
            unique = {
                (str(item.get("currency") or ""), str(item.get("value") or ""))
                for item in amounts.get("amounts", [])
            }
            if len(unique) > 1:
                discrepancies.append(
                    {
                        "field": "amounts",
                        "values": sorted(unique),
                        "evidence": facts["amounts_and_vat"].get("evidence") or [],
                        "reason": (
                            "Найдено несколько разных сумм; сохранены все "
                            "значения для проверки их назначения."
                        ),
                    }
                )
                review.append(
                    "В записке найдено несколько разных сумм; проверьте назначение каждой."
                )

        employees = facts["employees_and_roles"]["value"]
        if isinstance(employees, list) and len(set(employees)) > 1:
            review.append(
                "В записке несколько сотрудников; файл сохранён один раз, связи оставлены в карточке."
            )

        vehicles = facts["vehicles"]["value"]
        if isinstance(vehicles, dict):
            vehicle_count = sum(
                len(vehicles.get(key) or [])
                for key in ("vin", "plate_numbers", "inventory_numbers")
            )
            if vehicle_count > 1:
                review.append(
                    "В записке несколько единиц техники/номеров; файл сохранён один раз, все связи сохранены."
                )

        dates = facts["event_dates_and_periods"]["value"]
        if isinstance(dates, list) and len(set(dates)) > 3:
            review.append(
                "В записке много разных дат; дата записки и даты событий сохранены отдельно."
            )

        if (
            facts["requested_action"]["value"] != "не указано"
            and facts["confirmed_result"]["value"] == "не указано"
        ):
            review.append(
                "Найдена просьба/предложение, но подтверждённый результат "
                "в тексте не найден."
            )

        if document_year == "Год требует проверки":
            review.append("Не удалось надёжно определить год самой записки.")
        return discrepancies, review

    def _ensure_child(self, name: str, parent_id: str | None) -> dict[str, Any]:
        for folder in self.cloud_store.list_folders(parent_id=parent_id):
            if folder["name"].strip().casefold() == name.strip().casefold():
                return folder
        return self.cloud_store.create_folder(name, parent_id=parent_id)

    def _folder(
        self,
        *,
        item: dict[str, Any],
        year: str,
        topic: str,
        is_template: bool,
    ) -> tuple[str, str]:
        project_id = item.get("project_id") or PROJECT_ID
        project_name = "Dragon Tory" if project_id == PROJECT_ID else str(project_id)
        root = self._ensure_child(project_name, None)
        if is_template:
            templates = self._ensure_child("Шаблоны", root["id"])
            memos = self._ensure_child("Служебные записки", templates["id"])
            return memos["id"], f"{project_name} / Шаблоны / Служебные записки"

        documents = self._ensure_child("Документы", root["id"])
        year_folder = self._ensure_child(year, documents["id"])
        memos = self._ensure_child("Служебные записки", year_folder["id"])
        topic_folder = self._ensure_child(topic, memos["id"])
        folder_path = (
            f"{project_name} / Документы / {year} / "
            f"Служебные записки / {topic}"
        )
        return topic_folder["id"], folder_path

    def _duplicate_and_version(
        self,
        *,
        item: dict[str, Any],
        document_number: str,
        topic: str,
    ) -> tuple[str | None, str | None]:
        duplicates = self.cloud_store.documents_by_sha256(
            item["sha256"],
            exclude_document_id=item["id"],
        )
        duplicate_of = duplicates[0]["id"] if duplicates else None
        if duplicate_of:
            return duplicate_of, None

        current_stem = _normalized_stem(item["name"])
        possible: str | None = None
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT r.document_id, r.topic, r.facts_json, d.name, d.sha256
                FROM service_memo_records r
                JOIN documents d ON d.id = r.document_id
                WHERE r.document_id != ? AND d.trashed = 0
                ORDER BY r.processed_at DESC
                LIMIT 2000
                """,
                (item["id"],),
            ).fetchall()
        for row in rows:
            if row["sha256"] == item["sha256"]:
                continue
            other_facts = json.loads(row["facts_json"])
            other_number = (
                other_facts.get("document_number", {}).get("value")
                if isinstance(other_facts, dict)
                else None
            )
            same_number = (
                document_number
                and document_number != "не указано"
                and str(other_number) == document_number
            )
            same_stem = (
                current_stem
                and current_stem == _normalized_stem(row["name"])
            )
            if same_number or (same_stem and row["topic"] == topic):
                possible = str(row["document_id"])
                break
        return None, possible

    @staticmethod
    def _memory_content(
        *,
        item: dict[str, Any],
        year: str,
        topic: str,
        facts: dict[str, Any],
        discrepancies: list[dict[str, Any]],
        folder_path: str,
    ) -> str:
        compact = {
            key: value.get("value")
            for key, value in facts.items()
            if isinstance(value, dict) and "value" in value
        }
        return (
            "Служебная записка проекта.\n"
            f"Tory Document ID: {item['id']}.\n"
            f"Файл: {item['name']}.\n"
            f"Версия: {item['version']}.\n"
            f"SHA-256: {item['sha256']}.\n"
            f"Год записки: {year}.\n"
            f"Тема: {topic}.\n"
            f"Папка: {folder_path}.\n"
            "Основные факты: "
            + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            + "\nРасхождения: "
            + json.dumps(
                discrepancies,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )[:95_000]

    def process(self, document_id: str) -> dict[str, Any]:
        item = self.cloud_store.get(document_id)
        analysis = self.intelligence.get(document_id)
        if str(analysis.get("kind") or "").casefold() != "служебная записка":
            dna = self.smart.get_dna(document_id)
            if str(dna.get("kind") or "").casefold() != "служебная записка":
                raise ValueError(
                    "Правило сортировки применяется только к служебным запискам."
                )

        path, cleanup = self.cloud_store.materialize_plaintext(document_id)
        try:
            chunks, extraction_method, ocr_used = self.intelligence.extract(
                path,
                name=item["name"],
                content_type=item["content_type"],
            )
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)

        text = "\n\n".join(chunk.text for chunk in chunks)
        facts = self._facts(
            chunks=chunks,
            analysis=analysis,
            name=item["name"],
        )
        year, year_source, year_reason = self._document_year(
            chunks=chunks,
            name=item["name"],
        )
        topic, topic_reason, topic_scores = self._topic(text, item["name"])
        is_template = bool(_TEMPLATE_RE.search(item["name"] + "\n" + text[:20_000]))

        discrepancies, review = self._discrepancies(
            facts=facts,
            name=item["name"],
            document_year=year,
            chunks=chunks,
        )
        if year_source == "filename":
            review.append("Год определён по названию файла.")
        if topic == "Тема требует проверки":
            review.append("Тематическая папка требует проверки.")

        document_number = str(
            facts["document_number"].get("value") or ""
        )
        duplicate_of, possible_version_of = self._duplicate_and_version(
            item=item,
            document_number=document_number,
            topic=topic,
        )
        if duplicate_of:
            review.append(
                f"Файл полностью совпадает с {duplicate_of}; связан как копия."
            )
        elif possible_version_of:
            review.append(
                f"Возможная версия документа {possible_version_of}; сохранена отдельно."
            )

        folder_id, folder_path = self._folder(
            item=item,
            year=year,
            topic=topic,
            is_template=is_template,
        )

        tags = list(item.get("tags") or [])
        for tag in (
            "служебная записка",
            year if year.isdigit() else "",
            topic if "требует проверки" not in topic.casefold() else "",
            "шаблон" if is_template else "",
        ):
            if tag and tag not in tags:
                tags.append(tag)
        self.cloud_store.update_document(
            document_id,
            folder_id=folder_id,
            tags=tags[:50],
        )

        dna_update: dict[str, Any] = {
            "kind": "служебная записка",
            "origin": "Автосортировка служебных записок",
            "terms_summary": str(facts["summary"]["value"])[:5_000],
        }
        for source_key, target_key in (
            ("document_number", "document_number"),
            ("document_date", "document_date"),
            ("department", "department"),
            ("author", "employee_name"),
        ):
            value = facts[source_key]["value"]
            if value != "не указано":
                dna_update[target_key] = value
        self.smart.update_dna(
            document_id,
            dna_update,
            actor="tooru-memo-organizer",
        )

        memory_status = "skipped"
        memory_id = None
        if is_template:
            memory_status = "template"
        elif duplicate_of:
            memory_status = "duplicate"
        else:
            content = self._memory_content(
                item=item,
                year=year,
                topic=topic,
                facts=facts,
                discrepancies=discrepancies,
                folder_path=folder_path,
            )
            fingerprint = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()[:24]
            intake = self.memory_intake.ingest(
                MemoryCreate(
                    owner_id="local-user",
                    scope=MemoryScope.PROJECT,
                    project_id=item.get("project_id") or PROJECT_ID,
                    kind=MemoryKind.SUMMARY,
                    content=content,
                    key=f"service-memo:{fingerprint}",
                    source="tooru-service-memo-organizer",
                    source_ref=(
                        f"{document_id}:v{item['version']}:{item['sha256']}"
                    )[:500],
                    confidence=max(
                        0.72,
                        float(analysis.get("confidence") or 0.72),
                    ),
                    importance=0.78,
                    tags=[
                        "service-memo",
                        topic[:80],
                        year[:20],
                    ],
                ),
                reason=(
                    "Service memo facts and relations are stored in the "
                    "selected project memory after deterministic analysis."
                ),
            )
            memory_status = intake.decision.outcome.value
            if intake.memory is not None:
                memory_id = intake.memory.id

        record = {
            "document_id": document_id,
            "version": item["version"],
            "document_year": year,
            "year_source": year_source,
            "year_reason": year_reason,
            "topic": topic,
            "topic_reason": topic_reason,
            "topic_scores": topic_scores,
            "is_template": is_template,
            "folder_id": folder_id,
            "folder_path": folder_path,
            "duplicate_of": duplicate_of,
            "possible_version_of": possible_version_of,
            "facts": facts,
            "discrepancies": discrepancies,
            "review": review,
            "memory_status": memory_status,
            "memory_id": memory_id,
            "extraction_method": extraction_method,
            "ocr_used": bool(ocr_used),
            "processed_at": utc_now(),
        }

        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO service_memo_records (
                    document_id, version, document_year, year_source,
                    topic, topic_reason, is_template, folder_id, folder_path,
                    duplicate_of, possible_version_of, facts_json,
                    discrepancies_json, review_json, memory_status,
                    memory_id, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    item["version"],
                    year,
                    year_source,
                    topic,
                    topic_reason,
                    int(is_template),
                    folder_id,
                    folder_path,
                    duplicate_of,
                    possible_version_of,
                    json.dumps(facts, ensure_ascii=False),
                    json.dumps(discrepancies, ensure_ascii=False),
                    json.dumps(review, ensure_ascii=False),
                    memory_status,
                    memory_id,
                    record["processed_at"],
                ),
            )

        self.smart.record_provenance(
            document_id,
            "service_memo_processed",
            actor="tooru-memo-organizer",
            details={
                "year": year,
                "year_source": year_source,
                "topic": topic,
                "folder_path": folder_path,
                "is_template": is_template,
                "duplicate_of": duplicate_of,
                "possible_version_of": possible_version_of,
                "memory_status": memory_status,
                "memory_id": memory_id,
                "review_count": len(review),
            },
        )
        return record

    def get(self, document_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM service_memo_records
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(document_id)
        item = dict(row)
        item["is_template"] = bool(item["is_template"])
        item["facts"] = json.loads(item.pop("facts_json"))
        item["discrepancies"] = json.loads(item.pop("discrepancies_json"))
        item["review"] = json.loads(item.pop("review_json"))
        item["year_reason"] = (
            "Год определён по дате самой служебной записки."
            if item["year_source"] == "document_date"
            else (
                "Год определён по названию файла и требует визуальной проверки."
                if item["year_source"] == "filename"
                else "Год определить не удалось."
            )
        )
        return item
