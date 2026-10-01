from fastapi.testclient import TestClient

from tooru.main import app


def _project_memory_search(client: TestClient, query: str) -> list[dict]:
    response = client.post(
        "/v1/memory/search",
        json={
            "scope": "project",
            "project_id": "dragon-tory",
            "query": query,
            "limit": 20,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_garage_change_auto_syncs_project_memory() -> None:
    with TestClient(app) as client:
        employee = client.post(
            "/v1/cloud/smart/employees",
            json={
                "full_name": "Автотест Синхронизация Гаража",
                "position": "Водитель",
            },
        )
        assert employee.status_code == 201

        vehicle = client.post(
            "/v1/cloud/smart/garage",
            json={
                "garage_number": "AUTO-4242",
                "plate_number": "AUTO4242",
                "make_model": "Dragon Tory Test Car",
                "driver_employee_id": employee.json()["id"],
            },
        )
        assert vehicle.status_code == 201
        vehicle_id = vehicle.json()["id"]

        memories = _project_memory_search(client, "AUTO4242")

    assert any(
        item["source"] == "tooru-garage-auto-sync"
        and item["source_ref"] == vehicle_id
        for item in memories
    )


def test_weekend_work_dna_auto_syncs_timesheet_memory() -> None:
    marker = "AUTO-SYNC-WEEKEND-4242"
    with TestClient(app) as client:
        uploaded = client.post(
            "/v1/cloud/files?name=auto-sync-weekend.txt",
            content=b"weekend work auto sync test",
            headers={"Content-Type": "text/plain"},
        )
        assert uploaded.status_code == 201
        document_id = uploaded.json()["id"]

        dna = client.patch(
            f"/v1/cloud/smart/files/{document_id}/dna",
            json={
                "kind": "служебная записка",
                "document_subtype": "Работа в выходной день",
                "employee_name": "Автотест Табеля",
                "department": "Тест",
                "work_date": "2026-10-24",
                "work_hours": 8,
                "work_reason": marker,
            },
        )
        assert dna.status_code == 200

        memories = _project_memory_search(client, marker)
        client.delete(f"/v1/cloud/files/{document_id}")

    assert any(
        item["source"] == "tooru-timesheet-auto-sync"
        and item["source_ref"] == document_id
        for item in memories
    )
