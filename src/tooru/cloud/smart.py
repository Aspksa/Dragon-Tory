from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from tooru.cloud.store import CloudStore

_RELATION_TYPES = {
    "related",
    "derived_from",
    "replaces",
    "supports",
    "attachment",
    "same_subject",
    "reference",
}
_WATCH_EVENTS = {
    "version_changed",
    "integrity_failed",
    "passport_changed",
    "relation_added",
    "seal_failed",
}
_CONTRACT_FIELDS = {
    "metadata_search",
    "content_read",
    "answer",
    "compare",
    "memory",
    "propose_edits",
    "external_ai",
    "clean_room",
    "one_time_answer",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text[:80]


class SmartDrive:
    def __init__(self, cloud_store: CloudStore) -> None:
        self.cloud_store = cloud_store
        self.db_path = cloud_store.db_path
        self.identity_dir = cloud_store.root_dir / "identity"
        self.private_key_path = self.identity_dir / "seal_ed25519.key"
        self.public_key_path = self.identity_dir / "seal_ed25519.pub"

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _ensure_column(
        db: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            db.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def initialize(self) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_dna (
                    document_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT '',
                    origin TEXT NOT NULL DEFAULT '',
                    external_ref TEXT NOT NULL DEFAULT '',
                    important_date TEXT,
                    language TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                db,
                "document_dna",
                "counterparty",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "document_dna",
                "document_number",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "document_dna",
                "document_date",
                "TEXT",
            )
            self._ensure_column(
                db,
                "document_dna",
                "amount_value",
                "REAL",
            )
            self._ensure_column(
                db,
                "document_dna",
                "amount_currency",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "document_dna",
                "terms_summary",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "document_dna",
                "counterparty_id",
                "TEXT",
            )
            self._ensure_column(
                db,
                "document_dna",
                "document_subtype",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "document_dna",
                "employee_name",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "document_dna",
                "department",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                db,
                "document_dna",
                "work_date",
                "TEXT",
            )
            self._ensure_column(
                db,
                "document_dna",
                "work_hours",
                "REAL",
            )
            self._ensure_column(
                db,
                "document_dna",
                "work_reason",
                "TEXT NOT NULL DEFAULT ''",
            )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS counterparties (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    short_name TEXT NOT NULL DEFAULT '',
                    inn TEXT NOT NULL DEFAULT '',
                    kpp TEXT NOT NULL DEFAULT '',
                    ogrn TEXT NOT NULL DEFAULT '',
                    legal_address TEXT NOT NULL DEFAULT '',
                    postal_address TEXT NOT NULL DEFAULT '',
                    bank_name TEXT NOT NULL DEFAULT '',
                    bik TEXT NOT NULL DEFAULT '',
                    settlement_account TEXT NOT NULL DEFAULT '',
                    correspondent_account TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    contact_person TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_counterparties_name
                ON counterparties(name COLLATE NOCASE)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_counterparties_inn
                ON counterparties(inn)
                """
            )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_ai_contract (
                    document_id TEXT PRIMARY KEY,
                    metadata_search INTEGER NOT NULL DEFAULT 0,
                    content_read INTEGER NOT NULL DEFAULT 0,
                    answer INTEGER NOT NULL DEFAULT 0,
                    compare INTEGER NOT NULL DEFAULT 0,
                    memory INTEGER NOT NULL DEFAULT 0,
                    propose_edits INTEGER NOT NULL DEFAULT 0,
                    external_ai INTEGER NOT NULL DEFAULT 0,
                    clean_room INTEGER NOT NULL DEFAULT 0,
                    one_time_answer INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_relations (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_provenance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    source_ref TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_watch_rules (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_alerts (
                    id TEXT PRIMARY KEY,
                    rule_id TEXT,
                    document_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS drive_snapshots (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_seals (
                    document_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    signature_b64 TEXT NOT NULL,
                    public_key_b64 TEXT NOT NULL,
                    public_key_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, version)
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_relations_source
                ON document_relations(source_id, target_id)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_provenance_document
                ON document_provenance(document_id, id DESC)
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_alerts_open
                ON document_alerts(resolved_at, created_at DESC)
                """
            )

            documents = db.execute(
                """
                SELECT id, ai_access, confidentiality, source, created_at
                FROM documents
                """
            ).fetchall()
            for row in documents:
                self._ensure_defaults_db(db, dict(row))

    def _default_contract(
        self,
        ai_access: str,
        confidentiality: str,
    ) -> dict[str, bool]:
        contract = {field: False for field in _CONTRACT_FIELDS}
        if ai_access in {"search", "read", "answer", "memory", "full"}:
            contract["metadata_search"] = True
        if ai_access in {"read", "answer", "memory", "full"}:
            contract["content_read"] = True
        if ai_access in {"answer", "memory", "full"}:
            contract["answer"] = True
            contract["external_ai"] = True
        if ai_access in {"memory", "full"}:
            contract["memory"] = True
        if ai_access == "full":
            contract["compare"] = True
            contract["propose_edits"] = True

        if confidentiality == "confidential":
            contract["answer"] = False
            contract["memory"] = False
            contract["propose_edits"] = False
            contract["external_ai"] = False
            contract["clean_room"] = False
            contract["one_time_answer"] = False
        elif confidentiality == "highly_protected":
            contract = {field: False for field in _CONTRACT_FIELDS}
        return contract

    def _ensure_defaults_db(
        self,
        db: sqlite3.Connection,
        document: dict[str, Any],
    ) -> None:
        now = utc_now()
        db.execute(
            """
            INSERT OR IGNORE INTO document_dna (
                document_id, created_at, updated_at
            )
            VALUES (?, ?, ?)
            """,
            (document["id"], now, now),
        )
        exists = db.execute(
            """
            SELECT document_id FROM document_ai_contract
            WHERE document_id = ?
            """,
            (document["id"],),
        ).fetchone()
        if exists is None:
            defaults = self._default_contract(
                document["ai_access"],
                document["confidentiality"],
            )
            db.execute(
                """
                INSERT INTO document_ai_contract (
                    document_id, metadata_search, content_read, answer,
                    compare, memory, propose_edits, external_ai, clean_room,
                    one_time_answer, expires_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    document["id"],
                    int(defaults["metadata_search"]),
                    int(defaults["content_read"]),
                    int(defaults["answer"]),
                    int(defaults["compare"]),
                    int(defaults["memory"]),
                    int(defaults["propose_edits"]),
                    int(defaults["external_ai"]),
                    int(defaults["clean_room"]),
                    int(defaults["one_time_answer"]),
                    now,
                ),
            )
        provenance = db.execute(
            """
            SELECT id FROM document_provenance
            WHERE document_id = ?
            LIMIT 1
            """,
            (document["id"],),
        ).fetchone()
        if provenance is None:
            db.execute(
                """
                INSERT INTO document_provenance (
                    document_id, event, actor, source_ref,
                    details_json, created_at
                )
                VALUES (?, 'registered', 'system', ?, ?, ?)
                """,
                (
                    document["id"],
                    document.get("source") or "",
                    json.dumps(
                        {
                            "created_at": document.get("created_at"),
                            "source": document.get("source"),
                        },
                        ensure_ascii=False,
                    ),
                    document.get("created_at") or now,
                ),
            )

    def ensure_document(self, document_id: str) -> None:
        document = self.cloud_store.get(
            document_id,
            include_trashed=True,
        )
        with self._connect() as db:
            self._ensure_defaults_db(db, document)

    @staticmethod
    def _contract_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for field in _CONTRACT_FIELDS:
            item[field] = bool(item[field])
        expires = _parse_time(item.get("expires_at"))
        item["expired"] = bool(
            expires is not None and expires <= datetime.now(UTC)
        )
        return item

    def get_contract(self, document_id: str) -> dict[str, Any]:
        self.ensure_document(document_id)
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM document_ai_contract
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(document_id)
        return self._contract_row(row)

    def _validate_contract(
        self,
        document_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        document = self.cloud_store.get(document_id)
        result = {field: bool(values.get(field, False)) for field in _CONTRACT_FIELDS}
        if result["memory"] and not result["answer"]:
            raise ValueError("Память требует разрешения на ответы.")
        if result["answer"] and not result["content_read"]:
            raise ValueError("Ответы требуют разрешения на чтение.")
        if result["compare"] and not result["content_read"]:
            raise ValueError("Сравнение требует разрешения на чтение.")
        if result["propose_edits"] and not result["content_read"]:
            raise ValueError("Предложения изменений требуют чтения.")
        if result["clean_room"] and not (
            result["answer"] and result["external_ai"]
        ):
            raise ValueError(
                "Чистая комната требует разрешения на ответы и внешний ИИ."
            )
        if result["one_time_answer"] and not result["answer"]:
            raise ValueError(
                "Разовый ответ требует включённого разрешения на ответы."
            )

        if document["confidentiality"] == "confidential":
            forbidden = (
                "answer",
                "memory",
                "propose_edits",
                "external_ai",
                "clean_room",
                "one_time_answer",
            )
            if any(result[field] for field in forbidden):
                raise ValueError(
                    "Конфиденциальный документ нельзя передавать внешнему ИИ "
                    "или использовать для ИИ-ответов."
                )
        if (
            document["confidentiality"] == "highly_protected"
            and any(result.values())
        ):
            raise ValueError(
                "Особо защищённый документ не разрешает ИИ-доступ."
            )
        return result

    @staticmethod
    def _legacy_access(contract: dict[str, Any]) -> str:
        if contract["memory"]:
            return "memory"
        if contract["propose_edits"] or contract["compare"]:
            return "full"
        if contract["answer"]:
            return "answer"
        if contract["content_read"]:
            return "read"
        if contract["metadata_search"]:
            return "search"
        return "denied"

    def update_contract(
        self,
        document_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_contract(document_id)
        merged = {
            field: (
                payload[field]
                if field in payload and payload[field] is not None
                else current[field]
            )
            for field in _CONTRACT_FIELDS
        }
        validated = self._validate_contract(document_id, merged)
        expires_at = (
            payload.get("expires_at")
            if "expires_at" in payload
            else current.get("expires_at")
        )
        if expires_at:
            parsed = _parse_time(expires_at)
            if parsed is None:
                raise ValueError("Неверный формат срока ИИ-договора.")
            expires_at = parsed.isoformat()

        document = self.cloud_store.get(document_id)
        legacy = self._legacy_access(validated)
        if legacy != document["ai_access"]:
            self.cloud_store.update_passport(
                document_id,
                ai_access=legacy,
                confidentiality=document["confidentiality"],
                scope=document["scope"],
                project_id=document["project_id"],
            )

        with self._connect() as db:
            db.execute(
                """
                UPDATE document_ai_contract
                SET metadata_search = ?, content_read = ?, answer = ?,
                    compare = ?, memory = ?, propose_edits = ?,
                    external_ai = ?, clean_room = ?, one_time_answer = ?,
                    expires_at = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    int(validated["metadata_search"]),
                    int(validated["content_read"]),
                    int(validated["answer"]),
                    int(validated["compare"]),
                    int(validated["memory"]),
                    int(validated["propose_edits"]),
                    int(validated["external_ai"]),
                    int(validated["clean_room"]),
                    int(validated["one_time_answer"]),
                    expires_at,
                    utc_now(),
                    document_id,
                ),
            )
        self.record_provenance(
            document_id,
            "ai_contract_updated",
            actor="user",
            details={
                **validated,
                "expires_at": expires_at,
            },
        )
        return self.get_contract(document_id)

    def reconcile_contract(self, document_id: str) -> dict[str, Any]:
        current = self.get_contract(document_id)
        document = self.cloud_store.get(document_id)
        values = {field: current[field] for field in _CONTRACT_FIELDS}
        defaults = self._default_contract(
            document["ai_access"],
            document["confidentiality"],
        )
        legacy_from_contract = self._legacy_access(current)

        if legacy_from_contract != document["ai_access"]:
            return self.update_contract(
                document_id,
                {
                    **defaults,
                    "expires_at": current.get("expires_at"),
                },
            )
        try:
            self._validate_contract(document_id, values)
            return current
        except ValueError:
            return self.update_contract(
                document_id,
                {
                    **defaults,
                    "expires_at": current.get("expires_at"),
                },
            )

    def permission(self, document_id: str, name: str) -> bool:
        if name not in _CONTRACT_FIELDS:
            return False
        contract = self.get_contract(document_id)
        if contract["expired"]:
            return False
        return bool(contract[name])

    def consume_one_time_answer(self, document_id: str) -> bool:
        contract = self.get_contract(document_id)
        if not contract["one_time_answer"]:
            return False
        self.update_contract(
            document_id,
            {
                "answer": False,
                "memory": False,
                "external_ai": False,
                "clean_room": False,
                "one_time_answer": False,
            },
        )
        self.record_provenance(
            document_id,
            "one_time_ai_access_consumed",
            actor="system",
        )
        return True

    @staticmethod
    def _clean_counterparty_payload(
        payload: dict[str, Any],
    ) -> dict[str, str]:
        limits = {
            "name": 500,
            "short_name": 300,
            "inn": 32,
            "kpp": 32,
            "ogrn": 32,
            "legal_address": 1_000,
            "postal_address": 1_000,
            "bank_name": 500,
            "bik": 32,
            "settlement_account": 64,
            "correspondent_account": 64,
            "email": 300,
            "phone": 120,
            "contact_person": 300,
            "notes": 5_000,
        }
        cleaned = {
            key: str(payload.get(key, "") or "").strip()[:limit]
            for key, limit in limits.items()
        }
        if not cleaned["name"]:
            raise ValueError("Укажите наименование контрагента.")
        return cleaned

    def create_counterparty(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        values = self._clean_counterparty_payload(payload)
        counterparty_id = "TORY-CP-" + uuid4().hex.upper()
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO counterparties (
                    id, name, short_name, inn, kpp, ogrn,
                    legal_address, postal_address, bank_name, bik,
                    settlement_account, correspondent_account,
                    email, phone, contact_person, notes,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    counterparty_id,
                    values["name"],
                    values["short_name"],
                    values["inn"],
                    values["kpp"],
                    values["ogrn"],
                    values["legal_address"],
                    values["postal_address"],
                    values["bank_name"],
                    values["bik"],
                    values["settlement_account"],
                    values["correspondent_account"],
                    values["email"],
                    values["phone"],
                    values["contact_person"],
                    values["notes"],
                    now,
                    now,
                ),
            )
        return self.get_counterparty(counterparty_id)

    def update_counterparty(
        self,
        counterparty_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_counterparty(counterparty_id)
        merged = dict(current)
        merged.update(payload)
        values = self._clean_counterparty_payload(merged)
        with self._connect() as db:
            db.execute(
                """
                UPDATE counterparties
                SET name = ?, short_name = ?, inn = ?, kpp = ?, ogrn = ?,
                    legal_address = ?, postal_address = ?, bank_name = ?,
                    bik = ?, settlement_account = ?,
                    correspondent_account = ?, email = ?, phone = ?,
                    contact_person = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    values["name"],
                    values["short_name"],
                    values["inn"],
                    values["kpp"],
                    values["ogrn"],
                    values["legal_address"],
                    values["postal_address"],
                    values["bank_name"],
                    values["bik"],
                    values["settlement_account"],
                    values["correspondent_account"],
                    values["email"],
                    values["phone"],
                    values["contact_person"],
                    values["notes"],
                    utc_now(),
                    counterparty_id,
                ),
            )
            db.execute(
                """
                UPDATE document_dna
                SET counterparty = ?, updated_at = ?
                WHERE counterparty_id = ?
                """,
                (values["name"], utc_now(), counterparty_id),
            )
        return self.get_counterparty(counterparty_id)

    def get_counterparty(
        self,
        counterparty_id: str,
    ) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM counterparties WHERE id = ?",
                (counterparty_id,),
            ).fetchone()
            count = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM document_dna
                WHERE counterparty_id = ?
                """,
                (counterparty_id,),
            ).fetchone()
        if row is None:
            raise KeyError(counterparty_id)
        result = dict(row)
        result["document_count"] = int(count["count"] if count else 0)
        return result

    def list_counterparties(
        self,
        *,
        query: str = "",
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT cp.*,
                       COUNT(dna.document_id) AS document_count
                FROM counterparties cp
                LEFT JOIN document_dna dna
                  ON dna.counterparty_id = cp.id
                WHERE (? = '' OR cp.name LIKE ? OR cp.short_name LIKE ?
                       OR cp.inn LIKE ?)
                GROUP BY cp.id
                ORDER BY cp.name COLLATE NOCASE
                LIMIT ?
                """,
                (
                    query.strip(),
                    pattern,
                    pattern,
                    pattern,
                    max(1, min(int(limit), 1_000)),
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def weekend_timesheet(
        self,
        *,
        year: int | None = None,
        month: int | None = None,
    ) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT dna.*, d.name AS document_name
                FROM document_dna dna
                JOIN documents d ON d.id = dna.document_id
                WHERE d.trashed = 0
                  AND LOWER(dna.kind) = 'служебная записка'
                  AND LOWER(dna.document_subtype) = 'работа в выходной день'
                ORDER BY dna.work_date, dna.employee_name
                """
            ).fetchall()
        items: list[dict[str, Any]] = []
        totals: dict[str, float] = {}
        for row in rows:
            item = dict(row)
            work_date = str(item.get("work_date") or "")
            if year is not None and not work_date.startswith(f"{year:04d}-"):
                continue
            if month is not None:
                prefix = (
                    f"{year:04d}-{month:02d}-"
                    if year is not None
                    else f"-{month:02d}-"
                )
                if year is not None and not work_date.startswith(prefix):
                    continue
                if year is None and len(work_date) >= 7:
                    try:
                        if int(work_date[5:7]) != month:
                            continue
                    except ValueError:
                        continue
            hours = float(item.get("work_hours") or 0.0)
            employee = (
                str(item.get("employee_name") or "").strip()
                or "Сотрудник не указан"
            )
            totals[employee] = totals.get(employee, 0.0) + hours
            items.append(
                {
                    "document_id": item["document_id"],
                    "document_name": item["document_name"],
                    "employee_name": employee,
                    "department": item.get("department") or "",
                    "work_date": item.get("work_date"),
                    "work_hours": hours,
                    "work_reason": item.get("work_reason") or "",
                }
            )
        return {
            "items": items,
            "count": len(items),
            "total_hours": sum(item["work_hours"] for item in items),
            "by_employee": [
                {"employee_name": name, "hours": hours}
                for name, hours in sorted(totals.items())
            ],
        }

    def get_dna(self, document_id: str) -> dict[str, Any]:
        self.ensure_document(document_id)
        document = self.cloud_store.get(
            document_id,
            include_trashed=True,
        )
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM document_dna WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(document_id)
        dna = dict(row)
        dna["counterparty_record"] = None
        if dna.get("counterparty_id"):
            with self._connect() as db:
                counterparty = db.execute(
                    "SELECT * FROM counterparties WHERE id = ?",
                    (dna["counterparty_id"],),
                ).fetchone()
            if counterparty is not None:
                dna["counterparty_record"] = dict(counterparty)
        dna["document"] = {
            "id": document["id"],
            "name": document["name"],
            "version": document["version"],
            "sha256": document["sha256"],
            "source": document["source"],
            "created_at": document["created_at"],
            "updated_at": document["updated_at"],
        }
        return dna

    def update_dna(
        self,
        document_id: str,
        payload: dict[str, Any],
        *,
        actor: str = "user",
    ) -> dict[str, Any]:
        self.ensure_document(document_id)
        current = self.get_dna(document_id)
        values = {
            "kind": str(payload.get("kind", current["kind"]) or "")[:120],
            "origin": str(payload.get("origin", current["origin"]) or "")[:500],
            "external_ref": str(
                payload.get("external_ref", current["external_ref"]) or ""
            )[:1_000],
            "important_date": payload.get(
                "important_date",
                current["important_date"],
            ),
            "language": str(
                payload.get("language", current["language"]) or ""
            )[:60],
            "notes": str(payload.get("notes", current["notes"]) or "")[:5_000],
            "counterparty": str(
                payload.get("counterparty", current["counterparty"]) or ""
            )[:500],
            "document_number": str(
                payload.get("document_number", current["document_number"]) or ""
            )[:200],
            "document_date": _normalize_date(
                payload.get(
                    "document_date",
                    current["document_date"],
                )
            ),
            "amount_value": payload.get(
                "amount_value",
                current["amount_value"],
            ),
            "amount_currency": str(
                payload.get(
                    "amount_currency",
                    current["amount_currency"],
                )
                or ""
            )[:20],
            "terms_summary": str(
                payload.get("terms_summary", current["terms_summary"]) or ""
            )[:5_000],
            "counterparty_id": payload.get(
                "counterparty_id",
                current.get("counterparty_id"),
            ),
            "document_subtype": str(
                payload.get(
                    "document_subtype",
                    current.get("document_subtype", ""),
                )
                or ""
            )[:200],
            "employee_name": str(
                payload.get(
                    "employee_name",
                    current.get("employee_name", ""),
                )
                or ""
            )[:300],
            "department": str(
                payload.get(
                    "department",
                    current.get("department", ""),
                )
                or ""
            )[:300],
            "work_date": _normalize_date(
                payload.get(
                    "work_date",
                    current.get("work_date"),
                )
            ),
            "work_hours": payload.get(
                "work_hours",
                current.get("work_hours"),
            ),
            "work_reason": str(
                payload.get(
                    "work_reason",
                    current.get("work_reason", ""),
                )
                or ""
            )[:2_000],
        }

        if values["counterparty_id"]:
            counterparty = self.get_counterparty(
                str(values["counterparty_id"])
            )
            values["counterparty"] = counterparty["name"]
        with self._connect() as db:
            db.execute(
                """
                UPDATE document_dna
                SET kind = ?, origin = ?, external_ref = ?,
                    important_date = ?, language = ?, notes = ?,
                    counterparty = ?, document_number = ?,
                    document_date = ?, amount_value = ?,
                    amount_currency = ?, terms_summary = ?,
                    counterparty_id = ?, document_subtype = ?,
                    employee_name = ?, department = ?,
                    work_date = ?, work_hours = ?, work_reason = ?,
                    updated_at = ?
                WHERE document_id = ?
                """,
                (
                    values["kind"],
                    values["origin"],
                    values["external_ref"],
                    values["important_date"],
                    values["language"],
                    values["notes"],
                    values["counterparty"],
                    values["document_number"],
                    values["document_date"],
                    values["amount_value"],
                    values["amount_currency"],
                    values["terms_summary"],
                    values["counterparty_id"],
                    values["document_subtype"],
                    values["employee_name"],
                    values["department"],
                    values["work_date"],
                    values["work_hours"],
                    values["work_reason"],
                    utc_now(),
                    document_id,
                ),
            )
        self.record_provenance(
            document_id,
            "dna_updated",
            actor=actor,
            details=values,
        )
        return self.get_dna(document_id)

    def apply_intelligence_defaults(
        self,
        document_id: str,
        analysis: dict[str, Any],
        *,
        confidence_threshold: float = 0.75,
    ) -> dict[str, Any]:
        self.ensure_document(document_id)
        confidence = float(analysis.get("confidence") or 0.0)
        if confidence < confidence_threshold:
            return {
                "applied": False,
                "reason": "low_confidence",
                "confidence": confidence,
                "fields": [],
            }

        dna = self.get_dna(document_id)
        payload: dict[str, Any] = {}
        fields: list[str] = []

        if not str(dna.get("kind") or "").strip() and analysis.get("kind"):
            payload["kind"] = str(analysis["kind"])
            fields.append("kind")

        entities = analysis.get("entities") or {}
        references = entities.get("references") or []
        if (
            not str(dna.get("external_ref") or "").strip()
            and len(references) == 1
        ):
            payload["external_ref"] = str(references[0])
            fields.append("external_ref")

        deadlines = analysis.get("deadlines") or []
        if not dna.get("important_date") and len(deadlines) == 1:
            payload["important_date"] = deadlines[0].get("date")
            fields.append("important_date")

        if not str(dna.get("document_number") or "").strip() and len(
            references
        ) == 1:
            payload["document_number"] = str(references[0])
            fields.append("document_number")

        amounts = entities.get("amounts") or []
        if dna.get("amount_value") is None and len(amounts) == 1:
            payload["amount_value"] = amounts[0].get("value")
            payload["amount_currency"] = amounts[0].get("currency") or ""
            fields.extend(["amount_value", "amount_currency"])

        counterparties = entities.get("counterparties") or []
        if (
            not str(dna.get("counterparty") or "").strip()
            and len(counterparties) == 1
        ):
            payload["counterparty"] = str(counterparties[0])
            fields.append("counterparty")
            matches = [
                cp
                for cp in self.list_counterparties(
                    query=str(counterparties[0]),
                    limit=20,
                )
                if cp["name"].strip().casefold()
                == str(counterparties[0]).strip().casefold()
                or (
                    cp.get("short_name")
                    and cp["short_name"].strip().casefold()
                    == str(counterparties[0]).strip().casefold()
                )
            ]
            if len(matches) == 1 and not dna.get("counterparty_id"):
                payload["counterparty_id"] = matches[0]["id"]
                fields.append("counterparty_id")

        if analysis.get("kind") == "служебная записка":
            employees = entities.get("employees") or []
            departments = entities.get("departments") or []
            work_dates = entities.get("work_dates") or []
            work_hours = entities.get("work_hours") or []
            work_signals = bool(
                employees or departments or work_dates or work_hours
            )
            if (
                work_signals
                and not str(dna.get("document_subtype") or "").strip()
            ):
                payload["document_subtype"] = "Работа в выходной день"
                fields.append("document_subtype")
            if (
                not str(dna.get("employee_name") or "").strip()
                and len(employees) == 1
            ):
                payload["employee_name"] = str(employees[0])
                fields.append("employee_name")
            if (
                not str(dna.get("department") or "").strip()
                and len(departments) == 1
            ):
                payload["department"] = str(departments[0])
                fields.append("department")
            if not dna.get("work_date") and len(work_dates) == 1:
                payload["work_date"] = str(work_dates[0])
                fields.append("work_date")
            if dna.get("work_hours") is None and len(work_hours) == 1:
                payload["work_hours"] = float(work_hours[0])
                fields.append("work_hours")

        if payload:
            self.update_dna(
                document_id,
                payload,
                actor="tooru-local",
            )

        document = self.cloud_store.get(document_id)
        suggested_tags = [
            str(tag).strip()
            for tag in analysis.get("suggested_tags") or []
            if str(tag).strip()
        ]
        merged_tags = list(document.get("tags", []))
        seen = {tag.casefold() for tag in merged_tags}
        added_tags = []
        for tag in suggested_tags:
            if tag.casefold() in seen:
                continue
            seen.add(tag.casefold())
            merged_tags.append(tag)
            added_tags.append(tag)
            if len(merged_tags) >= 50:
                break

        if added_tags:
            self.cloud_store.update_document(
                document_id,
                tags=merged_tags,
            )
            fields.append("tags")

        if fields:
            self.record_provenance(
                document_id,
                "intelligence_safe_autofill",
                actor="tooru-local",
                details={
                    "fields": fields,
                    "confidence": confidence,
                    "kind": analysis.get("kind"),
                    "added_tags": added_tags,
                    "manual_values_overwritten": False,
                },
            )
        return {
            "applied": bool(fields),
            "reason": "applied" if fields else "nothing_empty",
            "confidence": confidence,
            "fields": fields,
            "added_tags": added_tags,
        }

    def record_provenance(
        self,
        document_id: str,
        event: str,
        *,
        actor: str = "system",
        source_ref: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.ensure_document(document_id)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO document_provenance (
                    document_id, event, actor, source_ref,
                    details_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    event[:120],
                    actor[:80],
                    source_ref[:1_000],
                    json.dumps(details or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def provenance(
        self,
        document_id: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self.ensure_document(document_id)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, event, actor, source_ref, details_json, created_at
                FROM document_provenance
                WHERE document_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (document_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json"))
            except json.JSONDecodeError:
                item["details"] = {}
            result.append(item)
        return result

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        note: str = "",
    ) -> dict[str, Any]:
        if source_id == target_id:
            raise ValueError("Документ нельзя связать с самим собой.")
        self.ensure_document(source_id)
        self.ensure_document(target_id)
        if relation_type not in _RELATION_TYPES:
            raise ValueError("Неизвестный тип связи.")
        relation_id = "TORY-REL-" + uuid4().hex.upper()
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO document_relations (
                    id, source_id, target_id, relation_type, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    relation_id,
                    source_id,
                    target_id,
                    relation_type,
                    note[:1_000],
                    now,
                ),
            )
        self.emit_event(
            source_id,
            "relation_added",
            details={
                "relation_id": relation_id,
                "target_id": target_id,
                "relation_type": relation_type,
            },
            actor="user",
        )
        return {
            "id": relation_id,
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
            "note": note[:1_000],
            "created_at": now,
        }

    def list_relations(self, document_id: str) -> list[dict[str, Any]]:
        self.ensure_document(document_id)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    r.*,
                    s.name AS source_name,
                    t.name AS target_name
                FROM document_relations r
                JOIN documents s ON s.id = r.source_id
                JOIN documents t ON t.id = r.target_id
                WHERE r.source_id = ? OR r.target_id = ?
                ORDER BY r.created_at DESC
                """,
                (document_id, document_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_relation(self, relation_id: str) -> bool:
        with self._connect() as db:
            result = db.execute(
                "DELETE FROM document_relations WHERE id = ?",
                (relation_id,),
            )
        return result.rowcount > 0

    def graph(self, *, limit: int = 300) -> dict[str, Any]:
        with self._connect() as db:
            relations = db.execute(
                """
                SELECT * FROM document_relations
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            ids: set[str] = set()
            edges = []
            for row in relations:
                item = dict(row)
                ids.add(item["source_id"])
                ids.add(item["target_id"])
                edges.append(item)
            nodes = []
            if ids:
                placeholders = ",".join("?" for _ in ids)
                rows = db.execute(
                    f"""
                    SELECT id, name, version, scope, project_id,
                           confidentiality, favorite
                    FROM documents
                    WHERE id IN ({placeholders})
                    """,
                    tuple(ids),
                ).fetchall()
                nodes = [dict(row) for row in rows]
        return {"nodes": nodes, "edges": edges}

    def suggest_relations(
        self,
        document_id: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        source = self.cloud_store.get(document_id)
        source_tags = {tag.lower() for tag in source.get("tags", [])}
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id FROM documents
                WHERE id != ? AND trashed = 0
                ORDER BY updated_at DESC
                LIMIT 500
                """,
                (document_id,),
            ).fetchall()
        scored = []
        for row in rows:
            candidate = self.cloud_store.get(row["id"])
            tags = {tag.lower() for tag in candidate.get("tags", [])}
            shared = sorted(source_tags & tags)
            score = len(shared) * 3
            if (
                source.get("project_id")
                and source.get("project_id") == candidate.get("project_id")
            ):
                score += 2
            if score < 1:
                continue
            scored.append(
                {
                    "document_id": candidate["id"],
                    "name": candidate["name"],
                    "score": score,
                    "shared_tags": shared,
                    "same_project": bool(
                        source.get("project_id")
                        and source.get("project_id")
                        == candidate.get("project_id")
                    ),
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def create_watch(
        self,
        document_id: str,
        event_type: str,
        *,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_document(document_id)
        if event_type not in _WATCH_EVENTS:
            raise ValueError("Неизвестный тип наблюдателя.")
        rule_id = "TORY-WATCH-" + uuid4().hex.upper()
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO document_watch_rules (
                    id, document_id, event_type, enabled,
                    config_json, created_at
                )
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (
                    rule_id,
                    document_id,
                    event_type,
                    json.dumps(config or {}, ensure_ascii=False),
                    now,
                ),
            )
        return {
            "id": rule_id,
            "document_id": document_id,
            "event_type": event_type,
            "enabled": True,
            "config": config or {},
            "created_at": now,
        }

    def list_watches(self, document_id: str) -> list[dict[str, Any]]:
        self.ensure_document(document_id)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM document_watch_rules
                WHERE document_id = ?
                ORDER BY created_at DESC
                """,
                (document_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            try:
                item["config"] = json.loads(item.pop("config_json"))
            except json.JSONDecodeError:
                item["config"] = {}
            result.append(item)
        return result

    def delete_watch(self, rule_id: str) -> bool:
        with self._connect() as db:
            result = db.execute(
                "DELETE FROM document_watch_rules WHERE id = ?",
                (rule_id,),
            )
        return result.rowcount > 0

    def emit_event(
        self,
        document_id: str,
        event_type: str,
        *,
        details: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> list[dict[str, Any]]:
        self.record_provenance(
            document_id,
            event_type,
            actor=actor,
            details=details,
        )
        with self._connect() as db:
            rules = db.execute(
                """
                SELECT * FROM document_watch_rules
                WHERE document_id = ? AND event_type = ? AND enabled = 1
                """,
                (document_id, event_type),
            ).fetchall()
            alerts = []
            for rule in rules:
                alert_id = "TORY-ALERT-" + uuid4().hex.upper()
                severity = (
                    "high" if event_type in {"integrity_failed", "seal_failed"}
                    else "info"
                )
                titles = {
                    "version_changed": "Новая версия документа",
                    "integrity_failed": "Нарушена целостность документа",
                    "passport_changed": "Изменён цифровой паспорт",
                    "relation_added": "Добавлена связь документа",
                    "seal_failed": "Криптопечать не подтверждена",
                }
                title = titles.get(event_type, "Событие документа")
                message = json.dumps(details or {}, ensure_ascii=False)
                now = utc_now()
                db.execute(
                    """
                    INSERT INTO document_alerts (
                        id, rule_id, document_id, severity,
                        title, message, created_at, resolved_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        alert_id,
                        rule["id"],
                        document_id,
                        severity,
                        title,
                        message[:2_000],
                        now,
                    ),
                )
                alerts.append(
                    {
                        "id": alert_id,
                        "document_id": document_id,
                        "severity": severity,
                        "title": title,
                        "message": message[:2_000],
                        "created_at": now,
                    }
                )
        return alerts

    def alerts(
        self,
        *,
        include_resolved: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT a.*, d.name AS document_name
            FROM document_alerts a
            JOIN documents d ON d.id = a.document_id
        """
        if not include_resolved:
            sql += " WHERE a.resolved_at IS NULL"
        sql += " ORDER BY a.created_at DESC LIMIT ?"
        with self._connect() as db:
            rows = db.execute(sql, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def resolve_alert(self, alert_id: str) -> bool:
        with self._connect() as db:
            result = db.execute(
                """
                UPDATE document_alerts
                SET resolved_at = ?
                WHERE id = ? AND resolved_at IS NULL
                """,
                (utc_now(), alert_id),
            )
        return result.rowcount > 0

    def _snapshot_payload(self) -> dict[str, Any]:
        with self._connect() as db:
            documents = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, name, folder_id, favorite, description,
                           tags_json, version, trashed, scope, project_id,
                           confidentiality, ai_access, sha256, updated_at
                    FROM documents
                    ORDER BY id
                    """
                ).fetchall()
            ]
            folders = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, name, parent_id, trashed, updated_at
                    FROM folders
                    ORDER BY id
                    """
                ).fetchall()
            ]
        return {
            "schema": 1,
            "created_at": utc_now(),
            "documents": documents,
            "folders": folders,
        }

    def create_snapshot(self, label: str) -> dict[str, Any]:
        snapshot_id = "TORY-SNAPSHOT-" + uuid4().hex.upper()
        payload = self._snapshot_payload()
        now = payload["created_at"]
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO drive_snapshots (
                    id, label, snapshot_json, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    (label.strip() or "Снимок диска")[:255],
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
        return {
            "id": snapshot_id,
            "label": (label.strip() or "Снимок диска")[:255],
            "created_at": now,
            "documents": len(payload["documents"]),
            "folders": len(payload["folders"]),
        }

    def list_snapshots(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, label, created_at
                FROM drive_snapshots
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM drive_snapshots
                WHERE id = ?
                """,
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        item = dict(row)
        item["snapshot"] = json.loads(item.pop("snapshot_json"))
        return item

    def restore_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.get_snapshot(snapshot_id)["snapshot"]
        restored = 0
        skipped = 0
        for state in snapshot.get("documents", []):
            document_id = state["id"]
            try:
                current = self.cloud_store.get(
                    document_id,
                    include_trashed=True,
                )
            except KeyError:
                skipped += 1
                continue

            try:
                if current["trashed"] and not bool(state["trashed"]):
                    current = self.cloud_store.restore(document_id)
                if (
                    not current["trashed"]
                    and int(state["version"]) != int(current["version"])
                ):
                    versions = {
                        int(item["version"])
                        for item in self.cloud_store.list_versions(document_id)
                    }
                    if int(state["version"]) in versions:
                        current = self.cloud_store.restore_version(
                            document_id,
                            int(state["version"]),
                        )
                if not current["trashed"]:
                    folder_id = state["folder_id"]
                    try:
                        self.cloud_store.update_document(
                            document_id,
                            name=state["name"],
                            folder_id=folder_id,
                            favorite=bool(state["favorite"]),
                            description=state["description"],
                            tags=json.loads(state["tags_json"] or "[]"),
                        )
                    except ValueError:
                        self.cloud_store.update_document(
                            document_id,
                            name=state["name"],
                            folder_id=None,
                            favorite=bool(state["favorite"]),
                            description=state["description"],
                            tags=json.loads(state["tags_json"] or "[]"),
                        )
                    if bool(state["trashed"]):
                        self.cloud_store.trash(document_id)
                restored += 1
                self.record_provenance(
                    document_id,
                    "time_machine_restored",
                    actor="user",
                    source_ref=snapshot_id,
                    details={
                        "snapshot_version": state["version"],
                        "security_policy_preserved": True,
                    },
                )
            except (FileNotFoundError, PermissionError, ValueError):
                skipped += 1
        return {
            "snapshot_id": snapshot_id,
            "restored_documents": restored,
            "skipped_documents": skipped,
            "security_policy_preserved": True,
        }

    def _private_key(self) -> Ed25519PrivateKey:
        if self.private_key_path.is_file():
            return Ed25519PrivateKey.from_private_bytes(
                self.private_key_path.read_bytes()
            )
        private = Ed25519PrivateKey.generate()
        private_bytes = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.private_key_path.write_bytes(private_bytes)
        self.public_key_path.write_bytes(public_bytes)
        return private

    def _seal_payload(
        self,
        document_id: str,
        version: int,
    ) -> tuple[dict[str, Any], bytes]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT
                    v.document_id, v.version, v.sha256, v.size_bytes,
                    v.content_type, v.created_at
                FROM document_versions v
                WHERE v.document_id = ? AND v.version = ?
                """,
                (document_id, version),
            ).fetchone()
        if row is None:
            raise KeyError(f"{document_id}:{version}")
        payload = dict(row)
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return payload, canonical

    def seal(self, document_id: str) -> dict[str, Any]:
        document = self.cloud_store.get(document_id)
        version = int(document["version"])
        payload, canonical = self._seal_payload(document_id, version)
        private = self._private_key()
        public_bytes = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        signature = private.sign(canonical)
        digest = hashlib.sha256(canonical).hexdigest()
        fingerprint = hashlib.sha256(public_bytes).hexdigest()
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO document_seals (
                    document_id, version, payload_sha256,
                    signature_b64, public_key_b64,
                    public_key_fingerprint, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    version,
                    digest,
                    base64.b64encode(signature).decode("ascii"),
                    base64.b64encode(public_bytes).decode("ascii"),
                    fingerprint,
                    now,
                ),
            )
        self.record_provenance(
            document_id,
            "local_seal_created",
            actor="user",
            details={
                "version": version,
                "public_key_fingerprint": fingerprint,
            },
        )
        return {
            "document_id": document_id,
            "version": version,
            "payload": payload,
            "payload_sha256": digest,
            "public_key_fingerprint": fingerprint,
            "created_at": now,
            "identity_scope": "local_dragon_tory_installation",
        }

    def latest_seal(self, document_id: str) -> dict[str, Any] | None:
        self.ensure_document(document_id)
        with self._connect() as db:
            row = db.execute(
                """
                SELECT document_id, version, payload_sha256,
                       public_key_fingerprint, created_at
                FROM document_seals
                WHERE document_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def verify_seal(
        self,
        document_id: str,
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        document = self.cloud_store.get(
            document_id,
            include_trashed=True,
        )
        target_version = int(version or document["version"])
        with self._connect() as db:
            seal = db.execute(
                """
                SELECT * FROM document_seals
                WHERE document_id = ? AND version = ?
                """,
                (document_id, target_version),
            ).fetchone()
        if seal is None:
            raise KeyError(f"{document_id}:{target_version}")

        payload, canonical = self._seal_payload(
            document_id,
            target_version,
        )
        digest = hashlib.sha256(canonical).hexdigest()
        signature_valid = False
        try:
            public = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(seal["public_key_b64"])
            )
            public.verify(
                base64.b64decode(seal["signature_b64"]),
                canonical,
            )
            signature_valid = digest == seal["payload_sha256"]
        except (InvalidSignature, ValueError, TypeError):
            signature_valid = False

        storage_verified: bool | None = None
        storage_message = "Историческая версия проверена по реестру версий."
        if target_version == int(document["version"]) and not document["trashed"]:
            try:
                integrity = self.cloud_store.verify_integrity(document_id)
                storage_verified = bool(integrity["ok"])
                storage_message = (
                    "Физический файл совпадает с зарегистрированным SHA-256."
                    if storage_verified
                    else "Физический файл отличается от зарегистрированной версии."
                )
            except PermissionError:
                storage_message = (
                    "Сейф заблокирован: подпись метаданных проверена, "
                    "физический файл не расшифровывался."
                )

        ok = signature_valid and storage_verified is not False
        if not ok:
            self.emit_event(
                document_id,
                "seal_failed",
                details={
                    "version": target_version,
                    "signature_valid": signature_valid,
                    "storage_verified": storage_verified,
                },
            )
        return {
            "ok": ok,
            "signature_valid": signature_valid,
            "storage_verified": storage_verified,
            "storage_message": storage_message,
            "document_id": document_id,
            "version": target_version,
            "payload": payload,
            "payload_sha256": digest,
            "public_key_fingerprint": seal["public_key_fingerprint"],
            "identity_scope": "local_dragon_tory_installation",
        }

    def timeline(self, document_id: str) -> list[dict[str, Any]]:
        provenance = [
            {
                "type": "provenance",
                "event": item["event"],
                "details": item["details"],
                "actor": item["actor"],
                "created_at": item["created_at"],
            }
            for item in self.provenance(document_id)
        ]
        activity = [
            {
                "type": "activity",
                "event": item["action"],
                "details": item["details"],
                "actor": "system",
                "created_at": item["created_at"],
            }
            for item in self.cloud_store.activity(document_id)
        ]
        combined = provenance + activity
        combined.sort(
            key=lambda item: item["created_at"],
            reverse=True,
        )
        return combined[:300]

    def knowledge_card(self, document_id: str) -> dict[str, Any]:
        document = self.cloud_store.get(
            document_id,
            include_trashed=True,
        )
        versions = self.cloud_store.list_versions(document_id)
        relations = self.list_relations(document_id)
        contract = self.get_contract(document_id)
        dna = self.get_dna(document_id)
        watches = self.list_watches(document_id)
        seal = self.latest_seal(document_id)
        suggestions = (
            self.suggest_relations(document_id)
            if not document["trashed"]
            else []
        )
        return {
            "document": document,
            "dna": dna,
            "ai_contract": contract,
            "version_count": len(versions),
            "relations": relations,
            "relation_suggestions": suggestions,
            "watchers": watches,
            "latest_seal": seal,
            "timeline_preview": self.timeline(document_id)[:12],
        }
