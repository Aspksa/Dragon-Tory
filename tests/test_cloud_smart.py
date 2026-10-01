import hashlib
from pathlib import Path

from tooru.cloud.smart import SmartDrive
from tooru.cloud.store import CloudStore
from tooru.cloud.vault import ToryVault


def _stack(tmp_path: Path) -> tuple[CloudStore, SmartDrive]:
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
    return store, smart


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


def test_ai_contract_syncs_with_legacy_and_supports_one_time_access(
    tmp_path: Path,
) -> None:
    store, smart = _stack(tmp_path)
    document = _upload(store, "contract.txt", b"contract")

    initial = smart.get_contract(document["id"])
    assert initial["content_read"] is False
    assert initial["answer"] is False

    store.update_passport(
        document["id"],
        ai_access="read",
        confidentiality="personal",
    )
    synced = smart.reconcile_contract(document["id"])
    assert synced["content_read"] is True
    assert synced["answer"] is False

    contract = smart.update_contract(
        document["id"],
        {
            "metadata_search": True,
            "content_read": True,
            "answer": True,
            "external_ai": True,
            "clean_room": True,
            "one_time_answer": True,
        },
    )
    assert contract["clean_room"] is True
    assert store.get(document["id"])["ai_access"] == "answer"

    assert smart.consume_one_time_answer(document["id"]) is True
    consumed = smart.get_contract(document["id"])
    assert consumed["answer"] is False
    assert consumed["external_ai"] is False
    assert consumed["one_time_answer"] is False
    assert store.get(document["id"])["ai_access"] == "read"


def test_confidential_contract_blocks_external_ai(tmp_path: Path) -> None:
    store, smart = _stack(tmp_path)
    document = _upload(store, "confidential.txt", b"secret")
    store.update_passport(
        document["id"],
        ai_access="read",
        confidentiality="confidential",
    )
    smart.reconcile_contract(document["id"])

    try:
        smart.update_contract(
            document["id"],
            {
                "metadata_search": True,
                "content_read": True,
                "answer": True,
                "external_ai": True,
            },
        )
    except ValueError as exc:
        assert "Конфиденциальный" in str(exc)
    else:
        raise AssertionError("External AI must be blocked for confidential files.")


def test_relations_knowledge_card_and_watchers(tmp_path: Path) -> None:
    store, smart = _stack(tmp_path)
    first = _upload(store, "contract.txt", b"a")
    second = _upload(store, "invoice.txt", b"b")
    store.update_document(first["id"], tags=["Subaru", "2026"])
    store.update_document(second["id"], tags=["Subaru"])

    relation = smart.add_relation(
        first["id"],
        second["id"],
        "supports",
        "Счёт подтверждает договор",
    )
    assert relation["relation_type"] == "supports"

    card = smart.knowledge_card(first["id"])
    assert card["relations"][0]["target_id"] == second["id"]
    assert any(
        item["document_id"] == second["id"]
        for item in card["relation_suggestions"]
    )

    smart.create_watch(first["id"], "version_changed")
    alerts = smart.emit_event(
        first["id"],
        "version_changed",
        details={"version": 2},
    )
    assert alerts
    assert smart.alerts()[0]["document_id"] == first["id"]
    assert smart.resolve_alert(alerts[0]["id"]) is True


def test_time_machine_restores_metadata_and_version_but_not_security(
    tmp_path: Path,
) -> None:
    store, smart = _stack(tmp_path)
    original = b"version one"
    second = b"version two"
    document = _upload(store, "history.txt", original)
    snapshot = smart.create_snapshot("До изменений")

    store.update_document(
        document["id"],
        name="renamed.txt",
        favorite=True,
    )
    temp = store.incoming_dir / "second.upload"
    temp.write_bytes(second)
    store.add_version(
        document["id"],
        temp,
        name="history.txt",
        content_type="text/plain",
        size_bytes=len(second),
        sha256=hashlib.sha256(second).hexdigest(),
    )
    store.update_passport(
        document["id"],
        ai_access="read",
        confidentiality="confidential",
    )
    smart.reconcile_contract(document["id"])

    restored = smart.restore_snapshot(snapshot["id"])
    assert restored["security_policy_preserved"] is True
    current = store.get(document["id"])
    assert current["name"] == "history.txt"
    assert current["favorite"] is False
    assert current["version"] == 3
    assert current["confidentiality"] == "confidential"
    assert store.content_path(document["id"]).read_bytes() == original


def test_local_ed25519_seal_survives_rename_and_detects_file_change(
    tmp_path: Path,
) -> None:
    store, smart = _stack(tmp_path)
    content = b"signed content"
    document = _upload(store, "signed.txt", content)

    seal = smart.seal(document["id"])
    assert seal["identity_scope"] == "local_dragon_tory_installation"

    store.update_document(document["id"], name="renamed-signed.txt")
    verified = smart.verify_seal(document["id"])
    assert verified["ok"] is True
    assert verified["signature_valid"] is True
    assert verified["storage_verified"] is True

    store.content_path(document["id"]).write_bytes(b"tampered")
    failed = smart.verify_seal(document["id"])
    assert failed["ok"] is False
    assert failed["storage_verified"] is False


def test_dna_and_timeline_are_separate_from_file_bytes(tmp_path: Path) -> None:
    store, smart = _stack(tmp_path)
    content = b"document bytes never changed"
    document = _upload(store, "dna.txt", content)
    before = store.content_path(document["id"]).read_bytes()

    dna = smart.update_dna(
        document["id"],
        {
            "kind": "договор",
            "origin": "email import",
            "external_ref": "AGREEMENT-42",
            "important_date": "2027-11-14",
            "language": "ru",
        },
    )
    assert dna["kind"] == "договор"
    assert store.content_path(document["id"]).read_bytes() == before
    assert any(
        item["event"] == "dna_updated"
        for item in smart.timeline(document["id"])
    )


def test_intelligence_autofill_never_overwrites_manual_dna(tmp_path: Path) -> None:
    store, smart = _stack(tmp_path)
    document = _upload(store, "manual.txt", b"manual content")
    smart.update_dna(
        document["id"],
        {
            "kind": "мой ручной тип",
            "external_ref": "MANUAL-REF",
            "important_date": "2030-01-01",
        },
    )

    result = smart.apply_intelligence_defaults(
        document["id"],
        {
            "kind": "договор",
            "confidence": 0.98,
            "entities": {"references": ["AUTO-42"]},
            "deadlines": [{"date": "2027-11-14"}],
            "suggested_tags": ["договор", "2027"],
        },
    )

    dna = smart.get_dna(document["id"])
    assert dna["kind"] == "мой ручной тип"
    assert dna["external_ref"] == "MANUAL-REF"
    assert dna["important_date"] == "2030-01-01"
    assert "договор" in store.get(document["id"])["tags"]
    assert result["applied"] is True
    assert "kind" not in result["fields"]
    assert "external_ref" not in result["fields"]
    assert "important_date" not in result["fields"]


def test_contract_business_fields_and_counterparty_are_preserved(
    tmp_path: Path,
) -> None:
    store, smart_drive = _stack(tmp_path)
    first = _upload(store, "contract-1.txt", b"contract one")
    second = _upload(store, "contract-2.txt", b"contract two")

    for document, number, amount in (
        (first, "D-001", 125000.0),
        (second, "D-002", 98000.0),
    ):
        dna = smart_drive.update_dna(
            document["id"],
            {
                "kind": "договор",
                "counterparty": "ООО Ромашка",
                "document_number": number,
                "document_date": "01.10.2026",
                "amount_value": amount,
                "amount_currency": "RUB",
            },
        )
        assert dna["counterparty"] == "ООО Ромашка"
        assert dna["document_number"] == number
        assert dna["amount_value"] == amount
        assert dna["amount_currency"] == "RUB"


def test_counterparty_directory_links_many_documents(tmp_path: Path) -> None:
    store, smart_drive = _stack(tmp_path)
    counterparty = smart_drive.create_counterparty(
        {
            "name": "ООО Ромашка",
            "short_name": "Ромашка",
            "inn": "7700000000",
            "kpp": "770001001",
            "bank_name": "Банк Тест",
            "bik": "044525000",
            "settlement_account": "40702810000000000001",
        }
    )
    first = _upload(store, "contract-a.txt", b"a")
    second = _upload(store, "contract-b.txt", b"b")

    for document, number in ((first, "D-1"), (second, "D-2")):
        dna = smart_drive.update_dna(
            document["id"],
            {
                "kind": "договор",
                "counterparty_id": counterparty["id"],
                "document_number": number,
                "amount_value": 1000,
                "amount_currency": "RUB",
            },
        )
        assert dna["counterparty_id"] == counterparty["id"]
        assert dna["counterparty"] == "ООО Ромашка"

    current = smart_drive.get_counterparty(counterparty["id"])
    assert current["document_count"] == 2

    updated = smart_drive.update_counterparty(
        counterparty["id"],
        {
            **current,
            "name": "ООО Ромашка Групп",
        },
    )
    assert updated["name"] == "ООО Ромашка Групп"
    assert smart_drive.get_dna(first["id"])["counterparty"] == (
        "ООО Ромашка Групп"
    )


def test_weekend_work_timesheet_is_built_from_service_memos(
    tmp_path: Path,
) -> None:
    store, smart_drive = _stack(tmp_path)
    memo = _upload(store, "weekend.txt", b"weekend work")
    dna = smart_drive.update_dna(
        memo["id"],
        {
            "kind": "служебная записка",
            "document_subtype": "Работа в выходной день",
            "employee_name": "Иванов И.И.",
            "department": "ИТ",
            "work_date": "03.10.2026",
            "work_hours": 8,
            "work_reason": "Обновление серверов",
        },
    )
    assert dna["work_date"] == "2026-10-03"

    timesheet = smart_drive.weekend_timesheet(
        year=2026,
        month=10,
    )
    assert timesheet["count"] == 1
    assert timesheet["total_hours"] == 8
    assert timesheet["items"][0]["employee_name"] == "Иванов И.И."
