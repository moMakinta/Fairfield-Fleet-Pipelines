"""Settings for the pipeline. Every value has a default and can be overridden with an environment variable."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# The daily measurements requested from Open-Meteo, mapped to the column they are stored in.
DAILY_VARIABLES: dict[str, str] = {
    "temperature_2m_max": "temp_max_c",
    "temperature_2m_min": "temp_min_c",
    "precipitation_sum": "precipitation_mm",
    "wind_speed_10m_max": "wind_speed_max_kmh",
    "wind_gusts_10m_max": "wind_gust_max_kmh",
}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # Recent days and the forecast come from the forecast endpoint.
    forecast_url: str = field(
        default_factory=lambda: os.environ.get("FAIRFIELD_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"))
    # Older history comes from the archive endpoint.
    archive_url: str = field(
        default_factory=lambda: os.environ.get("FAIRFIELD_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive"))

    # All dates are local South African dates, whichever machine the pipeline runs on.
    timezone: str = "Africa/Johannesburg"

    # The forecast endpoint only goes back about 92 days. Anything older than this is read from the archive.
    archive_after_days: int = field(default_factory=lambda: _env_int("FAIRFIELD_ARCHIVE_AFTER_DAYS", 80))

    # Recent observations are revised by the weather models for a few days,
    # so every daily run re-reads the last few days as well and overwrites them.
    lookback_days: int = field(default_factory=lambda: _env_int("FAIRFIELD_LOOKBACK_DAYS", 3))

    # How many days ahead to store (today counts as day 1).
    forecast_days: int = field(default_factory=lambda: _env_int("FAIRFIELD_FORECAST_DAYS", 7))

    # The archive is requested in chunks of at most this many days.
    max_days_per_request: int = 180

    request_timeout_seconds: int = field(default_factory=lambda: _env_int("FAIRFIELD_REQUEST_TIMEOUT", 30))
    max_retries: int = field(default_factory=lambda: _env_int("FAIRFIELD_MAX_RETRIES", 5))
    retry_backoff_seconds: float = 1.0

    # Open-Meteo asks for fair use. A short pause between calls keeps us polite.
    pause_between_requests_seconds: float = field(
        default_factory=lambda: float(os.environ.get("FAIRFIELD_REQUEST_PAUSE", "0.2")))


def database_url() -> str:
    """Connection string for the warehouse when running outside Airflow."""
    url = os.environ.get("FAIRFIELD_DB_URL")
    if not url:
        raise RuntimeError(
            "FAIRFIELD_DB_URL is not set. Example: postgresql://fairfield:fairfield@localhost:5433/fairfield_weather")
    return url
