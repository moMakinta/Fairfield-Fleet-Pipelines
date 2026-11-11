"""Client for the Open-Meteo weather API (https://open-meteo.com).

No API key is needed. Weather data by Open-Meteo.com, licensed under CC BY 4.0.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fairfield_weather.config import DAILY_VARIABLES, Settings
from fairfield_weather.models import DateWindow, Location

log = logging.getLogger(__name__)


class OpenMeteoError(RuntimeError):
    """The API answered, but with an error or with something that is not usable."""


def build_session(settings: Settings) -> requests.Session:
    """A session that retries by itself on the errors that are worth retrying.

    429 (too many requests) and 5xx (server trouble) usually pass if we wait and
    try again, with a longer wait each time. A 400 means our request is wrong,
    so retrying would only fail the same way.
    """
    retry = Retry(
        total=settings.max_retries,
        backoff_factor=settings.retry_backoff_seconds,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "fairfield-weather-risk (portfolio project)"
    return session


class OpenMeteoClient:
    def __init__(self, settings: Settings | None = None, session: requests.Session | None = None) -> None:
        self.settings = settings or Settings()
        self.session = session or build_session(self.settings)

    def endpoint_for(self, window: DateWindow, today: date) -> str:
        """Recent and future days come from the forecast endpoint, older days from the archive."""
        age_of_oldest_day = (today - window.start).days
        if age_of_oldest_day > self.settings.archive_after_days:
            return self.settings.archive_url
        return self.settings.forecast_url

    def fetch_daily(self, location: Location, window: DateWindow, today: date) -> tuple[str, dict[str, Any]]:
        """Daily weather for one location over a range of dates.

        Returns the URL that was called and the JSON exactly as the API sent it,
        so the raw answer can be stored before anything is done to it.
        """
        url = self.endpoint_for(window, today)
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "start_date": window.start.isoformat(),
            "end_date": window.end.isoformat(),
            "daily": ",".join(DAILY_VARIABLES),
            "timezone": self.settings.timezone,
            # ask for the units explicitly instead of relying on the defaults
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }
        try:
            response = self.session.get(url, params=params, timeout=self.settings.request_timeout_seconds)
        except requests.RequestException as error:
            raise OpenMeteoError(f"{location.code}: could not reach {url}: {error}") from error

        payload = self._read_json(response, location)
        if response.status_code != 200 or payload.get("error"):
            reason = payload.get("reason", "no reason given")
            raise OpenMeteoError(f"{location.code}: API returned HTTP {response.status_code}: {reason}")
        if "daily" not in payload:
            raise OpenMeteoError(f"{location.code}: response has no 'daily' section")

        log.info("Fetched %s %s..%s from %s", location.code, window.start, window.end, url)
        if self.settings.pause_between_requests_seconds:
            time.sleep(self.settings.pause_between_requests_seconds)
        return response.url, payload

    @staticmethod
    def _read_json(response: requests.Response, location: Location) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise OpenMeteoError(
                f"{location.code}: HTTP {response.status_code} and the body is not JSON: {response.text[:200]!r}") from error
        if not isinstance(payload, dict):
            raise OpenMeteoError(f"{location.code}: expected a JSON object, got {type(payload).__name__}")
        return payload
