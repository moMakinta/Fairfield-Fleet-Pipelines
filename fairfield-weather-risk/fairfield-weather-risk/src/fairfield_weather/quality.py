"""Data quality checks, run at the end of every pipeline run.

Each check is a query that counts the rows that break a rule. Zero means the
check passed. The results are stored in audit.data_quality_result so there is
a history, and the run fails if any check fails.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fairfield_weather.models import DateWindow
from fairfield_weather.warehouse import transaction


class DataQualityError(RuntimeError):
    """At least one data quality check failed."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    failed_rows: int

    @property
    def passed(self) -> bool:
        return self.failed_rows == 0


# name -> query that returns one number. %(start)s and %(end)s are the dates the run loaded.
OBSERVED_CHECKS: dict[str, str] = {
    "observed: every active location has a row for every day": """
        SELECT count(*)
        FROM   core.dim_location AS l
        CROSS  JOIN generate_series(%(start)s::date, %(end)s::date, interval '1 day') AS d(day)
        LEFT   JOIN core.fact_weather_observed AS f
               ON f.location_key = l.location_key AND f.weather_date = d.day::date
        WHERE  l.is_active AND f.location_key IS NULL
    """,
    "observed: no missing measurements": """
        SELECT count(*)
        FROM   core.fact_weather_observed
        WHERE  weather_date BETWEEN %(start)s AND %(end)s
          AND  (temp_max_c IS NULL OR temp_min_c IS NULL OR precipitation_mm IS NULL
                OR wind_speed_max_kmh IS NULL OR wind_gust_max_kmh IS NULL)
    """,
    "observed: minimum temperature is not above the maximum": """
        SELECT count(*)
        FROM   core.fact_weather_observed
        WHERE  weather_date BETWEEN %(start)s AND %(end)s AND temp_min_c > temp_max_c
    """,
    "observed: values are physically plausible": """
        SELECT count(*)
        FROM   core.fact_weather_observed
        WHERE  weather_date BETWEEN %(start)s AND %(end)s
          AND  (temp_max_c NOT BETWEEN -30 AND 55 OR temp_min_c NOT BETWEEN -30 AND 55
                OR precipitation_mm NOT BETWEEN 0 AND 600
                OR wind_speed_max_kmh NOT BETWEEN 0 AND 250 OR wind_gust_max_kmh NOT BETWEEN 0 AND 300)
    """,
    "observed: nothing is dated after the run": """
        SELECT count(*) FROM core.fact_weather_observed WHERE weather_date > %(end)s AND source_run_date <= %(end)s
    """,
}

FORECAST_CHECKS: dict[str, str] = {
    "forecast: every active location has every forecast day": """
        SELECT count(*)
        FROM   core.dim_location AS l
        CROSS  JOIN generate_series(%(start)s::date, %(end)s::date, interval '1 day') AS d(day)
        LEFT   JOIN core.fact_weather_forecast AS f
               ON f.location_key = l.location_key AND f.issue_date = %(start)s AND f.target_date = d.day::date
        WHERE  l.is_active AND f.location_key IS NULL
    """,
    "forecast: no missing measurements": """
        SELECT count(*)
        FROM   core.fact_weather_forecast
        WHERE  issue_date = %(start)s
          AND  (temp_max_c IS NULL OR temp_min_c IS NULL OR precipitation_mm IS NULL
                OR wind_speed_max_kmh IS NULL OR wind_gust_max_kmh IS NULL)
    """,
    "forecast: lead days match the dates": """
        SELECT count(*) FROM core.fact_weather_forecast
        WHERE  issue_date = %(start)s AND (lead_days <> target_date - issue_date OR lead_days < 0)
    """,
}


def _run(conn, run_date: date, checks: dict[str, str], window: DateWindow) -> list[CheckResult]:
    results = []
    with transaction(conn) as cur:
        for name, query in checks.items():
            cur.execute(query, {"start": window.start, "end": window.end})
            failed_rows = cur.fetchone()[0]
            results.append(CheckResult(name, failed_rows))
            cur.execute(
                "INSERT INTO audit.data_quality_result (run_date, check_name, passed, failed_rows) "
                "VALUES (%s, %s, %s, %s)",
                (run_date, name, failed_rows == 0, failed_rows))
    return results


def run_checks(conn, run_date: date, observed: DateWindow | None = None,
               forecast: DateWindow | None = None) -> list[CheckResult]:
    """Run the checks for whichever datasets this run loaded, store the results, and return them."""
    results: list[CheckResult] = []
    if observed is not None:
        results += _run(conn, run_date, OBSERVED_CHECKS, observed)
    if forecast is not None:
        results += _run(conn, run_date, FORECAST_CHECKS, forecast)
    return results


def raise_if_failed(results: list[CheckResult]) -> None:
    failed = [result for result in results if not result.passed]
    if failed:
        details = "; ".join(f"{result.name} ({result.failed_rows} rows)" for result in failed)
        raise DataQualityError(f"{len(failed)} data quality check(s) failed: {details}")
