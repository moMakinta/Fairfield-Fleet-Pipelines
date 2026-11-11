from datetime import date

import pytest
import requests

from conftest import TODAY
from fairfield_weather.api import OpenMeteoClient, OpenMeteoError, build_session
from fairfield_weather.config import Settings
from fairfield_weather.models import DateWindow, Location
from fake_open_meteo import FakeResponse

DURBAN = Location("DUR", "Durban Port Terminal", -29.87, 31.03)
RECENT = DateWindow(date(2026, 11, 8), date(2026, 11, 10))


def test_request_asks_for_the_right_place_dates_and_units(client, session):
    url, payload = client.fetch_daily(DURBAN, RECENT, TODAY)
    called_url, params = session.calls[0]
    assert params["latitude"] == -29.87 and params["longitude"] == 31.03
    assert (params["start_date"], params["end_date"]) == ("2026-11-08", "2026-11-10")
    assert params["timezone"] == "Africa/Johannesburg"
    assert (params["temperature_unit"], params["wind_speed_unit"], params["precipitation_unit"]) == ("celsius", "kmh", "mm")
    assert set(params["daily"].split(",")) == {"temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                                               "wind_speed_10m_max", "wind_gusts_10m_max"}
    assert payload["daily"]["time"] == ["2026-11-08", "2026-11-09", "2026-11-10"]


def test_recent_and_future_dates_use_the_forecast_endpoint(client, settings):
    assert client.endpoint_for(RECENT, TODAY) == settings.forecast_url
    assert client.endpoint_for(DateWindow(date(2026, 11, 11), date(2026, 11, 17)), TODAY) == settings.forecast_url


def test_old_dates_use_the_archive_endpoint(client, settings):
    assert client.endpoint_for(DateWindow(date(2025, 1, 1), date(2025, 6, 29)), TODAY) == settings.archive_url
    # the oldest day decides: one day past the limit is enough to switch
    boundary = date.fromordinal(TODAY.toordinal() - settings.archive_after_days)
    assert client.endpoint_for(DateWindow(boundary, boundary), TODAY) == settings.forecast_url
    older = date.fromordinal(boundary.toordinal() - 1)
    assert client.endpoint_for(DateWindow(older, TODAY), TODAY) == settings.archive_url


def test_an_error_answer_from_the_api_is_raised_with_its_reason(client, session):
    session.fail_for_latitudes = {-29.87}
    with pytest.raises(OpenMeteoError, match="DUR: API returned HTTP 400: Latitude must be in range"):
        client.fetch_daily(DURBAN, RECENT, TODAY)


class _OneAnswerSession:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def get(self, url, params, timeout=None):
        if self.error:
            raise self.error
        return self.response


@pytest.mark.parametrize("response, message", [
    (FakeResponse(502, "<html>Bad Gateway</html>"), "HTTP 502 and the body is not JSON"),
    (FakeResponse(200, ["a", "list"]), "expected a JSON object"),
    (FakeResponse(200, {"latitude": -29.87}), "no 'daily' section"),
    (FakeResponse(200, {"error": True, "reason": "Daily API request limit exceeded."}), "request limit exceeded"),
])
def test_unusable_answers_are_refused(settings, response, message):
    client = OpenMeteoClient(settings, session=_OneAnswerSession(response=response))
    with pytest.raises(OpenMeteoError, match=message):
        client.fetch_daily(DURBAN, RECENT, TODAY)


def test_a_network_failure_becomes_an_open_meteo_error(settings):
    client = OpenMeteoClient(settings, session=_OneAnswerSession(error=requests.ConnectionError("no route to host")))
    with pytest.raises(OpenMeteoError, match="DUR: could not reach"):
        client.fetch_daily(DURBAN, RECENT, TODAY)


def test_the_real_session_retries_only_what_is_worth_retrying():
    retry = build_session(Settings(max_retries=4)).get_adapter("https://api.open-meteo.com").max_retries
    assert retry.total == 4
    assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
    assert 400 not in retry.status_forcelist
