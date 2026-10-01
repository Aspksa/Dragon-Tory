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


def test_employee_and_garage_directories_link_driver(
    tmp_path: Path,
) -> None:
    _, smart = _stack(tmp_path)
    employee = smart.create_employee(
        {
            "full_name": "Иванов Иван Иванович",
            "personnel_number": "T-001",
            "position": "Водитель",
            "department": "Транспортный отдел",
            "driver_license": "77 00 123456",
        }
    )
    vehicle = smart.create_vehicle(
        {
            "garage_number": "12",
            "plate_number": "А123АА77",
            "vin": "JF1SJABC1GH123456",
            "make_model": "Subaru Forester",
            "driver_employee_id": employee["id"],
        }
    )

    assert employee["position"] == "Водитель"
    assert vehicle["driver_employee_id"] == employee["id"]
    assert vehicle["driver_name"] == "Иванов Иван Иванович"

    listed = smart.list_vehicles(query="Иванов")
    assert len(listed) == 1
    assert listed[0]["vin"] == "JF1SJABC1GH123456"



def test_monthly_timesheet_combines_calendar_manual_absence_and_weekend_work(
    tmp_path: Path,
) -> None:
    store, smart = _stack(tmp_path)
    memo = _upload(store, "weekend.txt", b"weekend work")
    smart.update_dna(
        memo["id"],
        {
            "kind": "служебная записка",
            "document_subtype": "Работа в выходной день",
            "employee_name": "Иванов И.И.",
            "department": "ИТ",
            "work_date": "2026-05-16",
            "work_hours": 6,
            "work_reason": "Плановые работы",
        },
    )
    vacation = smart.create_timesheet_manual_entry(
        {
            "employee_name": "Иванов И.И.",
            "date_from": "2026-05-01",
            "date_to": "2026-05-05",
            "code": "ОТ",
            "note": "Отпуск введён вручную",
        }
    )
    sick = smart.create_timesheet_manual_entry(
        {
            "employee_name": "Петров П.П.",
            "date_from": "2026-05-14",
            "date_to": "2026-05-16",
            "code": "Б",
        }
    )

    data = smart.monthly_timesheet(year=2026, month=5)
    assert data["calendar"]["summary"]["workdays"] == 19
    assert data["calendar"]["summary"]["norm_hours"] == 151.0
    assert data["row_count"] == 2

    ivanov = next(
        row for row in data["rows"]
        if row["employee_name"] == "Иванов И.И."
    )
    # 1 May is an official holiday and is not counted as annual leave.
    assert ivanov["cells"][0]["code"] == "В"
    assert ivanov["cells"][1]["code"] == "ОТ"
    assert ivanov["cells"][15]["code"] == "РВ"
    assert ivanov["cells"][15]["hours"] == 6
    assert ivanov["weekend_work_hours"] == 6

    petrov = next(
        row for row in data["rows"]
        if row["employee_name"] == "Петров П.П."
    )
    assert petrov["cells"][13]["code"] == "Б"
    assert petrov["cells"][15]["code"] == "Б"
    assert petrov["sick_days"] == 3

    smart.delete_timesheet_manual_entry(vacation["id"])
    smart.delete_timesheet_manual_entry(sick["id"])


def test_monthly_timesheet_flags_manual_absence_weekend_work_conflict(
    tmp_path: Path,
) -> None:
    store, smart = _stack(tmp_path)
    memo = _upload(store, "weekend.txt", b"weekend work")
    smart.update_dna(
        memo["id"],
        {
            "kind": "служебная записка",
            "document_subtype": "Работа в выходной день",
            "employee_name": "Иванов И.И.",
            "work_date": "2026-10-03",
            "work_hours": 8,
        },
    )
    smart.create_timesheet_manual_entry(
        {
            "employee_name": "Иванов И.И.",
            "date_from": "2026-10-03",
            "date_to": "2026-10-03",
            "code": "Б",
        }
    )

    data = smart.monthly_timesheet(year=2026, month=10)

    assert len(data["conflicts"]) == 1
    row = data["rows"][0]
    assert row["cells"][2]["code"] == "Б"


def test_garage_stores_fuel_tires_and_insurance_alerts(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    _, smart = _stack(tmp_path)
    today = datetime.now(UTC).date()
    end = today + timedelta(days=10)
    vehicle = smart.create_vehicle(
        {
            "garage_number": "12",
            "plate_number": "А123АА77",
            "vin": "JF1SJABC1GH123456",
            "make_model": "Subaru Forester",
            "fuel_type": "АИ-95",
            "fuel_rate_summer": 10.5,
            "fuel_rate_winter": 12.2,
            "tire_size_summer": "225/60 R17",
            "tire_size_winter": "225/60 R17",
            "insurance_type": "ОСАГО",
            "insurance_policy": "ХХХ 1234567890",
            "insurance_company": "Страховая компания",
            "insurance_start": today.isoformat(),
            "insurance_end": end.isoformat(),
        }
    )

    assert vehicle["fuel_rate_summer"] == 10.5
    assert vehicle["fuel_rate_winter"] == 12.2
    assert vehicle["tire_size_summer"] == "225/60 R17"
    assert vehicle["insurance_days_left"] == 10
    assert vehicle["insurance_alert"] is True
    assert vehicle["insurance_expired"] is False

    alerts = smart.garage_alerts(days=15)
    assert len(alerts) == 1
    assert alerts[0]["id"] == vehicle["id"]


def test_garage_marks_expired_insurance(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    _, smart = _stack(tmp_path)
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    vehicle = smart.create_vehicle(
        {
            "garage_number": "99",
            "make_model": "Test Car",
            "insurance_end": yesterday.isoformat(),
        }
    )

    assert vehicle["insurance_expired"] is True
    assert vehicle["insurance_alert"] is False
    alerts = smart.garage_alerts(days=15)
    assert alerts[0]["insurance_expired"] is True



def test_annual_leave_excludes_holiday_but_includes_shifted_day_off(
    tmp_path: Path,
) -> None:
    _, smart = _stack(tmp_path)
    smart.create_timesheet_manual_entry(
        {
            "employee_name": "Сидоров С.С.",
            "date_from": "2026-03-08",
            "date_to": "2026-03-09",
            "code": "ОТ",
        }
    )

    data = smart.monthly_timesheet(year=2026, month=3)
    row = next(
        item
        for item in data["rows"]
        if item["employee_name"] == "Сидоров С.С."
    )

    assert row["cells"][7]["code"] == "В"
    assert row["cells"][8]["code"] == "ОТ"
    assert row["vacation_days"] == 1



def test_weekend_timesheet_expands_multiple_work_dates(
    tmp_path: Path,
) -> None:
    store, smart = _stack(tmp_path)
    memo = _upload(store, "weekend-multi.txt", b"weekend multi")
    dna = smart.update_dna(
        memo["id"],
        {
            "kind": "служебная записка",
            "document_subtype": "Работа в выходной день",
            "employee_name": "Матиенко А.Н.",
            "work_dates": ["2026-03-21", "2026-03-22"],
            "work_hours": 8,
        },
    )

    assert dna["work_dates"] == ["2026-03-21", "2026-03-22"]

    timesheet = smart.weekend_timesheet(year=2026, month=3)
    assert timesheet["count"] == 2
    assert [item["work_date"] for item in timesheet["items"]] == [
        "2026-03-21",
        "2026-03-22",
    ]
    assert timesheet["total_hours"] == 16


def test_intelligence_date_conflict_is_not_added_to_timesheet(
    tmp_path: Path,
) -> None:
    store, smart = _stack(tmp_path)
    memo = _upload(store, "СЗ раб.вых. день 24-25.01.2026.txt", b"memo")

    result = smart.apply_intelligence_defaults(
        memo["id"],
        {
            "kind": "служебная записка",
            "confidence": 0.95,
            "entities": {
                "references": [],
                "amounts": [],
                "counterparties": [],
                "employees": ["Кихтев Мстислав Юрьевич"],
                "departments": [],
                "work_dates": [],
                "work_hours": [],
                "weekend_work_detected": True,
                "work_date_conflict": True,
                "work_date_source": "conflict",
                "work_dates_body": ["2025-12-24", "2025-12-25"],
                "work_dates_filename": ["2026-01-24", "2026-01-25"],
            },
            "deadlines": [],
            "suggested_tags": ["служебная записка"],
        },
    )

    assert result["applied"] is True
    dna = smart.get_dna(memo["id"])
    assert dna["document_subtype"] == "Работа в выходной день"
    assert dna["work_date_conflict"] is True
    assert dna["work_dates"] == []

    timesheet = smart.weekend_timesheet(year=2026, month=1)
    assert timesheet["items"] == []
    assert timesheet["date_conflicts"][0]["document_id"] == memo["id"]

    resolved = smart.update_dna(
        memo["id"],
        {
            "work_dates": ["2026-01-24", "2026-01-25"],
        },
    )
    assert resolved["work_date_conflict"] is False
    assert resolved["work_date_source"] == "manual"
