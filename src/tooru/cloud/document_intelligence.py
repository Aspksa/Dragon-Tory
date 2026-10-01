from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pymupdf

from tooru.cloud.document_analysis_v2 import analyze_chunks
from tooru.cloud.intelligence import (
    LEGACY_CONVERTIBLE_SUFFIXES,
    ExtractedChunk,
    UnsupportedDocumentError,
    extract_document,
)
from tooru.cloud.memo_organizer import ensure_service_memo_schema
from tooru.cloud.store import CloudStore
from tooru.observability.context import current_observation, observation_context

_DATE_PATTERNS = (
    re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}\b"),
    re.compile(r"\b(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])\b"),
)
_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)
_COUNTERPARTY_RE = re.compile(
    r"(?im)^\s*(?:контрагент|поставщик|исполнитель|заказчик|"
    r"продавец|покупатель)\s*[:\-]\s*([^\n\r]{3,180})"
)
_EMPLOYEE_RE = re.compile(
    r"(?im)^\s*(?:сотрудник|работник|фио)\s*[:\-]\s*([^\n\r]{3,180})"
)
_DEPARTMENT_RE = re.compile(
    r"(?im)^\s*(?:подразделение|отдел|служба)\s*[:\-]\s*([^\n\r]{2,180})"
)
_WORK_HOURS_RE = re.compile(
    r"(?i)(?:количество\s+часов|часов|продолжительность)\s*[:\-]?\s*"
    r"(\d{1,2}(?:[.,]\d{1,2})?)"
)
_WORK_DATE_RE = re.compile(
    r"(?i)(?:дата\s+работы|выходной\s+день|работа\s+в\s+выходной\s+день)"
    r"[^\d]{0,30}((?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}|(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01]))"
)
_AMOUNT_RE = re.compile(
    r"(?:(?P<currency1>€|EUR|USD|\$|GBP|£|RUB|₽)\s*)?"
    r"(?P<amount>\d+(?:[ .]\d{3})*(?:[,.]\d{1,2})?)"
    r"(?:\s*(?P<currency2>€|EUR|USD|\$|GBP|£|RUB|₽))?",
    re.IGNORECASE,
)
_REF_RE = re.compile(
    r"\b(?:договор|приказ|распоряжение|оферт[аы]?|contract|invoice|"
    r"сч[её]т|order|заказ|полис|policy)"
    r"\s*(?:№|#|no\.?|number)?\s*[:\-]?\s*([A-ZА-Я0-9][A-ZА-Я0-9._/-]{2,})",
    re.IGNORECASE,
)
_DEADLINE_WORDS = (
    "действует до",
    "срок до",
    "оплатить до",
    "оплата до",
    "до ",
    "истекает",
    "срок действия",
    "valid until",
    "expires",
    "due date",
    "pay by",
)
_KIND_RULES = {
    "договор": (
        "договор",
        "стороны договора",
        "предмет договора",
        "contract",
        "agreement",
    ),
    "счёт-оферта": (
        "счет-оферта",
        "счёт-оферта",
        "счет оферта",
        "счёт оферта",
        "invoice-offer",
        "invoice",
        "payment due",
        "счет на оплату",
        "счёт на оплату",
        "оферта",
        "условия оплаты",
        "условия поставки",
        "акцепт",
    ),
    "служебная записка": (
        "служебная записка",
        "докладная записка",
        "работа в выходной день",
        "memo",
        "memorandum",
        "кому:",
        "от кого:",
    ),
    "приказ": (
        "приказ №",
        "приказ от",
        "приказываю",
        "приказываю:",
        "order no",
    ),
    "распоряжение": (
        "распоряжение №",
        "распоряжение от",
        "распоряжаюсь",
        "распоряжаюсь:",
        "directive",
    ),
    "чек": ("кассовый чек", "receipt", "итого", "total"),
    "страхование": (
        "страхов",
        "полис",
        "insurance",
        "policyholder",
    ),
    "диагностика": (
        "диагност",
        "ошибка",
        "dtc",
        "fault code",
        "service report",
    ),
    "акт": ("акт выполненных", "акт при", "acceptance act"),
    "гарантия": ("гарант", "warranty"),
    "инструкция": ("руководство", "инструкция", "manual", "user guide"),
    "резюме": ("curriculum vitae", "resume", "резюме"),
}
_CURRENCY_MAP = {
    "€": "EUR",
    "eur": "EUR",
    "$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "₽": "RUB",
    "rub": "RUB",
}


class OCRUnavailableError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _unique(values: list[str], *, limit: int = 100) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _amount_value(raw: str) -> float | None:
    cleaned = raw.replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


class DocumentIntelligence:
    def __init__(self, cloud_store: CloudStore, *, observability=None) -> None:
        self.cloud_store = cloud_store
        self.db_path = cloud_store.db_path
        self.observability = observability

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
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_intelligence (
                    document_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    summary_local TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    deadlines_json TEXT NOT NULL,
                    suggested_tags_json TEXT NOT NULL,
                    suggested_relations_json TEXT NOT NULL,
                    structure_json TEXT NOT NULL DEFAULT '{}',
                    checks_json TEXT NOT NULL DEFAULT '{}',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    extraction_method TEXT NOT NULL,
                    ocr_used INTEGER NOT NULL DEFAULT 0,
                    analyzed_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, version)
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_intelligence_kind
                ON document_intelligence(kind, analyzed_at DESC)
                """
            )
            self._migrate_v2_schema(db)
            ensure_service_memo_schema(db)

    @staticmethod
    def _migrate_v2_schema(db: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(document_intelligence)"
            ).fetchall()
        }
        migrations = {
            "structure_json": "TEXT NOT NULL DEFAULT '{}'",
            "checks_json": "TEXT NOT NULL DEFAULT '{}'",
            "evidence_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column, definition in migrations.items():
            if column not in existing:
                db.execute(
                    f"ALTER TABLE document_intelligence "
                    f"ADD COLUMN {column} {definition}"
                )

    @classmethod
    def _aggregate_entities(
        cls,
        chunks: list[ExtractedChunk],
    ) -> dict[str, Any]:
        merged: dict[str, list[Any]] = {}
        seen: dict[str, set[str]] = {}
        for chunk in chunks:
            local = cls._entities(chunk.text)
            for key, values in local.items():
                bucket = merged.setdefault(key, [])
                keys = seen.setdefault(key, set())
                for value in values:
                    marker = json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if marker in keys:
                        continue
                    keys.add(marker)
                    bucket.append(value)
                    if len(bucket) >= 200:
                        break
        return merged

    @classmethod
    def _aggregate_deadlines(
        cls,
        chunks: list[ExtractedChunk],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chunk_no, chunk in enumerate(chunks, start=1):
            for item in cls._deadlines(chunk.text):
                key = (
                    str(item.get("date") or "")
                    + "|"
                    + str(item.get("context") or "").casefold()
                )
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        **item,
                        "chunk_no": chunk_no,
                        "label": chunk.label,
                        "page": chunk.page,
                        "table": chunk.table,
                        "cell": chunk.cell,
                    }
                )
                if len(result) >= 200:
                    return result
        return result

    @staticmethod
    def _find_libreoffice() -> str | None:
        for command in ("soffice", "libreoffice"):
            found = shutil.which(command)
            if found:
                return found
        candidates = (
            Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
            Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def converter_status(self) -> dict[str, Any]:
        executable = self._find_libreoffice()
        return {
            "available": bool(executable),
            "engine": "LibreOffice" if executable else None,
            "executable": executable,
            "legacy_formats": ["DOC", "DOCM", "PPT", "PPTM", "WPS"],
        }

    @staticmethod
    def _find_tesseract() -> str | None:
        found = shutil.which("tesseract")
        if found:
            return found
        candidates = (
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def ocr_status(self) -> dict[str, Any]:
        executable = self._find_tesseract()
        languages: list[str] = []
        if executable:
            try:
                result = subprocess.run(
                    [executable, "--list-langs"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=False,
                )
                languages = [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip() and "List of available" not in line
                ]
            except (OSError, subprocess.SubprocessError):
                languages = []
        preferred = []
        if "rus" in languages:
            preferred.append("rus")
        if "eng" in languages:
            preferred.append("eng")
        return {
            "available": bool(executable),
            "engine": "Tesseract OCR" if executable else None,
            "executable": executable,
            "languages": languages,
            "preferred_language": "+".join(preferred) or None,
            "local_only": True,
            "external_ai_used": False,
        }

    def _ocr_file(
        self,
        path: Path,
        *,
        label: str,
    ) -> list[ExtractedChunk]:
        status = self.ocr_status()
        executable = status["executable"]
        if not executable:
            raise OCRUnavailableError(
                "Локальный OCR не найден. Установите Tesseract OCR; "
                "скан не будет отправлен во внешний ИИ автоматически."
            )
        language = status["preferred_language"]
        command = [str(executable), str(path), "stdout"]
        if language:
            command.extend(["-l", language])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise OCRUnavailableError(
                "Tesseract не смог распознать изображение: "
                + (result.stderr.strip() or "неизвестная ошибка")
            )
        text = result.stdout.strip()
        if not text:
            return []
        return [
            ExtractedChunk(
                label=label,
                text=text[:20_000],
                page=None,
            )
        ]

    def _ocr_pdf(
        self,
        path: Path,
    ) -> list[ExtractedChunk]:
        status = self.ocr_status()
        if not status["available"]:
            raise OCRUnavailableError(
                "PDF выглядит как скан, но локальный Tesseract OCR не найден."
            )
        chunks: list[ExtractedChunk] = []
        document = pymupdf.open(str(path))
        try:
            with tempfile.TemporaryDirectory(
                dir=str(self.cloud_store.incoming_dir)
            ) as temp_dir:
                root = Path(temp_dir)
                matrix = pymupdf.Matrix(2.0, 2.0)
                for page_no, page in enumerate(document, start=1):
                    image_path = root / f"page-{page_no}.png"
                    pixmap = page.get_pixmap(
                        matrix=matrix,
                        alpha=False,
                    )
                    pixmap.save(str(image_path))
                    for chunk in self._ocr_file(
                        image_path,
                        label=f"OCR · страница {page_no}",
                    ):
                        chunk.page = page_no
                        chunks.append(chunk)
        finally:
            document.close()
        return chunks

    def _convert_legacy(
        self,
        path: Path,
        *,
        name: str,
    ) -> tuple[list[ExtractedChunk], str]:
        executable = self._find_libreoffice()
        if not executable:
            raise UnsupportedDocumentError(
                "Для старого формата "
                + Path(name).suffix.upper()
                + " нужен LibreOffice. Dragon Tory может установить "
                "его через Windows bootstrap или использовать DOCX/PPTX."
            )
        suffix = Path(name).suffix.lower()
        target = "pptx" if suffix in {".ppt", ".pptm"} else "docx"
        with tempfile.TemporaryDirectory(
            dir=str(self.cloud_store.incoming_dir)
        ) as temp_dir:
            root = Path(temp_dir)
            source = root / ("source" + suffix)
            shutil.copy2(path, source)
            result = subprocess.run(
                [
                    str(executable),
                    "--headless",
                    "--convert-to",
                    target,
                    "--outdir",
                    str(root),
                    str(source),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )
            converted = root / f"source.{target}"
            if result.returncode != 0 or not converted.is_file():
                raise UnsupportedDocumentError(
                    "LibreOffice не смог преобразовать старый документ: "
                    + (result.stderr.strip() or result.stdout.strip() or "ошибка")
                )
            chunks = extract_document(
                converted,
                name=converted.name,
                content_type="application/octet-stream",
            )
            return chunks, f"libreoffice_{target}"

    def extract(
        self,
        path: Path,
        *,
        name: str,
        content_type: str,
    ) -> tuple[list[ExtractedChunk], str, bool]:
        suffix = Path(name).suffix.lower()
        try:
            chunks = extract_document(
                path,
                name=name,
                content_type=content_type,
            )
            if chunks:
                return chunks, "native_text", False
        except UnsupportedDocumentError:
            chunks = []

        if suffix in LEGACY_CONVERTIBLE_SUFFIXES:
            converted, method = self._convert_legacy(
                path,
                name=name,
            )
            if converted:
                return converted, method, False
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
            return self._ocr_file(path, label="OCR · изображение"), "ocr_image", True
        if suffix == ".pdf" or content_type == "application/pdf":
            ocr_chunks = self._ocr_pdf(path)
            if ocr_chunks:
                return ocr_chunks, "ocr_pdf_pages", True
        if chunks:
            return chunks, "native_text", False
        raise UnsupportedDocumentError(
            "Из документа не удалось получить текст. Для сканов нужен "
            "локальный Tesseract OCR с русским/английским языковым пакетом; "
            "для старых DOC/PPT нужен LibreOffice."
        )

    @staticmethod
    def _classify(name: str, text: str) -> tuple[str, float]:
        haystack = (name + "\n" + text[:80_000]).casefold()
        scores = {
            kind: sum(haystack.count(keyword.casefold()) for keyword in keywords)
            for kind, keywords in _KIND_RULES.items()
        }
        best_kind, best_score = max(scores.items(), key=lambda item: item[1])
        if best_score < 1:
            return "документ", 0.35
        confidence = min(0.98, 0.55 + best_score * 0.08)
        return best_kind, confidence

    @staticmethod
    def _entities(text: str) -> dict[str, Any]:
        vins = _unique(_VIN_RE.findall(text), limit=30)
        emails = _unique(_EMAIL_RE.findall(text), limit=50)
        urls = _unique(_URL_RE.findall(text), limit=50)
        ibans = _unique(_IBAN_RE.findall(text), limit=30)
        references = _unique(
            [match.group(1) for match in _REF_RE.finditer(text)],
            limit=50,
        )
        counterparties = _unique(
            [match.group(1).strip(" .;") for match in _COUNTERPARTY_RE.finditer(text)],
            limit=30,
        )
        employees = _unique(
            [match.group(1).strip(" .;") for match in _EMPLOYEE_RE.finditer(text)],
            limit=30,
        )
        departments = _unique(
            [match.group(1).strip(" .;") for match in _DEPARTMENT_RE.finditer(text)],
            limit=30,
        )
        work_dates = _unique(
            [match.group(1) for match in _WORK_DATE_RE.finditer(text)],
            limit=30,
        )
        work_hours = []
        for match in _WORK_HOURS_RE.finditer(text):
            try:
                value = float(match.group(1).replace(",", "."))
            except ValueError:
                continue
            if 0 <= value <= 24:
                work_hours.append(value)
            if len(work_hours) >= 30:
                break
        dates: list[str] = []
        for pattern in _DATE_PATTERNS:
            dates.extend(match.group(0) for match in pattern.finditer(text))
        dates = _unique(dates, limit=100)

        amounts: list[dict[str, Any]] = []
        for match in _AMOUNT_RE.finditer(text):
            currency_raw = match.group("currency1") or match.group("currency2")
            if not currency_raw:
                continue
            value = _amount_value(match.group("amount"))
            if value is None:
                continue
            currency = _CURRENCY_MAP.get(
                currency_raw.casefold(),
                currency_raw.upper(),
            )
            amounts.append(
                {
                    "raw": match.group(0).strip(),
                    "value": value,
                    "currency": currency,
                }
            )
            if len(amounts) >= 100:
                break
        return {
            "vin": vins,
            "emails": emails,
            "urls": urls,
            "iban": ibans,
            "references": references,
            "counterparties": counterparties,
            "employees": employees,
            "departments": departments,
            "work_dates": work_dates,
            "work_hours": work_hours,
            "dates": dates,
            "amounts": amounts,
        }

    @staticmethod
    def _deadlines(text: str) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        lower = text.casefold()
        seen: set[str] = set()
        for pattern in _DATE_PATTERNS:
            for match in pattern.finditer(text):
                start = max(0, match.start() - 100)
                end = min(len(text), match.end() + 100)
                context = text[start:end].replace("\n", " ").strip()
                context_lower = lower[start:end]
                if not any(word in context_lower for word in _DEADLINE_WORDS):
                    continue
                key = match.group(0) + context.casefold()
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "date": match.group(0),
                        "context": context[:500],
                    }
                )
                if len(result) >= 50:
                    return result
        return result

    @staticmethod
    def _suggested_tags(
        kind: str,
        entities: dict[str, Any],
        text: str,
    ) -> list[str]:
        tags = [kind]
        years = re.findall(r"\b20\d{2}\b", text)
        tags.extend(Counter(years).most_common(3)[i][0] for i in range(min(3, len(Counter(years)))))
        tags.extend(entities["vin"][:3])
        tags.extend(item["currency"] for item in entities["amounts"][:5])
        return _unique(tags, limit=20)

    def _relation_suggestions(
        self,
        document_id: str,
        entities: dict[str, Any],
        tags: list[str],
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        source_values = {
            *(value.casefold() for value in entities["vin"]),
            *(value.casefold() for value in entities["references"]),
            *(value.casefold() for value in entities["emails"]),
        }
        source_tags = {tag.casefold() for tag in tags}
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT i.document_id, i.entities_json, i.suggested_tags_json,
                       d.name, d.project_id
                FROM document_intelligence i
                JOIN documents d ON d.id = i.document_id
                WHERE i.document_id != ?
                  AND i.version = d.version
                  AND d.trashed = 0
                """,
                (document_id,),
            ).fetchall()
            current = db.execute(
                "SELECT project_id FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        suggestions: list[dict[str, Any]] = []
        for row in rows:
            other_entities = json.loads(row["entities_json"])
            other_tags = set(json.loads(row["suggested_tags_json"]))
            other_values = {
                *(value.casefold() for value in other_entities.get("vin", [])),
                *(value.casefold() for value in other_entities.get("references", [])),
                *(value.casefold() for value in other_entities.get("emails", [])),
            }
            shared_entities = sorted(source_values & other_values)
            shared_tags = sorted(source_tags & {tag.casefold() for tag in other_tags})
            score = len(shared_entities) * 8 + len(shared_tags) * 2
            same_project = bool(
                current
                and current["project_id"]
                and current["project_id"] == row["project_id"]
            )
            if same_project:
                score += 2
            if score < 2:
                continue
            suggestions.append(
                {
                    "document_id": row["document_id"],
                    "name": row["name"],
                    "score": score,
                    "shared_entities": shared_entities,
                    "shared_tags": shared_tags,
                    "same_project": same_project,
                }
            )
        suggestions.sort(key=lambda item: item["score"], reverse=True)
        return suggestions[:limit]

    def analyze(self, document_id: str) -> dict[str, Any]:
        context = current_observation()
        module = context.module or "drive"
        with observation_context(
            trace_id=context.trace_id,
            module=module,
            source_type="document",
            source_id=document_id,
            document_id=document_id,
        ):
            span_id = None
            if self.observability is not None and context.trace_id is None:
                self.observability.event(
                    category="source",
                    stage="source",
                    operation="document_selected",
                    status="success",
                    module=module,
                    source_type="document",
                    source_id=document_id,
                    document_id=document_id,
                    message="Документ передан в локальный анализ.",
                )
            if self.observability is not None:
                span_id = self.observability.start_span(
                    category="analysis",
                    stage="analysis",
                    operation="local_document_analysis",
                    module=module,
                    source_type="document",
                    source_id=document_id,
                    document_id=document_id,
                    message="Локальный анализ документа.",
                )

            try:
                item = self.cloud_store.get(document_id)
                path, cleanup = self.cloud_store.materialize_plaintext(document_id)
                try:
                    chunks, method, ocr_used = self.extract(
                        path,
                        name=item["name"],
                        content_type=item["content_type"],
                    )
                finally:
                    if cleanup is not None:
                        cleanup.unlink(missing_ok=True)

                v2 = analyze_chunks(chunks)
                analysis_text = str(v2["representative_text"])
                kind, confidence = self._classify(item["name"], analysis_text)
                entities = self._aggregate_entities(chunks)
                deadlines = self._aggregate_deadlines(chunks)
                tags = self._suggested_tags(kind, entities, analysis_text)
                relations = self._relation_suggestions(
                    document_id,
                    entities,
                    tags,
                )
                summary_local = " ".join(
                    line.strip()
                    for line in analysis_text.splitlines()
                    if line.strip()
                )[:900]
                analyzed_at = utc_now()

                with self._connect() as db:
                    db.execute(
                        """
                        INSERT OR REPLACE INTO document_intelligence (
                            document_id, version, kind, confidence, summary_local,
                            entities_json, deadlines_json, suggested_tags_json,
                            suggested_relations_json, structure_json, checks_json,
                            evidence_json, extraction_method, ocr_used, analyzed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            item["version"],
                            kind,
                            confidence,
                            summary_local,
                            json.dumps(entities, ensure_ascii=False),
                            json.dumps(deadlines, ensure_ascii=False),
                            json.dumps(tags, ensure_ascii=False),
                            json.dumps(relations, ensure_ascii=False),
                            json.dumps(v2["structure"], ensure_ascii=False),
                            json.dumps(v2["checks"], ensure_ascii=False),
                            json.dumps(v2["evidence"], ensure_ascii=False),
                            method,
                            int(ocr_used),
                            analyzed_at,
                        ),
                    )
                result = self.get(document_id)
            except Exception as exc:
                if span_id is not None:
                    self.observability.finish_span(
                        span_id,
                        status="error",
                        message=f"{type(exc).__name__}: {str(exc)[:300]}",
                    )
                raise

            if span_id is not None:
                self.observability.finish_span(
                    span_id,
                    status="success",
                    message=f"Локальный анализ: {kind}.",
                    details={
                        "kind": kind,
                        "confidence": confidence,
                        "extraction_method": method,
                        "ocr_used": bool(ocr_used),
                        "version": item["version"],
                    },
                )
            return result

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["ocr_used"] = bool(item["ocr_used"])
        for key in (
            "entities_json",
            "deadlines_json",
            "suggested_tags_json",
            "suggested_relations_json",
            "structure_json",
            "checks_json",
            "evidence_json",
        ):
            item[key.removesuffix("_json")] = json.loads(item.pop(key))
        return item

    def get(
        self,
        document_id: str,
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        document = self.cloud_store.get(
            document_id,
            include_trashed=True,
        )
        target = int(version or document["version"])
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM document_intelligence
                WHERE document_id = ? AND version = ?
                """,
                (document_id, target),
            ).fetchone()
        if row is None:
            raise KeyError(f"{document_id}:{target}")
        result = self._decode_row(row)
        result["current_version"] = int(document["version"]) == target
        return result

    DOCUMENT_MODULES: ClassVar[dict[str, dict[str, Any]]] = {
        "contracts": {
            "title": "Договоры",
            "icon": "📑",
            "kinds": {"договор"},
            "ai_focus": [
                "контрагент и реквизиты",
                "номер и дата договора",
                "сумма и валюта",
                "срок действия и продление",
                "обязательства, ответственность и изменения версий",
            ],
        },
        "invoice_offers": {
            "title": "Счета-оферты",
            "icon": "🧾",
            "kinds": {"счёт-оферта", "счёт", "оферта"},
            "ai_focus": [
                "номер, дата и контрагент",
                "позиции, сумма, НДС и валюта",
                "срок и условия оплаты",
                "краткие договорные условия",
                "условия поставки, акцепта и гарантии",
            ],
        },
        "memos": {
            "title": "Служебные записки",
            "icon": "📝",
            "kinds": {"служебная записка"},
            "ai_focus": [
                "автор, адресат и подразделение",
                "тема и поручение",
                "работа в выходной день и часы",
                "срок исполнения",
                "данные для табеля",
            ],
        },
        "orders": {
            "title": "Приказы",
            "icon": "📜",
            "kinds": {"приказ"},
            "ai_focus": [
                "структура и стиль приказов предприятия",
                "основание и распорядительная часть",
                "ответственные лица и сроки",
                "нумерация пунктов",
                "контроль исполнения",
            ],
        },
        "directives": {
            "title": "Распоряжения",
            "icon": "📋",
            "kinds": {"распоряжение"},
            "ai_focus": [
                "структура и стиль распоряжений предприятия",
                "основание и задача",
                "исполнители и сроки",
                "порядок действий",
                "контроль исполнения",
            ],
        },
    }

    def modules_overview(self) -> list[dict[str, Any]]:
        result = []
        for module_id, config in self.DOCUMENT_MODULES.items():
            result.append(
                {
                    "id": module_id,
                    "title": config["title"],
                    "icon": config["icon"],
                    "count": len(self.module_items(module_id, limit=10_000)),
                    "ai_focus": config["ai_focus"],
                }
            )
        return result

    def module_items(
        self,
        module_id: str,
        *,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        config = self.DOCUMENT_MODULES.get(module_id)
        if config is None:
            raise KeyError(module_id)
        kinds = {value.casefold() for value in config["kinds"]}
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT d.*, dna.kind AS dna_kind,
                       dna.counterparty,
                       dna.counterparty_id,
                       dna.document_number,
                       dna.document_date,
                       dna.amount_value,
                       dna.amount_currency,
                       dna.terms_summary,
                       dna.document_subtype,
                       dna.employee_name,
                       dna.department,
                       dna.work_date,
                       dna.work_hours,
                       dna.work_reason,
                       i.kind AS intelligence_kind,
                       i.confidence AS intelligence_confidence,
                       i.deadlines_json,
                       i.entities_json,
                       i.analyzed_at,
                       memo.document_year AS memo_year,
                       memo.year_source AS memo_year_source,
                       memo.topic AS memo_topic,
                       memo.topic_reason AS memo_topic_reason,
                       memo.folder_path AS memo_folder_path,
                       memo.is_template AS memo_is_template,
                       memo.duplicate_of AS memo_duplicate_of,
                       memo.possible_version_of AS memo_possible_version_of,
                       memo.review_json AS memo_review_json,
                       memo.memory_status AS memo_memory_status
                FROM documents d
                LEFT JOIN document_dna dna ON dna.document_id = d.id
                LEFT JOIN document_intelligence i
                  ON i.document_id = d.id AND i.version = d.version
                LEFT JOIN service_memo_records memo
                  ON memo.document_id = d.id AND memo.version = d.version
                WHERE d.trashed = 0
                ORDER BY d.updated_at DESC
                """
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            effective_kind = (
                str(row["dna_kind"] or row["intelligence_kind"] or "")
                .strip()
                .casefold()
            )
            if effective_kind not in kinds:
                continue
            document = self.cloud_store._row(row)
            deadlines = (
                json.loads(row["deadlines_json"])
                if row["deadlines_json"]
                else []
            )
            entities = (
                json.loads(row["entities_json"])
                if row["entities_json"]
                else {}
            )
            document.update(
                {
                    "module_id": module_id,
                    "module_title": config["title"],
                    "effective_kind": effective_kind,
                    "intelligence_confidence": row[
                        "intelligence_confidence"
                    ],
                    "deadlines": deadlines,
                    "entities": entities,
                    "analyzed_at": row["analyzed_at"],
                    "counterparty": row["counterparty"] or "",
                    "counterparty_id": row["counterparty_id"],
                    "document_number": row["document_number"] or "",
                    "document_date": row["document_date"],
                    "amount_value": row["amount_value"],
                    "amount_currency": row["amount_currency"] or "",
                    "terms_summary": row["terms_summary"] or "",
                    "document_subtype": row["document_subtype"] or "",
                    "employee_name": row["employee_name"] or "",
                    "department": row["department"] or "",
                    "work_date": row["work_date"],
                    "work_hours": row["work_hours"],
                    "work_reason": row["work_reason"] or "",
                    "memo_year": row["memo_year"],
                    "memo_year_source": row["memo_year_source"],
                    "memo_topic": row["memo_topic"],
                    "memo_topic_reason": row["memo_topic_reason"],
                    "memo_folder_path": row["memo_folder_path"],
                    "memo_is_template": bool(row["memo_is_template"] or 0),
                    "memo_duplicate_of": row["memo_duplicate_of"],
                    "memo_possible_version_of": row["memo_possible_version_of"],
                    "memo_review": (
                        json.loads(row["memo_review_json"])
                        if row["memo_review_json"]
                        else []
                    ),
                    "memo_memory_status": row["memo_memory_status"] or "",
                }
            )
            items.append(document)
            if len(items) >= limit:
                break
        return items

    def module_profile(self, module_id: str) -> dict[str, Any]:
        config = self.DOCUMENT_MODULES.get(module_id)
        if config is None:
            raise KeyError(module_id)
        items = self.module_items(module_id, limit=10_000)
        with_deadlines = sum(bool(item["deadlines"]) for item in items)
        analyzed = sum(item["analyzed_at"] is not None for item in items)
        counterparties: list[dict[str, Any]] = []
        if module_id == "contracts":
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                name = (item.get("counterparty") or "Контрагент не указан").strip()
                grouped.setdefault(name, []).append(item)
            counterparties = [
                {
                    "name": name,
                    "contracts": len(group_items),
                    "document_ids": [item["id"] for item in group_items],
                }
                for name, group_items in sorted(
                    grouped.items(),
                    key=lambda pair: pair[0].casefold(),
                )
            ]
        return {
            "id": module_id,
            "title": config["title"],
            "icon": config["icon"],
            "ai_focus": config["ai_focus"],
            "count": len(items),
            "analyzed": analyzed,
            "with_deadlines": with_deadlines,
            "needs_analysis": len(items) - analyzed,
            "counterparties": counterparties,
            "items": items,
        }

    def smart_collections(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            kinds = db.execute(
                """
                SELECT i.kind, COUNT(*) AS count
                FROM document_intelligence i
                JOIN documents d ON d.id = i.document_id
                WHERE i.version = d.version AND d.trashed = 0
                GROUP BY i.kind
                ORDER BY count DESC, i.kind
                """
            ).fetchall()
            deadlines = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM document_intelligence i
                JOIN documents d ON d.id = i.document_id
                WHERE i.version = d.version
                  AND d.trashed = 0
                  AND i.deadlines_json != '[]'
                """
            ).fetchone()
            unanalyzed = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM documents d
                LEFT JOIN document_intelligence i
                  ON i.document_id = d.id AND i.version = d.version
                WHERE d.trashed = 0 AND i.document_id IS NULL
                """
            ).fetchone()
        result = [
            {
                "id": "kind:" + row["kind"],
                "title": row["kind"].capitalize(),
                "type": "kind",
                "value": row["kind"],
                "count": int(row["count"]),
            }
            for row in kinds
        ]
        result.append(
            {
                "id": "attention:deadlines",
                "title": "Есть сроки",
                "type": "attention",
                "value": "deadlines",
                "count": int(deadlines["count"] or 0),
            }
        )
        result.append(
            {
                "id": "attention:unanalyzed",
                "title": "Требует анализа",
                "type": "attention",
                "value": "unanalyzed",
                "count": int(unanalyzed["count"] or 0),
            }
        )
        return result

    def collection_items(
        self,
        collection_id: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            if collection_id.startswith("kind:"):
                kind = collection_id.split(":", 1)[1]
                rows = db.execute(
                    """
                    SELECT d.*
                    FROM documents d
                    JOIN document_intelligence i
                      ON i.document_id = d.id AND i.version = d.version
                    WHERE d.trashed = 0 AND i.kind = ?
                    ORDER BY d.updated_at DESC
                    LIMIT ?
                    """,
                    (kind, limit),
                ).fetchall()
            elif collection_id == "attention:deadlines":
                rows = db.execute(
                    """
                    SELECT d.*
                    FROM documents d
                    JOIN document_intelligence i
                      ON i.document_id = d.id AND i.version = d.version
                    WHERE d.trashed = 0 AND i.deadlines_json != '[]'
                    ORDER BY d.updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            elif collection_id == "attention:unanalyzed":
                rows = db.execute(
                    """
                    SELECT d.*
                    FROM documents d
                    LEFT JOIN document_intelligence i
                      ON i.document_id = d.id AND i.version = d.version
                    WHERE d.trashed = 0 AND i.document_id IS NULL
                    ORDER BY d.updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                raise KeyError(collection_id)
        return [self.cloud_store._row(row) for row in rows]

    def smart_search(
        self,
        query: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        cleaned = query.strip()
        if not cleaned:
            return []
        lower = cleaned.casefold()
        year_match = re.search(r"\b(20\d{2})\b", cleaned)
        requested_year = year_match.group(1) if year_match else None
        amount_match = re.search(
            r"(?:>|больше|более|свыше)\s*(?:€|eur|usd|\$|£|gbp|₽|rub)?\s*"
            r"(\d+(?:[.,]\d+)?)",
            lower,
        )
        minimum_amount = (
            _amount_value(amount_match.group(1))
            if amount_match
            else None
        )
        requested_currency = None
        for token, currency in (
            ("€", "EUR"),
            ("eur", "EUR"),
            ("$", "USD"),
            ("usd", "USD"),
            ("£", "GBP"),
            ("gbp", "GBP"),
            ("₽", "RUB"),
            ("rub", "RUB"),
        ):
            if token in lower:
                requested_currency = currency
                break
        requested_kind = None
        for kind in _KIND_RULES:
            if kind.casefold() in lower:
                requested_kind = kind
                break

        stop = {
            "найди",
            "найти",
            "все",
            "документы",
            "документ",
            "где",
            "есть",
            "за",
            "год",
            "больше",
            "более",
            "свыше",
            "eur",
            "usd",
            "gbp",
            "rub",
        }
        term_source = lower
        if requested_year:
            term_source = term_source.replace(requested_year, " ")
        if amount_match:
            term_source = term_source.replace(amount_match.group(0), " ")
        term_source = (
            term_source.replace("€", " ")
            .replace("$", " ")
            .replace("£", " ")
            .replace("₽", " ")
        )
        terms = {
            token.strip(".,:;!?()[]{}").casefold()
            for token in term_source.split()
            if len(token.strip(".,:;!?()[]{}")) >= 2
        }
        terms = {
            term
            for term in terms
            if term not in stop
            and not re.fullmatch(r"\d+(?:[.,]\d+)?", term)
        }

        with self._connect() as db:
            rows = db.execute(
                """
                SELECT i.*, d.name, d.tags_json, d.project_id,
                       d.confidentiality, d.favorite, d.updated_at
                FROM document_intelligence i
                JOIN documents d ON d.id = i.document_id
                WHERE i.version = d.version AND d.trashed = 0
                """
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            item = self._decode_row(row)
            if requested_kind and item["kind"] != requested_kind:
                continue
            if requested_year:
                year_haystack = json.dumps(
                    {
                        "entities": item["entities"],
                        "tags": item["suggested_tags"],
                        "summary": item["summary_local"],
                    },
                    ensure_ascii=False,
                )
                if requested_year not in year_haystack:
                    continue
            if minimum_amount is not None:
                matching_amounts = [
                    amount
                    for amount in item["entities"].get("amounts", [])
                    if float(amount["value"]) > minimum_amount
                    and (
                        requested_currency is None
                        or amount["currency"] == requested_currency
                    )
                ]
                if not matching_amounts:
                    continue
            else:
                matching_amounts = item["entities"].get("amounts", [])

            haystack = " ".join(
                [
                    row["name"],
                    item["kind"],
                    item["summary_local"],
                    " ".join(item["suggested_tags"]),
                    " ".join(item["entities"].get("vin", [])),
                    " ".join(item["entities"].get("references", [])),
                    " ".join(item["entities"].get("emails", [])),
                    row["project_id"] or "",
                ]
            ).casefold()
            score = sum(haystack.count(term) for term in terms)
            if terms and score < 1:
                continue
            if requested_kind:
                score += 4
            if requested_year:
                score += 2
            if minimum_amount is not None:
                score += 4
            if row["favorite"]:
                score += 1
            results.append(
                {
                    "document_id": item["document_id"],
                    "name": row["name"],
                    "version": item["version"],
                    "kind": item["kind"],
                    "score": score,
                    "project_id": row["project_id"],
                    "confidentiality": row["confidentiality"],
                    "suggested_tags": item["suggested_tags"],
                    "deadlines": item["deadlines"],
                    "amounts": matching_amounts[:10],
                    "summary": item["summary_local"],
                    "updated_at": row["updated_at"],
                }
            )
        results.sort(
            key=lambda item: (
                item["score"],
                item["updated_at"],
            ),
            reverse=True,
        )
        return results[:limit]

    def deadlines(self, *, limit: int = 300) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT i.document_id, i.version, i.deadlines_json, d.name
                FROM document_intelligence i
                JOIN documents d ON d.id = i.document_id
                WHERE i.version = d.version
                  AND d.trashed = 0
                  AND i.deadlines_json != '[]'
                ORDER BY i.analyzed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            for deadline in json.loads(row["deadlines_json"]):
                result.append(
                    {
                        "document_id": row["document_id"],
                        "document_name": row["name"],
                        "version": row["version"],
                        **deadline,
                    }
                )
        return result[:limit]

    def apply_suggestions(
        self,
        document_id: str,
        *,
        apply_tags: bool = True,
        apply_kind_to_dna: bool = True,
    ) -> dict[str, Any]:
        insight = self.get(document_id)
        document = self.cloud_store.get(document_id)
        result: dict[str, Any] = {"document_id": document_id}
        if apply_tags:
            merged = _unique(
                list(document.get("tags", []))
                + list(insight["suggested_tags"]),
                limit=50,
            )
            result["document"] = self.cloud_store.update_document(
                document_id,
                tags=merged,
            )
        result["kind"] = insight["kind"] if apply_kind_to_dna else None
        return result

    def _version_source(
        self,
        document_id: str,
        version: int,
    ) -> tuple[Path, Path | None, dict[str, Any]]:
        document = self.cloud_store.get(
            document_id,
            include_trashed=True,
        )
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = ? AND version = ?
                """,
                (document_id, version),
            ).fetchone()
        if row is None:
            raise KeyError(f"{document_id}:{version}")
        source = self.cloud_store.root_dir / row["storage_ref"]
        if not source.is_file():
            raise FileNotFoundError(str(source))
        if not document["encrypted"]:
            return source, None, dict(row)
        vault = self.cloud_store.vault
        if vault is None:
            raise PermissionError("Сейф Тори недоступен.")
        destination = self.cloud_store.incoming_dir / (
            f"version-{document_id}-{version}{Path(document['name']).suffix}.plain"
        )
        try:
            vault.materialize(
                source,
                destination,
                aad=document_id.encode("utf-8"),
            )
        except RuntimeError as exc:
            raise PermissionError(str(exc)) from exc
        return destination, destination, dict(row)

    def version_text(
        self,
        document_id: str,
        version: int,
    ) -> dict[str, Any]:
        document = self.cloud_store.get(
            document_id,
            include_trashed=True,
        )
        path, cleanup, version_row = self._version_source(
            document_id,
            version,
        )
        try:
            chunks, method, ocr_used = self.extract(
                path,
                name=document["name"],
                content_type=version_row["content_type"],
            )
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)
        v2 = analyze_chunks(chunks)
        text = "\n\n".join(chunk.text for chunk in chunks)
        return {
            "document_id": document_id,
            "version": version,
            "name": document["name"],
            "content_type": version_row["content_type"],
            "sha256": version_row["sha256"],
            "extraction_method": method,
            "ocr_used": ocr_used,
            "text": text[:120_000],
            "structure": v2["structure"],
            "checks": v2["checks"],
            "evidence": v2["evidence"],
            "representative_text": v2["representative_text"][:120_000],
        }

    def local_version_diff(
        self,
        document_id: str,
        first: int,
        second: int,
    ) -> dict[str, Any]:
        a = self.version_text(document_id, first)
        b = self.version_text(document_id, second)
        a_entities = self._entities(a["text"])
        b_entities = self._entities(b["text"])
        a_dates = set(a_entities["dates"])
        b_dates = set(b_entities["dates"])
        a_amounts = {
            (item["currency"], item["value"])
            for item in a_entities["amounts"]
        }
        b_amounts = {
            (item["currency"], item["value"])
            for item in b_entities["amounts"]
        }
        a_lines = {
            line.strip()
            for line in a["text"].splitlines()
            if len(line.strip()) >= 20
        }
        b_lines = {
            line.strip()
            for line in b["text"].splitlines()
            if len(line.strip()) >= 20
        }
        return {
            "document_id": document_id,
            "version_a": first,
            "version_b": second,
            "dates_added": sorted(b_dates - a_dates),
            "dates_removed": sorted(a_dates - b_dates),
            "amounts_added": [
                {"currency": currency, "value": value}
                for currency, value in sorted(b_amounts - a_amounts)
            ],
            "amounts_removed": [
                {"currency": currency, "value": value}
                for currency, value in sorted(a_amounts - b_amounts)
            ],
            "text_added": sorted(b_lines - a_lines)[:30],
            "text_removed": sorted(a_lines - b_lines)[:30],
            "sha256_a": a["sha256"],
            "sha256_b": b["sha256"],
        }
