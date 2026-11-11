"""Turns a raw Open-Meteo response into one record per day.

The API sends the days as parallel lists:

    "daily": {"time": ["2026-11-09", "2026-11-10"],
              "temperature_2m_max": [27.4, 29.1],
              "precipitation_sum": [0.0, 12.6], ...}

so the first value in every list belongs to the first date, and so on.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from fairfield_weather.config import DAILY_VARIABLES
from fairfield_weather.models import DailyWeather


class PayloadError(ValueError):
    """The response does not have the structure we rely on."""


def _number(value: Any, location_code: str, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PayloadError(f"{location_code}: {field} has a non-numeric value {value!r}")
    if math.isnan(value) or math.isinf(value):
        return None
    return float(value)


def parse_daily(payload: dict[str, Any], location_code: str) -> list[DailyWeather]:
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise PayloadError(f"{location_code}: 'daily' section is missing")

    days = daily.get("time")
    if not isinstance(days, list) or not days:
        raise PayloadError(f"{location_code}: 'daily.time' is missing or empty")

    columns: dict[str, list[Any]] = {}
    for api_name, column in DAILY_VARIABLES.items():
        values = daily.get(api_name)
        if not isinstance(values, list):
            raise PayloadError(f"{location_code}: 'daily.{api_name}' is missing")
        if len(values) != len(days):
            raise PayloadError(
                f"{location_code}: 'daily.{api_name}' has {len(values)} values for {len(days)} dates")
        columns[column] = values

    records = []
    for index, day in enumerate(days):
        try:
            weather_date = date.fromisoformat(day)
        except (TypeError, ValueError) as error:
            raise PayloadError(f"{location_code}: bad date {day!r} in 'daily.time'") from error
        records.append(DailyWeather(
            location_code=location_code,
            weather_date=weather_date,
            **{column: _number(values[index], location_code, column) for column, values in columns.items()},
        ))

    if len({record.weather_date for record in records}) != len(records):
        raise PayloadError(f"{location_code}: the same date appears more than once")
    return records
