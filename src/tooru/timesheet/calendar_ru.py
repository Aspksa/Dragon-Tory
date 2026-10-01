from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class CalendarYearConfig:
    year: int
    regulation: str
    source_url: str
    transfers: tuple[tuple[date, date], ...]
    short_days: frozenset[date]


_CONFIGS: dict[int, CalendarYearConfig] = {
    2026: CalendarYearConfig(
        year=2026,
        regulation=(
            "Постановление Правительства РФ от 24.09.2025 № 1466 "
            "«О переносе выходных дней в 2026 году»"
        ),
        source_url="https://government.ru/docs/all/161028/",
        transfers=(
            (date(2026, 1, 3), date(2026, 1, 9)),
            (date(2026, 1, 4), date(2026, 12, 31)),
        ),
        short_days=frozenset(
            {
                date(2026, 4, 30),
                date(2026, 5, 8),
                date(2026, 6, 11),
                date(2026, 11, 3),
            }
        ),
    ),
    2027: CalendarYearConfig(
        year=2027,
        regulation=(
            "Постановление Правительства РФ от 17.09.2026 № 1187 "
            "«О переносе выходных дней в 2027 году»"
        ),
        source_url=(
            "https://www.consultant.ru/document/cons_doc_LAW_544706/"
        ),
        transfers=(
            (date(2027, 1, 2), date(2027, 11, 5)),
            (date(2027, 1, 3), date(2027, 12, 31)),
            (date(2027, 2, 20), date(2027, 2, 22)),
        ),
        short_days=frozenset(
            {
                date(2027, 2, 20),
                date(2027, 4, 30),
                date(2027, 6, 11),
                date(2027, 11, 3),
            }
        ),
    ),
}

_HOLIDAYS: dict[tuple[int, int], str] = {
    (1, 1): "Новогодние каникулы",
    (1, 2): "Новогодние каникулы",
    (1, 3): "Новогодние каникулы",
    (1, 4): "Новогодние каникулы",
    (1, 5): "Новогодние каникулы",
    (1, 6): "Новогодние каникулы",
    (1, 7): "Рождество Христово",
    (1, 8): "Новогодние каникулы",
    (2, 23): "День защитника Отечества",
    (3, 8): "Международный женский день",
    (5, 1): "Праздник Весны и Труда",
    (5, 9): "День Победы",
    (6, 12): "День России",
    (11, 4): "День народного единства",
}

_WEEKDAY_NAMES = (
    "Пн",
    "Вт",
    "Ср",
    "Чт",
    "Пт",
    "Сб",
    "Вс",
)


def supported_years() -> list[int]:
    return sorted(_CONFIGS)


def _automatic_shifted_holidays(year: int) -> dict[date, str]:
    shifted: dict[date, str] = {}
    occupied = {
        date(year, month, day)
        for (month, day) in _HOLIDAYS
    }
    config = _CONFIGS[year]
    transfer_targets = {target for _, target in config.transfers}

    for (month, day), holiday_name in _HOLIDAYS.items():
        if month == 1 and 1 <= day <= 8:
            continue
        holiday = date(year, month, day)
        if holiday.weekday() < 5:
            continue
        candidate = holiday + timedelta(days=1)
        while (
            candidate.weekday() >= 5
            or candidate in occupied
            or candidate in transfer_targets
            or candidate in shifted
        ):
            candidate += timedelta(days=1)
        shifted[candidate] = (
            f"Перенос выходного после праздника: {holiday_name}"
        )
    return shifted


def production_calendar(
    year: int,
    *,
    month: int | None = None,
    weekly_hours: float = 40.0,
) -> dict[str, Any]:
    if year not in _CONFIGS:
        raise ValueError(
            "Производственный календарь доступен для 2026 и 2027 годов."
        )
    if month is not None and not 1 <= month <= 12:
        raise ValueError("Месяц должен быть от 1 до 12.")
    if weekly_hours <= 0 or weekly_hours > 60:
        raise ValueError("Некорректная продолжительность рабочей недели.")

    config = _CONFIGS[year]
    transfer_sources = {source: target for source, target in config.transfers}
    transfer_targets = {target: source for source, target in config.transfers}
    shifted = _automatic_shifted_holidays(year)

    start = date(year, month or 1, 1)
    if month is None:
        end = date(year, 12, 31)
    else:
        end = date(year, month, calendar.monthrange(year, month)[1])

    daily_hours = weekly_hours / 5.0
    days: list[dict[str, Any]] = []
    current = start
    while current <= end:
        holiday_name = _HOLIDAYS.get((current.month, current.day))
        weekend = current.weekday() >= 5
        transfer_source = current in transfer_sources
        transfer_target = current in transfer_targets
        shifted_holiday = shifted.get(current)

        # A transfer source can become a working day. In 2027 this makes
        # Saturday 20 February a working (and shortened) day.
        working_override = transfer_source and not holiday_name
        nonworking = (
            (weekend and not working_override)
            or bool(holiday_name)
            or transfer_target
            or bool(shifted_holiday)
        )
        short_day = current in config.short_days and not nonworking
        planned_hours = None
        if not nonworking:
            planned_hours = max(0.0, daily_hours - (1.0 if short_day else 0.0))

        reason = ""
        if holiday_name:
            reason = holiday_name
        elif transfer_target:
            source = transfer_targets[current]
            reason = (
                "Перенос выходного "
                f"с {source.day:02d}.{source.month:02d}.{source.year}"
            )
        elif shifted_holiday:
            reason = shifted_holiday
        elif working_override:
            target = transfer_sources[current]
            reason = (
                "Рабочий день из-за переноса выходного на "
                f"{target.day:02d}.{target.month:02d}.{target.year}"
            )
        elif weekend:
            reason = "Выходной"

        days.append(
            {
                "date": current.isoformat(),
                "day": current.day,
                "weekday": current.weekday(),
                "weekday_name": _WEEKDAY_NAMES[current.weekday()],
                "is_workday": not nonworking,
                "is_weekend": weekend and not working_override,
                "is_holiday": bool(holiday_name),
                "is_shifted_day_off": bool(
                    shifted_holiday or transfer_target
                ),
                "is_transferred": (
                    transfer_source
                    or transfer_target
                    or bool(shifted_holiday)
                ),
                "is_short_day": short_day,
                "planned_code": "Я" if not nonworking else "В",
                "planned_hours": (
                    round(planned_hours, 2)
                    if planned_hours is not None
                    else None
                ),
                "reason": reason,
            }
        )
        current += timedelta(days=1)

    workdays = sum(1 for item in days if item["is_workday"])
    shortened = sum(1 for item in days if item["is_short_day"])
    norm_hours = round(
        sum(float(item["planned_hours"] or 0.0) for item in days),
        2,
    )
    return {
        "year": year,
        "month": month,
        "country": "RU",
        "workweek": "five_day",
        "weekly_hours": weekly_hours,
        "official": True,
        "regulation": config.regulation,
        "source_url": config.source_url,
        "days": days,
        "summary": {
            "calendar_days": len(days),
            "workdays": workdays,
            "days_off": len(days) - workdays,
            "short_days": shortened,
            "norm_hours": norm_hours,
        },
        "codes": {
            "Я": "Явка / обычный рабочий день",
            "В": "Выходной или нерабочий праздничный день",
            "РВ": "Работа в выходной или нерабочий праздничный день",
            "ОТ": "Ежегодный основной оплачиваемый отпуск",
            "Б": "Временная нетрудоспособность с назначением пособия",
        },
    }
