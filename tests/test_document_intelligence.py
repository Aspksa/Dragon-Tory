import hashlib
from pathlib import Path

from tooru.cloud.document_intelligence import DocumentIntelligence
from tooru.cloud.smart import SmartDrive
from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault


def _stack(
    tmp_path: Path,
) -> tuple[CloudStore, SmartDrive, DocumentIntelligence]:
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
    return store, smart, intelligence


def _upload(store: CloudStore, name: str, content: bytes) -> dict:
    temp = store.incoming_dir / (name + ".upload")
    temp.write_bytes(content)
    return store.register_upload(
        temp,
        name=name,
        content_type="text/plain",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_document_intelligence_extracts_entities_deadlines_and_tags(
    tmp_path: Path,
) -> None:
    store, smart, intelligence = _stack(tmp_path)
    text = (
        "ДОГОВОР № ABC-123\n"
        "Автомобиль VIN JF1SJABC1GH123456.\n"
        "Договор действует до 14.11.2027.\n"
        "Стоимость услуг: € 1250,00.\n"
        "Контакт: owner@example.com\n"
    ).encode()
    document = _upload(store, "Договор Subaru.txt", text)
    store.update_passport(
        document["id"],
        ai_access="read",
        confidentiality="personal",
    )
    smart.reconcile_contract(document["id"])

    result = intelligence.analyze(document["id"])
    assert result["kind"] == "договор"
    assert result["ocr_used"] is False
    assert "JF1SJABC1GH123456" in result["entities"]["vin"]
    assert "14.11.2027" in result["entities"]["dates"]
    assert any(
        item["currency"] == "EUR" and item["value"] == 1250.0
        for item in result["entities"]["amounts"]
    )
    assert result["deadlines"]
    assert "договор" in result["suggested_tags"]

    search = intelligence.smart_search("2027 больше €500")
    assert any(item["document_id"] == document["id"] for item in search)

    collections = intelligence.smart_collections()
    assert any(
        item["id"] == "kind:договор" and item["count"] == 1
        for item in collections
    )


def test_intelligence_suggestions_do_not_change_file_bytes(
    tmp_path: Path,
) -> None:
    store, smart, intelligence = _stack(tmp_path)
    content = b"invoice number INV-42\nPayment due 2027-12-01\nEUR 900"
    document = _upload(store, "invoice.txt", content)
    store.update_passport(
        document["id"],
        ai_access="read",
        confidentiality="personal",
    )
    smart.reconcile_contract(document["id"])
    before = store.content_path(document["id"]).read_bytes()

    intelligence.analyze(document["id"])
    applied = intelligence.apply_suggestions(document["id"])
    smart.update_dna(document["id"], {"kind": applied["kind"]})

    assert store.content_path(document["id"]).read_bytes() == before
    current = store.get(document["id"])
    assert current["tags"]
    assert smart.get_dna(document["id"])["kind"] == "счёт-оферта"


def test_local_version_diff_detects_dates_and_amounts(
    tmp_path: Path,
) -> None:
    store, smart, intelligence = _stack(tmp_path)
    first = (
        "Договор действует до 14.11.2027.\n"
        "Стоимость: EUR 1000.\n"
        "Условие первой версии документа."
    ).encode()
    document = _upload(store, "version-contract.txt", first)
    store.update_passport(
        document["id"],
        ai_access="full",
        confidentiality="personal",
    )
    smart.reconcile_contract(document["id"])

    second = (
        "Договор действует до 14.11.2028.\n"
        "Стоимость: EUR 1500.\n"
        "Условие второй версии документа существенно изменено."
    ).encode()
    temp = store.incoming_dir / "version-two.upload"
    temp.write_bytes(second)
    updated = store.add_version(
        document["id"],
        temp,
        name="version-contract.txt",
        content_type="text/plain",
        size_bytes=len(second),
        sha256=hashlib.sha256(second).hexdigest(),
    )
    assert updated["version"] == 2

    diff = intelligence.local_version_diff(
        document["id"],
        1,
        2,
    )
    assert "14.11.2028" in diff["dates_added"]
    assert "14.11.2027" in diff["dates_removed"]
    assert {
        "currency": "EUR",
        "value": 1500.0,
    } in diff["amounts_added"]
    assert {
        "currency": "EUR",
        "value": 1000.0,
    } in diff["amounts_removed"]
    assert diff["sha256_a"] != diff["sha256_b"]


def test_ocr_status_is_local_and_never_implies_external_ai(
    tmp_path: Path,
) -> None:
    _, _, intelligence = _stack(tmp_path)
    status = intelligence.ocr_status()
    assert status["local_only"] is True
    assert status["external_ai_used"] is False
    assert isinstance(status["available"], bool)


def test_specialized_document_modules_are_separate(tmp_path: Path) -> None:
    store, smart, intelligence = _stack(tmp_path)

    invoice_offer = _upload(
        store,
        "invoice-offer.txt",
        (
            "Счёт-оферта №154\n"
            "Поставщик: ООО Ромашка\n"
            "Цена EUR 300. Условия оплаты: в течение 10 дней.\n"
            "Оферта действует до 01.12.2027."
        ).encode(),
    )
    memo = _upload(
        store,
        "memo.txt",
        "Служебная записка\nКому: Руководителю\nОт кого: Отдел ИТ\n"
        "Исполнить до 15.12.2027.".encode(),
    )
    for document in (invoice_offer, memo):
        store.update_passport(
            document["id"],
            ai_access="read",
            confidentiality="personal",
        )
        smart.reconcile_contract(document["id"])
        result = intelligence.analyze(document["id"])
        smart.apply_intelligence_defaults(document["id"], result)

    invoice_offers = intelligence.module_profile("invoice_offers")
    memos = intelligence.module_profile("memos")

    assert {item["id"] for item in invoice_offers["items"]} == {
        invoice_offer["id"]
    }
    assert {item["id"] for item in memos["items"]} == {memo["id"]}
    assert invoice_offers["ai_focus"]
    assert memos["ai_focus"]


def test_orders_directives_and_weekend_work_are_recognized(
    tmp_path: Path,
) -> None:
    store, smart, intelligence = _stack(tmp_path)

    order = _upload(
        store,
        "order.txt",
        "ПРИКАЗ № 17\nПРИКАЗЫВАЮ:\n1. Назначить ответственного.".encode(),
    )
    directive = _upload(
        store,
        "directive.txt",
        (
            "РАСПОРЯЖЕНИЕ № 5\nРАСПОРЯЖАЮСЬ:\n"
            "Выполнить проверку до 20.10.2026."
        ).encode(),
    )
    weekend = _upload(
        store,
        "weekend-memo.txt",
        (
            "Служебная записка\n"
            "Работа в выходной день: 03.10.2026\n"
            "Сотрудник: Иванов И.И.\n"
            "Подразделение: ИТ\n"
            "Количество часов: 8\n"
        ).encode(),
    )

    results = {}
    for document in (order, directive, weekend):
        store.update_passport(
            document["id"],
            ai_access="read",
            confidentiality="personal",
        )
        smart.reconcile_contract(document["id"])
        analysis = intelligence.analyze(document["id"])
        smart.apply_intelligence_defaults(document["id"], analysis)
        results[document["id"]] = analysis

    assert results[order["id"]]["kind"] == "приказ"
    assert results[directive["id"]]["kind"] == "распоряжение"
    assert intelligence.module_profile("orders")["count"] == 1
    assert intelligence.module_profile("directives")["count"] == 1

    weekend_dna = smart.get_dna(weekend["id"])
    assert weekend_dna["document_subtype"] == "Работа в выходной день"
    assert weekend_dna["employee_name"] == "Иванов И.И"
    assert weekend_dna["department"] == "ИТ"
    assert weekend_dna["work_date"] == "2026-10-03"
    assert weekend_dna["work_hours"] == 8
