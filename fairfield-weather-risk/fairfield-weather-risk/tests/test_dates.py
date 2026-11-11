from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from fairfield_weather.dates import each_day, forecast_window, local_today, observed_window, split_window, target_date_for_run
from fairfield_weather.models import DateWindow

SAST = "Africa/Johannesburg"


def test_target_date_is_yesterday_in_local_time():
    run = datetime(2026, 11, 11, 5, 0, tzinfo=ZoneInfo(SAST))
    assert target_date_for_run(run, SAST) == date(2026, 11, 10)


def test_target_date_uses_local_time_not_utc():
    # 23:30 UTC on the 10th is already 01:30 on the 11th in South Africa
    run = datetime(2026, 11, 10, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert target_date_for_run(run, SAST) == date(2026, 11, 10)
    assert local_today(SAST, now=run) == date(2026, 11, 11)


def test_observed_window_ends_on_the_target_date():
    assert observed_window(date(2026, 11, 10), 3) == DateWindow(date(2026, 11, 8), date(2026, 11, 10))
    assert observed_window(date(2026, 11, 10), 1) == DateWindow(date(2026, 11, 10), date(2026, 11, 10))


def test_observed_window_crosses_month_and_year_ends():
    assert observed_window(date(2026, 1, 1), 3).start == date(2025, 12, 30)


def test_forecast_window_starts_on_the_issue_date():
    window = forecast_window(date(2026, 11, 11), 7)
    assert (window.start, window.end, window.days) == (date(2026, 11, 11), date(2026, 11, 17), 7)


def test_split_window_covers_every_day_once():
    year = DateWindow(date(2025, 1, 1), date(2025, 12, 31))
    pieces = split_window(year, 180)
    assert [piece.days for piece in pieces] == [180, 180, 5]
    assert pieces[0].start == year.start and pieces[-1].end == year.end
    all_days = [day for piece in pieces for day in each_day(piece)]
    assert all_days == each_day(year) and len(set(all_days)) == 365


def test_split_window_shorter_than_the_limit_is_left_alone():
    window = DateWindow(date(2025, 3, 1), date(2025, 3, 10))
    assert split_window(window, 180) == [window]


@pytest.mark.parametrize("bad_call", [
    lambda: DateWindow(date(2026, 1, 2), date(2026, 1, 1)),
    lambda: observed_window(date(2026, 1, 1), 0),
    lambda: forecast_window(date(2026, 1, 1), 0),
    lambda: split_window(DateWindow(date(2026, 1, 1), date(2026, 1, 2)), 0),
])
def test_nonsense_input_is_refused(bad_call):
    with pytest.raises(ValueError):
        bad_call()
