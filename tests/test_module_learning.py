import hashlib
from pathlib import Path

import pytest
from openpyxl import Workbook

from tooru.ai.router import AIRouter
from tooru.cloud.document_intelligence import DocumentIntelligence
from tooru.cloud.module_learning import ModuleLearningService
from tooru.cloud.smart import SmartDrive
from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.models import MemoryScope, MemorySearch
from tooru.memory.store import SQLiteMemoryStore


class NoAI:
    def has_provider(self, name: str) -> bool:
        return False


def _stack(tmp_path: Path):
    root = tmp_path / "cloud"
    vault = ToryVault(root / "vault.json")
    cloud = CloudStore(
        root,
        root / "tooru_cloud.sqlite3",
        vault=vault,
    )
    cloud.initialize()
    smart = SmartDrive(cloud)
    smart.initialize()
    intelligence = DocumentIntelligence(cloud)
    intelligence.initialize()
    memory_store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    memory = MemoryEngine(
        store=memory_store,
        embedder=HashEmbeddingProvider(128),
    )
    memory.initialize()
    guardian = MemoryGuardian(
        MemoryIntelligence(
            memory,
            AIRouter(),
            IntelligenceConfig(
                primary_provider="deepseek",
                reviewer_provider="deepseek",
            ),
        ),
        memory_store,
        GuardianConfig(),
    )
    learning = ModuleLearningService(
        memory_intake=MemoryIntakeGateway(guardian),
        smart=smart,
        intelligence=intelligence,
        ai_router=NoAI(),
    )
    return cloud, smart, intelligence, memory, learning


def _upload(
    store: CloudStore,
    name: str,
    content: bytes,
) -> dict:
    temp = store.incoming_dir / (name + ".upload")
    temp.write_bytes(content)
    return store.register_upload(
        temp,
        name=name,
        content_type="text/plain",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


@pytest.mark.asyncio
async def test_contract_study_writes_traceable_project_memory(
    tmp_path: Path,
) -> None:
    cloud, smart, _, memory, learning = _stack(tmp_path)
    document = _upload(
        cloud,
        "Договор-12.txt",
        (
            "ДОГОВОР № 12\n"
            "Контрагент: ООО Ромашка\n"
            "Сумма 125 000 RUB.\n"
            "Срок действия до 31.12.2026."
        ).encode(),
    )
    smart.update_dna(
        document["id"],
        {
            "kind": "договор",
            "counterparty": "ООО Ромашка",
            "document_number": "12",
            "amount_value": 125000,
            "amount_currency": "RUB",
        },
    )
    smart.update_contract(
        document["id"],
        {
            "metadata_search": True,
            "content_read": True,
            "answer": True,
            "memory": True,
            "external_ai": False,
        },
    )

    result = await learning.study("contracts")

    assert result["studied"] == 1
    assert result["external_ai_summaries"] == 0
    hits = memory.search(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="Ромашка",
            limit=10,
        )
    )
    assert len(hits) == 1
    assert document["id"] in hits[0].content
    assert hits[0].source == "tooru-module-study"


@pytest.mark.asyncio
async def test_contract_without_memory_permission_is_skipped(
    tmp_path: Path,
) -> None:
    cloud, smart, _, _, learning = _stack(tmp_path)
    document = _upload(
        cloud,
        "Договор-no-memory.txt",
        b"contract without memory permission",
    )
    smart.update_dna(document["id"], {"kind": "договор"})
    smart.update_contract(
        document["id"],
        {
            "metadata_search": True,
            "content_read": True,
            "answer": True,
            "memory": False,
        },
    )

    result = await learning.study("contracts")

    assert result["studied"] == 0
    assert result["skipped"] == 1
    assert "content_read + memory" in result["skipped_items"][0]["reason"]


@pytest.mark.asyncio
async def test_garage_and_timesheet_sync_to_project_memory(
    tmp_path: Path,
) -> None:
    cloud, smart, _, memory, learning = _stack(tmp_path)
    employee = smart.create_employee(
        {
            "full_name": "Иванов Иван Иванович",
            "position": "Водитель",
            "department": "Гараж",
        }
    )
    smart.create_vehicle(
        {
            "garage_number": "7",
            "plate_number": "А123АА77",
            "vin": "JF1SJABC1GH123456",
            "make_model": "Subaru Forester",
            "driver_employee_id": employee["id"],
        }
    )
    memo = _upload(cloud, "weekend.txt", b"weekend work")
    smart.update_dna(
        memo["id"],
        {
            "kind": "служебная записка",
            "document_subtype": "Работа в выходной день",
            "employee_name": "Иванов Иван Иванович",
            "department": "Гараж",
            "work_date": "2026-10-23",
            "work_hours": 8,
            "work_reason": "Перегон автомобиля",
        },
    )

    garage = await learning.study("garage")
    timesheet = await learning.study("timesheet")

    assert garage["studied"] == 1
    assert timesheet["studied"] == 1
    vehicle_hits = memory.search(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="А123АА77",
            limit=10,
        )
    )
    work_hits = memory.search(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="Перегон автомобиля",
            limit=10,
        )
    )
    assert vehicle_hits
    assert "Subaru Forester" in vehicle_hits[0].content
    assert work_hits
    assert "8" in work_hits[0].content



@pytest.mark.asyncio
async def test_service_memo_module_studies_into_project_memory(
    tmp_path: Path,
) -> None:
    cloud, smart, intelligence, memory, learning = _stack(tmp_path)
    document = _upload(
        cloud,
        "memo-learning.txt",
        (
            "Служебная записка № 41 от 01.10.2026\n"
            "Подразделение: Гараж\n"
            "Прошу выполнить ремонт автомобиля А123АА77."
        ).encode(),
    )
    cloud.update_passport(
        document["id"],
        ai_access="memory",
        confidentiality="personal",
        scope="project",
        project_id="dragon-tory",
    )
    smart.reconcile_contract(document["id"])
    smart.update_dna(
        document["id"],
        {
            "kind": "служебная записка",
            "document_number": "41",
            "department": "Гараж",
        },
    )
    analysis = intelligence.analyze(document["id"])
    smart.apply_intelligence_defaults(document["id"], analysis)

    result = await learning.study("memos")

    assert result["studied"] == 1
    hits = memory.search(
        MemorySearch(
            scope=MemoryScope.PROJECT,
            project_id="dragon-tory",
            query="А123АА77 ремонт",
            limit=10,
        )
    )
    assert hits
    assert document["id"] in hits[0].content

@pytest.mark.asyncio
async def test_invoice_learning_keeps_sheet_cell_provenance(
    tmp_path: Path,
) -> None:
    cloud, smart, intelligence, memory, learning = _stack(tmp_path)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Оферта"
    sheet.append(["Счёт-оферта № 77", ""])
    sheet.append(["Поставщик", "ООО Таблица"])
    sheet.append(["Итого", "2500 RUB"])
    source = cloud.incoming_dir / "offer.xlsx.upload"
    workbook.save(source)
    payload = source.read_bytes()
    document = cloud.register_upload(
        source,
        name="offer.xlsx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    smart.update_dna(
        document["id"],
        {
            "kind": "счёт-оферта",
            "counterparty": "ООО Таблица",
            "document_number": "77",
            "amount_value": 2500,
            "amount_currency": "RUB",
        },
    )
    smart.update_contract(
        document["id"],
        {
            "metadata_search": True,
            "content_read": True,
            "answer": True,
            "memory": True,
            "external_ai": False,
        },
    )
    analysis = intelligence.analyze(document["id"])
    assert analysis["evidence"]

    result = await learning.study("invoice_offers")

    assert result["studied"] == 1
    memory_id = result["memory_ids"][0]
    evidence = memory.evidence(memory_id)
    precise = [
        item
        for item in evidence
        if item.extraction_method == "document-intelligence-v2"
    ]
    assert precise
    assert any(item.document_id == document["id"] for item in precise)
    assert any(item.table_ref == "Оферта" for item in precise)
    assert any(item.cell_ref and item.cell_ref.startswith("A1:") for item in precise)
    assert any(item.chunk_no == 1 for item in precise)

