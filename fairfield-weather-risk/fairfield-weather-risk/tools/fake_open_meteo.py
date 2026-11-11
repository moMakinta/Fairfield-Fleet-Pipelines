"""A stand-in for the Open-Meteo API that makes up plausible weather.

Used in two ways:

1. The tests import `build_payload` and `FakeSession`, so they never touch the internet.
2. Run as a program, it is a small web server that answers like Open-Meteo. Point the
   pipeline at it to try everything with no internet connection:

       python tools/fake_open_meteo.py --port 8089
       set FAIRFIELD_FORECAST_URL=http://localhost:8089/v1/forecast
       set FAIRFIELD_ARCHIVE_URL=http://localhost:8089/v1/archive

The weather is invented but repeatable: the same place and day always give the
same numbers. Days that are still in the future get a little extra noise that
depends on the day the question is asked, the way a real forecast changes from
one day to the next.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

UNITS = {"time": "iso8601", "temperature_2m_max": "°C", "temperature_2m_min": "°C",
         "precipitation_sum": "mm", "wind_speed_10m_max": "km/h", "wind_gusts_10m_max": "km/h"}


def _one_day(latitude: float, longitude: float, day: date, today: date) -> dict[str, float]:
    rng = random.Random(f"{latitude:.2f}|{longitude:.2f}|{day.toordinal()}")
    # southern hemisphere: hottest in mid January, coldest in mid July
    season = math.cos(2 * math.pi * (day.timetuple().tm_yday - 15) / 365)
    coastal = longitude > 30.5 or latitude < -33
    temp_max = 23 + 6 * season + rng.uniform(-4, 5) + (0 if coastal else 2)
    temp_min = temp_max - rng.uniform(7, 14) + (3 if coastal else 0)
    rain = 0.0 if rng.random() < 0.7 else rng.expovariate(1 / 9)
    wind = rng.uniform(8, 30) + (10 if coastal else 0)
    gust = wind * rng.uniform(1.4, 1.9)

    if day >= today:      # a forecast: wobble it a bit, more the further ahead it is
        lead = (day - today).days + 1
        noise = random.Random(f"{latitude:.2f}|{longitude:.2f}|{day.toordinal()}|{today.toordinal()}")
        temp_max += noise.uniform(-0.4, 0.4) * lead
        temp_min += noise.uniform(-0.4, 0.4) * lead
        rain = max(0.0, rain + noise.uniform(-1, 1) * lead)
        gust = max(wind, gust + noise.uniform(-2, 2) * lead)

    return {"temperature_2m_max": round(temp_max, 1), "temperature_2m_min": round(min(temp_min, temp_max), 1),
            "precipitation_sum": round(rain, 1), "wind_speed_10m_max": round(wind, 1),
            "wind_gusts_10m_max": round(gust, 1)}


def build_payload(latitude: float, longitude: float, start: date, end: date, today: date | None = None,
                  variables: list[str] | None = None) -> dict:
    """A response in the same shape Open-Meteo documents for daily data."""
    today = today or datetime.now(tz=ZoneInfo("Africa/Johannesburg")).date()
    variables = variables or [name for name in UNITS if name != "time"]
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    values = [_one_day(latitude, longitude, day, today) for day in days]
    daily = {"time": [day.isoformat() for day in days]}
    for name in variables:
        daily[name] = [row[name] for row in values]
    return {
        "latitude": latitude, "longitude": longitude, "generationtime_ms": 0.1,
        "utc_offset_seconds": 7200, "timezone": "Africa/Johannesburg", "timezone_abbreviation": "GMT+2",
        "elevation": 10.0,
        "daily_units": {name: UNITS[name] for name in ["time", *variables]},
        "daily": daily,
    }


class FakeResponse:
    def __init__(self, status_code: int, payload, url: str = "https://fake.test/v1/forecast") -> None:
        self.status_code, self._payload, self.url = status_code, payload, url
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not JSON")
        return self._payload


class FakeSession:
    """Drop-in for requests.Session in tests. Records every call it gets."""

    def __init__(self, today: date | None = None) -> None:
        self.today = today
        self.calls: list[tuple[str, dict]] = []
        self.fail_for_latitudes: set[float] = set()      # these locations get an error answer
        self.transform = None                            # optional function to tamper with a payload

    def get(self, url: str, params: dict, timeout: int | None = None) -> FakeResponse:
        self.calls.append((url, dict(params)))
        if float(params["latitude"]) in self.fail_for_latitudes:
            return FakeResponse(400, {"error": True, "reason": "Latitude must be in range of -90 to 90°."}, url)
        payload = build_payload(float(params["latitude"]), float(params["longitude"]),
                                date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"]),
                                today=self.today, variables=params["daily"].split(","))
        if self.transform:
            payload = self.transform(payload, params)
        return FakeResponse(200, payload, url)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:      # noqa: N802  (the name is fixed by BaseHTTPRequestHandler)
        query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
        try:
            payload = build_payload(float(query["latitude"]), float(query["longitude"]),
                                    date.fromisoformat(query["start_date"]), date.fromisoformat(query["end_date"]),
                                    variables=query["daily"].split(","))
            status = 200
        except (KeyError, ValueError) as error:
            payload, status = {"error": True, "reason": f"Bad request: {error}"}, 400
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:      # keep the console quiet
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake Open-Meteo server for offline runs")
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    print(f"Fake Open-Meteo listening on http://localhost:{args.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", args.port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
