import json
from datetime import date
from pathlib import Path

import pytest

from fairfield_weather.parsing import PayloadError, parse_daily

FIXTURE = Path(__file__).parent / "fixtures" / "open_meteo_daily.json"


@pytest.fixture
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_one_record_per_day_with_the_right_values(payload):
    records = parse_daily(payload, "DUR")
    assert [r.weather_date for r in records] == [date(2026, 11, 8), date(2026, 11, 9), date(2026, 11, 10)]
    first = records[0]
    assert (first.location_code, first.temp_max_c, first.temp_min_c) == ("DUR", 27.4, 19.8)
    assert (first.precipitation_mm, first.wind_speed_max_kmh, first.wind_gust_max_kmh) == (0.0, 24.1, 46.8)


def test_whole_numbers_become_floats(payload):
    payload["daily"]["precipitation_sum"][0] = 3
    assert parse_daily(payload, "DUR")[0].precipitation_mm == 3.0


def test_a_missing_measurement_is_kept_as_none(payload):
    payload["daily"]["wind_gusts_10m_max"][1] = None
    records = parse_daily(payload, "DUR")
    assert records[1].wind_gust_max_kmh is None and records[1].temp_max_c == 29.1


@pytest.mark.parametrize("damage, message", [
    (lambda p: p.pop("daily"), "'daily' section is missing"),
    (lambda p: p["daily"].pop("time"), "'daily.time' is missing"),
    (lambda p: p["daily"].update(time=[]), "'daily.time' is missing or empty"),
    (lambda p: p["daily"].pop("precipitation_sum"), "'daily.precipitation_sum' is missing"),
    (lambda p: p["daily"]["temperature_2m_max"].pop(), "2 values for 3 dates"),
    (lambda p: p["daily"]["time"].__setitem__(0, "08/11/2026"), "bad date"),
    (lambda p: p["daily"]["time"].__setitem__(1, "2026-11-08"), "more than once"),
    (lambda p: p["daily"]["temperature_2m_min"].__setitem__(0, "warm"), "non-numeric"),
])
def test_a_damaged_response_is_refused_with_a_clear_message(payload, damage, message):
    damage(payload)
    with pytest.raises(PayloadError, match=message):
        parse_daily(payload, "DUR")
