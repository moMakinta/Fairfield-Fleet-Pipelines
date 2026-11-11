"""Date logic, kept in one place because it is the easiest part to get subtly wrong.

Vocabulary used everywhere in the project:

    run day      the day the pipeline runs (it runs early in the morning)
    target date  the last full day before the run day, i.e. "yesterday"
    issue date   the day a forecast is made, which is the run day

So the run at 05:00 on 11 November has target date 10 November and issue date 11 November.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fairfield_weather.models import DateWindow


def local_today(timezone: str, now: datetime | None = None) -> date:
    """Today's date in the given time zone, whatever the clock of the machine says."""
    now = now or datetime.now(tz=ZoneInfo("UTC"))
    return now.astimezone(ZoneInfo(timezone)).date()


def target_date_for_run(run_moment: datetime, timezone: str) -> date:
    """The last full local day before the moment a run was scheduled for."""
    return run_moment.astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)


def observed_window(target_date: date, lookback_days: int) -> DateWindow:
    """The days to (re)load for a daily run: the target date and the days just before it."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")
    return DateWindow(target_date - timedelta(days=lookback_days - 1), target_date)


def forecast_window(issue_date: date, forecast_days: int) -> DateWindow:
    """The days a forecast covers. The issue date itself is the first day."""
    if forecast_days < 1:
        raise ValueError("forecast_days must be at least 1")
    return DateWindow(issue_date, issue_date + timedelta(days=forecast_days - 1))


def split_window(window: DateWindow, max_days: int) -> list[DateWindow]:
    """Cut a long window into consecutive pieces of at most max_days, for APIs that limit the range per call."""
    if max_days < 1:
        raise ValueError("max_days must be at least 1")
    pieces, start = [], window.start
    while start <= window.end:
        end = min(start + timedelta(days=max_days - 1), window.end)
        pieces.append(DateWindow(start, end))
        start = end + timedelta(days=1)
    return pieces


def each_day(window: DateWindow) -> list[date]:
    return [window.start + timedelta(days=offset) for offset in range(window.days)]
