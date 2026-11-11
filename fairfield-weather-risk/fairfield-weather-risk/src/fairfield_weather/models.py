"""The small data structures passed between the steps."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

# The two kinds of data the pipeline handles.
#   observed = what the weather actually was on a past day
#   forecast = what a day is expected to be, as predicted on the issue date
Dataset = Literal["observed", "forecast"]


@dataclass(frozen=True)
class Location:
    code: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class DailyWeather:
    """One day of weather at one location. A value is None when the API had no figure for it."""

    location_code: str
    weather_date: date
    temp_max_c: float | None
    temp_min_c: float | None
    precipitation_mm: float | None
    wind_speed_max_kmh: float | None
    wind_gust_max_kmh: float | None


@dataclass(frozen=True)
class DateWindow:
    """An inclusive range of dates."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"window ends ({self.end}) before it starts ({self.start})")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1
