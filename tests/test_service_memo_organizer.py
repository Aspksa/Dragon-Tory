from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tooru.ai.router import AIRouter
from tooru.cloud.document_intelligence import DocumentIntelligence
from tooru.cloud.memo_organizer import ServiceMemoOrganizer
from tooru.cloud.smart import SmartDrive
from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault
from tooru.memory.embedding import HashEmbeddingProvider
from tooru.memory.engine import MemoryEngine
from tooru.memory.guardian import GuardianConfig, MemoryGuardian
from tooru.memory.intake import MemoryIntakeGateway
from tooru.memory.intelligence import IntelligenceConfig, MemoryIntelligence
from tooru.memory.store import SQLiteMemoryStore


def _stack(tmp_path: Path):
    root = tmp_path / "cloud"
    store = CloudStore(
        root,
        root / "tooru_cloud.sqlite3",
        vault=ToryVault(root / "vault.json"),
    )
    store.initialize()
    smart = SmartDrive(store)
    smart.initialize()
    intelligence = DocumentIntelligence(store)
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
    organizer = ServiceMemoOrganizer(
        cloud_store=store,
        smart=smart,
        intelligence=intelligence,
        memory_intake=MemoryIntakeGateway(guardian),
    )
    organizer.initialize()
    return store, smart, intelligence, organizer


def _upload(store: CloudStore, name: str, text: str) -> dict:
    content = text.encode("utf-8")
    temp = store.incoming_dir / (name + ".upload")
    temp.write_bytes(content)
    return store.register_upload(
        temp,
        name=name,
        content_type="text/plain",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _prepare_memo(
    store: CloudStore,
    smart: SmartDrive,
    intelligence: DocumentIntelligence,
    document: dict,
) -> dict:
    store.update_passport(
        document["id"],
        ai_access="memory",
        confidentiality="personal",
        scope="project",
        project_id="dragon-tory",
    )
    smart.reconcile_contract(document["id"])
    smart.update_dna(
        document["id"],
        {"kind": "служебная записка"},
    )
    analysis = intelligence.analyze(document["id"])
    smart.apply_intelligence_defaults(document["id"], analysis)
    return analysis


def test_service_memo_uses_document_year_not_event_year_and_sorts_by_topic(
    tmp_path: Path,
) -> None:
    store, smart, intelligence, organizer = _stack(tmp_path)
    text = (
        "СЛУЖЕБНАЯ ЗАПИСКА № 12 от 15.05.2020\n"
        "Организация: ООО Тест\n"
        "Подразделение: Гараж\n"
        "От кого: Иванов И.И.\n"
        "Кому: Директору\n"
        "Тема: Надбавка водителю\n"
        "Сотрудник: Петров П.П.\n"
        "Прошу установить надбавку на 2021 год.\n"
        "Автомобиль А123АА77 требует дополнительного обслуживания.\n"
        "Контрагент: ООО Ромашка\n"
        "Стоимость услуг 10 000 RUB, в том числе НДС 20%.\n"
        "Основание: договор № D-17.\n"
    )
    document = _upload(store, "СЗ надбавка 2020.txt", text)
    original = store.content_path(document["id"]).read_bytes()
    _prepare_memo(store, smart, intelligence, document)

    card = organizer.process(document["id"])

    assert card["document_year"] == "2020"
    assert card["year_source"] == "document_date"
    assert card["topic"] == "Надбавки и доплаты"
    assert (
        card["folder_path"]
        == "Dragon Tory / Документы / 2020 / Служебные записки / Надбавки и доплаты"
    )
    assert card["facts"]["document_number"]["value"] == "12"
    assert "15.05.2020" in card["facts"]["document_date"]["value"]
    assert card["facts"]["requested_action"]["value"] != "не указано"
    assert card["facts"]["confirmed_result"]["value"] == "не указано"
    assert any(
        "подтверждённый результат" in item
        for item in card["review"]
    )
    assert card["facts"]["vehicles"]["value"] != "не указано"
    assert card["facts"]["amounts_and_vat"]["value"] != "не указано"
    assert store.content_path(document["id"]).read_bytes() == original
    assert store.get(document["id"])["folder_id"] == card["folder_id"]


def test_service_memo_year_can_fall_back_to_filename_with_review(
    tmp_path: Path,
) -> None:
    store, smart, intelligence, organizer = _stack(tmp_path)
    document = _upload(
        store,
        "СЗ командировка 2024.txt",
        (
            "Служебная записка\n"
            "Тема: Командировка сотрудника\n"
            "Прошу направить сотрудника в командировку."
        ),
    )
    _prepare_memo(store, smart, intelligence, document)

    card = organizer.process(document["id"])

    assert card["document_year"] == "2024"
    assert card["year_source"] == "filename"
    assert card["topic"] == "Командировки"
    assert any("названию файла" in item for item in card["review"])


def test_service_memo_template_goes_to_template_folder_without_memory(
    tmp_path: Path,
) -> None:
    store, smart, intelligence, organizer = _stack(tmp_path)
    document = _upload(
        store,
        "Шаблон служебной записки.txt",
        (
            "Служебная записка\n"
            "Дата: [ДАТА]\n"
            "От кого: [ФИО]\n"
            "Кому: [ФИО]\n"
            "Тема: [ТЕМА]\n"
        ),
    )
    _prepare_memo(store, smart, intelligence, document)

    card = organizer.process(document["id"])

    assert card["is_template"] is True
    assert (
        card["folder_path"]
        == "Dragon Tory / Шаблоны / Служебные записки"
    )
    assert card["memory_status"] == "template"
    assert card["memory_id"] is None


def test_identical_service_memo_is_linked_as_copy_without_second_memory(
    tmp_path: Path,
) -> None:
    store, smart, intelligence, organizer = _stack(tmp_path)
    text = (
        "Служебная записка № 9 от 01.09.2026\n"
        "Тема: Ремонт автомобиля\n"
        "Прошу выполнить ремонт автомобиля А123АА77."
    )
    first = _upload(store, "memo-first.txt", text)
    _prepare_memo(store, smart, intelligence, first)
    first_card = organizer.process(first["id"])

    second = _upload(store, "memo-copy.txt", text)
    _prepare_memo(store, smart, intelligence, second)
    second_card = organizer.process(second["id"])

    assert first_card["duplicate_of"] is None
    assert second_card["duplicate_of"] == first["id"]
    assert second_card["memory_status"] == "duplicate"
    assert second_card["memory_id"] is None


def test_memo_rule_rejects_non_memo_document(tmp_path: Path) -> None:
    store, smart, intelligence, organizer = _stack(tmp_path)
    document = _upload(
        store,
        "contract.txt",
        "Договор № 1\nПредмет договора: поставка товара.",
    )
    store.update_passport(
        document["id"],
        ai_access="read",
        confidentiality="personal",
    )
    smart.reconcile_contract(document["id"])
    intelligence.analyze(document["id"])

    with pytest.raises(ValueError, match="только к служебным запискам"):
        organizer.process(document["id"])



def test_service_memo_respects_read_only_memory_permission(
    tmp_path: Path,
) -> None:
    store, smart, intelligence, organizer = _stack(tmp_path)
    document = _upload(
        store,
        "memo-read-only.txt",
        (
            "Служебная записка № 5 от 10.10.2026\n"
            "Тема: Командировка сотрудника\n"
            "Прошу направить сотрудника в командировку."
        ),
    )
    store.update_passport(
        document["id"],
        ai_access="read",
        confidentiality="personal",
        scope="project",
        project_id="dragon-tory",
    )
    smart.reconcile_contract(document["id"])
    smart.update_dna(
        document["id"],
        {"kind": "служебная записка"},
    )
    analysis = intelligence.analyze(document["id"])
    smart.apply_intelligence_defaults(document["id"], analysis)

    card = organizer.process(document["id"])

    assert card["memory_status"] == "permission-denied"
    assert card["memory_id"] is None
    assert any(
        "не разрешает запись в память" in item
        for item in card["review"]
    )
