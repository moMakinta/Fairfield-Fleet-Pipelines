"""
### Fairfield weather: daily load

Runs every morning at 05:00 South African time.

| Task | What it does |
|---|---|
| `plan_run` | Works out which dates this run covers |
| `extract_observed` | Calls Open-Meteo for the last few days at every site and stores the raw answers |
| `transform_observed` | Parses the raw answers and merges them into `core.fact_weather_observed` |
| `forecast_is_current` | Skips the forecast branch when an old date is being re-run |
| `extract_forecast` / `transform_forecast` | The same two steps for the 7-day forecast |
| `quality_checks` | Fails the run if the loaded data breaks a rule |

**Re-running a day:** trigger the DAG by hand and fill in `target_date`. Every
step overwrites what it wrote before, so re-running is always safe.

**Loading history:** use the `fairfield_weather_backfill` DAG instead. It makes
one API call per site for a whole date range rather than one per day.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pendulum
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Param, dag, get_current_context, task

from fairfield_weather import pipeline
from fairfield_weather.api import OpenMeteoClient
from fairfield_weather.config import Settings
from fairfield_weather.dates import forecast_window, local_today, observed_window, target_date_for_run
from fairfield_weather.models import DateWindow

WAREHOUSE_CONN_ID = "fairfield_warehouse"
LOCAL_TZ = "Africa/Johannesburg"

DEFAULT_ARGS = {
    "owner": "data-engineering",
    # API hiccups usually clear up, so wait and try again, a bit longer each time
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "execution_timeout": timedelta(minutes=20),
}


def _warehouse():
    return PostgresHook(postgres_conn_id=WAREHOUSE_CONN_ID).get_conn()


def _window(plan: dict, name: str) -> DateWindow:
    start, end = plan[name]
    return DateWindow(date.fromisoformat(start), date.fromisoformat(end))


@dag(
    dag_id="fairfield_weather_daily",
    schedule="0 5 * * *",
    start_date=pendulum.datetime(2025, 1, 1, tz=LOCAL_TZ),     # the cron above is read in this time zone
    catchup=False,              # do not create a run for every day since start_date. History is the backfill DAG's job
    max_active_runs=1,          # two runs at once would only fight over the same rows
    default_args=DEFAULT_ARGS,
    params={
        "target_date": Param(
            None, type=["null", "string"], format="date",
            description="Re-run for this date (YYYY-MM-DD). Leave empty for the normal run, which loads yesterday."),
    },
    tags=["fairfield", "weather", "daily"],
    doc_md=__doc__,
)
def fairfield_weather_daily():

    @task
    def plan_run() -> dict:
        """Decide the dates once, so every task in the run agrees on them."""
        context = get_current_context()
        settings = Settings()
        today = local_today(settings.timezone)

        override = context["params"].get("target_date")
        if override:
            target = date.fromisoformat(override)
        else:
            # data_interval_end is the moment this run was scheduled for. A run that was
            # scheduled for 05:00 yesterday but only started today still loads the right day.
            moment = context.get("data_interval_end") or context["dag_run"].run_after
            if not isinstance(moment, datetime):
                moment = datetime.now(tz=timezone.utc)
            target = target_date_for_run(moment, settings.timezone)

        if target >= today:
            raise ValueError(f"target_date {target} is not in the past (today is {today}). A day must be over to be observed.")

        issue = target + timedelta(days=1)
        observed = observed_window(target, settings.lookback_days)
        forecast = forecast_window(issue, settings.forecast_days)
        return {
            "target_date": target.isoformat(),
            "issue_date": issue.isoformat(),
            "today": today.isoformat(),
            # a forecast can only be fetched for "now". When an old date is re-run, there is nothing to fetch.
            "load_forecast": issue >= today,
            "observed": [observed.start.isoformat(), observed.end.isoformat()],
            "forecast": [forecast.start.isoformat(), forecast.end.isoformat()],
        }

    @task
    def extract_observed(plan: dict) -> int:
        conn = _warehouse()
        try:
            return pipeline.extract(conn, OpenMeteoClient(), "observed", date.fromisoformat(plan["target_date"]),
                                    _window(plan, "observed"), date.fromisoformat(plan["today"]))
        finally:
            conn.close()

    @task
    def transform_observed(plan: dict) -> int:
        conn = _warehouse()
        try:
            return pipeline.transform(conn, "observed", date.fromisoformat(plan["target_date"]), _window(plan, "observed"))
        finally:
            conn.close()

    # ignore_downstream_trigger_rules=False: only skip the forecast tasks, and let quality_checks decide for itself
    @task.short_circuit(ignore_downstream_trigger_rules=False)
    def forecast_is_current(plan: dict) -> bool:
        return bool(plan["load_forecast"])

    @task
    def extract_forecast(plan: dict) -> int:
        conn = _warehouse()
        try:
            return pipeline.extract(conn, OpenMeteoClient(), "forecast", date.fromisoformat(plan["issue_date"]),
                                    _window(plan, "forecast"), date.fromisoformat(plan["today"]))
        finally:
            conn.close()

    @task
    def transform_forecast(plan: dict) -> int:
        conn = _warehouse()
        try:
            return pipeline.transform(conn, "forecast", date.fromisoformat(plan["issue_date"]), _window(plan, "forecast"))
        finally:
            conn.close()

    # none_failed: run when the forecast branch was skipped, but not when anything upstream failed.
    # retries=0: the data will not get better by checking it again.
    @task(trigger_rule="none_failed", retries=0)
    def quality_checks(plan: dict) -> int:
        conn = _warehouse()
        try:
            results = pipeline.check(
                conn, date.fromisoformat(plan["target_date"]),
                observed=_window(plan, "observed"),
                forecast=_window(plan, "forecast") if plan["load_forecast"] else None)
            return len(results)
        finally:
            conn.close()

    plan = plan_run()
    checks = quality_checks(plan)

    extract_observed(plan) >> transform_observed(plan) >> checks
    forecast_is_current(plan) >> extract_forecast(plan) >> transform_forecast(plan) >> checks


fairfield_weather_daily()
