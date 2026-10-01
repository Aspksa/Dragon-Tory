from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from tooru.main import app


def test_timesheet_calendar_and_manual_entry_api() -> None:
    name = "Табель API " + uuid4().hex[:8]
    with TestClient(app) as client:
        calendar = client.get(
            "/v1/cloud/smart/timesheet/calendar",
            params={"year": 2027, "month": 2},
        )
        assert calendar.status_code == 200
        payload = calendar.json()
        assert payload["official"] is True
        days = {item["date"]: item for item in payload["days"]}
        assert days["2027-02-20"]["is_workday"] is True
        assert days["2027-02-20"]["is_short_day"] is True
        assert days["2027-02-22"]["is_workday"] is False

        created = client.post(
            "/v1/cloud/smart/timesheet/manual",
            json={
                "employee_name": name,
                "date_from": "2027-02-24",
                "date_to": "2027-02-25",
                "code": "ОТ",
                "note": "API test",
            },
        )
        assert created.status_code == 201
        entry_id = created.json()["id"]

        month = client.get(
            "/v1/cloud/smart/timesheet/month",
            params={"year": 2027, "month": 2},
        )
        assert month.status_code == 200
        row = next(
            item
            for item in month.json()["rows"]
            if item["employee_name"] == name
        )
        assert row["cells"][23]["code"] == "ОТ"
        assert row["cells"][24]["code"] == "ОТ"

        deleted = client.delete(
            f"/v1/cloud/smart/timesheet/manual/{entry_id}"
        )
        assert deleted.status_code == 204


def test_garage_extended_fields_and_insurance_alert_api() -> None:
    today = datetime.now(UTC).date()
    end = today + timedelta(days=15)
    garage_number = "API-" + uuid4().hex[:8]

    with TestClient(app) as client:
        created = client.post(
            "/v1/cloud/smart/garage",
            json={
                "garage_number": garage_number,
                "make_model": "Test Vehicle",
                "fuel_type": "ДТ",
                "fuel_rate_summer": 13.4,
                "fuel_rate_winter": 15.2,
                "tire_size_summer": "215/65 R16",
                "tire_size_winter": "215/65 R16",
                "insurance_type": "ОСАГО",
                "insurance_policy": "API-POLICY-" + uuid4().hex[:8],
                "insurance_company": "Тест Страхование",
                "insurance_start": today.isoformat(),
                "insurance_end": end.isoformat(),
            },
        )
        assert created.status_code == 201
        item = created.json()
        assert item["fuel_rate_summer"] == 13.4
        assert item["fuel_rate_winter"] == 15.2
        assert item["insurance_days_left"] == 15
        assert item["insurance_alert"] is True

        alerts = client.get(
            "/v1/cloud/smart/garage/alerts",
            params={"days": 15},
        )
        assert alerts.status_code == 200
        assert any(
            row["id"] == item["id"]
            for row in alerts.json()["items"]
        )

        diagnostics = client.get("/v1/diagnostics/status")
        assert diagnostics.status_code == 200
        assert diagnostics.json()["garage"]["insurance_alerts"] >= 1
