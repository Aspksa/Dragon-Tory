from __future__ import annotations

from tooru.timesheet.calendar_ru import production_calendar


def _by_date(payload: dict) -> dict[str, dict]:
    return {item["date"]: item for item in payload["days"]}


def test_russian_production_calendar_2026_official_totals() -> None:
    data = production_calendar(2026)
    assert data["official"] is True
    assert data["summary"]["workdays"] == 247
    assert data["summary"]["days_off"] == 118
    assert data["summary"]["short_days"] == 4
    assert data["summary"]["norm_hours"] == 1972.0

    days = _by_date(data)
    assert days["2026-01-09"]["is_workday"] is False
    assert days["2026-03-09"]["is_workday"] is False
    assert days["2026-04-30"]["is_short_day"] is True
    assert days["2026-12-31"]["is_workday"] is False


def test_russian_production_calendar_2027_official_transfers() -> None:
    data = production_calendar(2027)
    assert data["official"] is True
    assert data["summary"]["workdays"] == 247
    assert data["summary"]["days_off"] == 118
    assert data["summary"]["short_days"] == 4
    assert data["summary"]["norm_hours"] == 1972.0

    days = _by_date(data)
    assert days["2027-02-20"]["is_workday"] is True
    assert days["2027-02-20"]["is_short_day"] is True
    assert days["2027-02-22"]["is_workday"] is False
    assert days["2027-11-05"]["is_workday"] is False
    assert days["2027-12-31"]["is_workday"] is False
