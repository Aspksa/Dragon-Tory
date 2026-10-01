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
from typing import Any

from pypdf import PdfReader

from tooru.cloud.intelligence import (
    ExtractedChunk,
    UnsupportedDocumentError,
    extract_document,
)
from tooru.cloud.store import CloudStore

_DATE_PATTERNS = (
    re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}\b"),
    re.compile(r"\b(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])\b"),
)
_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>"]+", re.IGNORECASE)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(
    r"(?:(?P<currency1>€|EUR|USD|\$|GBP|£|RUB|₽)\s*)?"
    r"(?P<amount>\d{1,3}(?:[ .]\d{3})*(?:[,.]\d{1,2})?|\d+(?:[,.]\d{1,2})?)"
    r"(?:\s*(?P<currency2>€|EUR|USD|\$|GBP|£|RUB|₽))?",
    re.IGNORECASE,
)
_REF_RE = re.compile(
    r"\b(?:договор|contract|invoice|сч[её]т|order|заказ|полис|policy)"
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
    "счёт": (
        "счет на оплату",
        "счёт на оплату",
        "invoice",
        "payment due",
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
    def __init__(self, cloud_store: CloudStore) -> None:
        self.cloud_store = cloud_store
        self.db_path = cloud_store.db_path

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
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
        reader = PdfReader(str(path))
        chunks: list[ExtractedChunk] = []
        with tempfile.TemporaryDirectory(
            dir=str(self.cloud_store.incoming_dir)
        ) as temp_dir:
            root = Path(temp_dir)
            for page_no, page in enumerate(reader.pages, start=1):
                for image_no, image in enumerate(page.images, start=1):
                    suffix = Path(image.name or "scan.png").suffix or ".png"
                    image_path = root / f"p{page_no}-{image_no}{suffix}"
                    image_path.write_bytes(image.data)
                    for chunk in self._ocr_file(
                        image_path,
                        label=f"OCR · страница {page_no}",
                    ):
                        chunk.page = page_no
                        chunks.append(chunk)
        return chunks

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

        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
            return self._ocr_file(path, label="OCR · изображение"), "ocr_image", True
        if suffix == ".pdf" or content_type == "application/pdf":
            ocr_chunks = self._ocr_pdf(path)
            if ocr_chunks:
                return ocr_chunks, "ocr_pdf_images", True
        if chunks:
            return chunks, "native_text", False
        raise UnsupportedDocumentError(
            "Из документа не удалось получить текст. Для сканов нужен "
            "локальный Tesseract OCR с нужным языковым пакетом."
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

        text = "\n\n".join(chunk.text for chunk in chunks)
        analysis_text = text[:250_000]
        kind, confidence = self._classify(item["name"], analysis_text)
        entities = self._entities(analysis_text)
        deadlines = self._deadlines(analysis_text)
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
                    suggested_relations_json, extraction_method, ocr_used,
                    analyzed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    method,
                    int(ocr_used),
                    analyzed_at,
                ),
            )
        return self.get(document_id)

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["ocr_used"] = bool(item["ocr_used"])
        for key in (
            "entities_json",
            "deadlines_json",
            "suggested_tags_json",
            "suggested_relations_json",
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
        terms = {
            token.strip(".,:;!?()[]{}").casefold()
            for token in cleaned.split()
            if len(token.strip(".,:;!?()[]{}")) >= 2
        }
        terms = {
            term
            for term in terms
            if term not in stop
            and term != requested_year
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
