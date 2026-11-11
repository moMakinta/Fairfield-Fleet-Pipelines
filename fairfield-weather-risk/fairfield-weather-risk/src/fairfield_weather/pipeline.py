"""The steps of the pipeline. Nothing in here knows about Airflow.

    extract    call the API for every location and store the raw answers
    transform  parse the stored answers and merge them into the core tables
    check      run the data quality checks

Extract and transform are separate on purpose. The raw answers are kept, so
if the parsing or the table design changes, transform can be run again
without calling the API a second time.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fairfield_weather import warehouse
from fairfield_weather.api import OpenMeteoClient, OpenMeteoError
from fairfield_weather.config import Settings
from fairfield_weather.dates import forecast_window, observed_window, split_window
from fairfield_weather.models import DailyWeather, Dataset, DateWindow
from fairfield_weather.parsing import parse_daily
from fairfield_weather.quality import CheckResult, raise_if_failed, run_checks

log = logging.getLogger(__name__)


class ExtractError(RuntimeError):
    """One or more locations could not be fetched."""


def extract(conn, client: OpenMeteoClient, dataset: Dataset, run_date: date, window: DateWindow, today: date) -> int:
    """Fetch the window for every active location and store the raw answers under run_date.

    Every location is attempted even if an earlier one fails, so one bad
    location does not hide problems with the others. If any failed, the step
    fails at the end and can simply be run again.
    """
    locations = warehouse.active_locations(conn)
    if not locations:
        raise ExtractError("core.dim_location has no active locations. Has the database been set up?")

    failures: list[str] = []
    for location in locations:
        try:
            url, payload = client.fetch_daily(location, window, today)
            warehouse.save_raw_response(conn, dataset, location.code, run_date, url, payload)
        except OpenMeteoError as error:
            log.error("%s", error)
            failures.append(str(error))

    stored = len(locations) - len(failures)
    warehouse.log_step(conn, run_date, f"extract_{dataset}", "failed" if failures else "success", stored,
                       "; ".join(failures)[:2000] or None)
    if failures:
        raise ExtractError(f"{len(failures)} of {len(locations)} locations failed: " + "; ".join(failures))
    log.info("Stored %d raw %s responses for run date %s", stored, dataset, run_date)
    return stored


def transform(conn, dataset: Dataset, run_date: date, window: DateWindow | None = None) -> int:
    """Parse the raw answers of a run and merge them into the core table. Returns rows inserted or changed."""
    records: list[DailyWeather] = []
    for location_code, payload in warehouse.raw_responses(conn, dataset, run_date):
        parsed = parse_daily(payload, location_code)
        if window is not None:      # ignore days outside what was asked for, should the API send any
            parsed = [r for r in parsed if window.start <= r.weather_date <= window.end]
        records.extend(parsed)

    staged = warehouse.replace_staging(conn, dataset, run_date, records)
    merged = warehouse.merge_observed(conn, run_date) if dataset == "observed" else warehouse.merge_forecast(conn, run_date)
    warehouse.log_step(conn, run_date, f"transform_{dataset}", "success", merged, f"{staged} rows staged")
    log.info("%s for %s: %d rows staged, %d inserted or changed", dataset, run_date, staged, merged)
    return merged


def check(conn, run_date: date, observed: DateWindow | None, forecast: DateWindow | None) -> list[CheckResult]:
    """Run the checks, record the outcome, and raise DataQualityError if anything failed."""
    results = run_checks(conn, run_date, observed=observed, forecast=forecast)
    for result in results:
        log.info("%s  %s%s", "PASS" if result.passed else "FAIL", result.name,
                 "" if result.passed else f" ({result.failed_rows} rows)")
    failed = sum(not result.passed for result in results)
    warehouse.log_step(conn, run_date, "quality_checks", "failed" if failed else "success", len(results),
                       f"{failed} failed" if failed else None)
    raise_if_failed(results)
    return results


# ---------------------------------------------------------------------------
# Whole runs, built from the steps above. The command line uses these directly.
# The Airflow DAGs call the steps one by one so each shows as its own task.
# ---------------------------------------------------------------------------

def run_daily(conn, client: OpenMeteoClient, settings: Settings, target_date: date, today: date,
              include_forecast: bool = True) -> None:
    """The normal daily run: recent observations up to target_date, plus a forecast issued the day after."""
    obs_window = observed_window(target_date, settings.lookback_days)
    extract(conn, client, "observed", target_date, obs_window, today)
    transform(conn, "observed", target_date, obs_window)

    fc_window = None
    if include_forecast:
        issue_date = target_date + timedelta(days=1)
        fc_window = forecast_window(issue_date, settings.forecast_days)
        extract(conn, client, "forecast", issue_date, fc_window, today)
        transform(conn, "forecast", issue_date, fc_window)

    check(conn, target_date, observed=obs_window, forecast=fc_window)


def run_backfill(conn, client: OpenMeteoClient, settings: Settings, window: DateWindow, today: date) -> int:
    """Load a long stretch of history. One request per location per chunk, instead of one per day."""
    total = 0
    for piece in split_window(window, settings.max_days_per_request):
        extract(conn, client, "observed", piece.end, piece, today)
        total += transform(conn, "observed", piece.end, piece)
    check(conn, window.end, observed=window, forecast=None)
    return total
