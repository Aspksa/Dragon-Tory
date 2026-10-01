from pathlib import Path
from types import SimpleNamespace

import pytest

from tooru.chat.workflows import (
    create_weekend_work_document,
    is_weekend_work_request,
)
from tooru.cloud.document_intelligence import DocumentIntelligence
from tooru.cloud.smart import SmartDrive
from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault


class NoAI:
    def has_provider(self, name: str) -> bool:
        return False


def _stack(tmp_path: Path):
    root = tmp_path / "cloud"
    vault = ToryVault(root / "vault.json")
    store = CloudStore(
        root,
        root / "tooru_cloud.sqlite3",
        vault=vault,
    )
    store.initialize()
    smart = SmartDrive(store)
    smart.initialize()
    intelligence = DocumentIntelligence(store)
    intelligence.initialize()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                cloud_smart=smart,
                cloud_store=store,
                document_intelligence=intelligence,
                ai_router=NoAI(),
            )
        )
    )
    return store, smart, request


def test_weekend_work_intent_is_detected() -> None:
    assert is_weekend_work_request(
        "Напиши работу в выходной день водителю Иванову на 23 число."
    )
    assert not is_weekend_work_request("Покажи договоры за октябрь.")


@pytest.mark.asyncio
async def test_weekend_work_chat_action_creates_month_folder_and_document(
    tmp_path: Path,
) -> None:
    store, smart, request = _stack(tmp_path)
    employee = smart.create_employee(
        {
            "full_name": "Иванов Иван Иванович",
            "personnel_number": "T-001",
            "position": "Водитель",
            "department": "Гараж",
        }
    )
    smart.create_vehicle(
        {
            "garage_number": "7",
            "plate_number": "А123АА77",
            "make_model": "ГАЗ",
            "driver_employee_id": employee["id"],
        }
    )

    created = await create_weekend_work_document(
        request=request,
        message=(
            "Напиши работу в выходной день водителю Иванов "
            "на 23.10.2026 на 8 часов."
        ),
    )

    assert created["work_date"] == "2026-10-23"
    assert created["work_hours"] == 8
    assert created["employee"]["id"] == employee["id"]
    assert created["vehicle"]["garage_number"] == "7"
    assert created["path"].startswith(
        "Служебные записки / 2026 год / Октябрь / Работа выходной /"
    )

    dna = smart.get_dna(created["document_id"])
    assert dna["kind"] == "служебная записка"
    assert dna["document_subtype"] == "Работа в выходной день"
    assert dna["employee_name"] == "Иванов Иван Иванович"
    assert dna["work_hours"] == 8

    root = store.list_folders(parent_id=None)
    service = next(item for item in root if item["name"] == "Служебные записки")
    year = next(
        item
        for item in store.list_folders(parent_id=service["id"])
        if item["name"] == "2026 год"
    )
    month = next(
        item
        for item in store.list_folders(parent_id=year["id"])
        if item["name"] == "Октябрь"
    )
    weekend = next(
        item
        for item in store.list_folders(parent_id=month["id"])
        if item["name"] == "Работа выходной"
    )
    documents = store.list_documents(folder_id=weekend["id"])
    assert documents[0]["id"] == created["document_id"]
