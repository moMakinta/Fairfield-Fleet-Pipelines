"""
### Fairfield weather: load history

Has no schedule. Trigger it by hand and give it a date range:

- `start_date`, for example `2025-01-01`
- `end_date`, for example `2025-12-31`

It loads observed weather for every site over that range, one API call per
site per 180 days, so a full year is about 36 calls. It is safe to run again
for the same or an overlapping range.

Use this once after installing, and again if a gap ever needs to be filled.
"""
from __future__ import annotations

from datetime import date, timedelta

from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Param, dag, get_current_context, task

from fairfield_weather import pipeline
from fairfield_weather.api import OpenMeteoClient
from fairfield_weather.config import Settings
from fairfield_weather.dates import local_today
from fairfield_weather.models import DateWindow

WAREHOUSE_CONN_ID = "fairfield_warehouse"


@dag(
    dag_id="fairfield_weather_backfill",
    schedule=None,
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "data-engineering",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(hours=1),
    },
    params={
        "start_date": Param("2025-01-01", type="string", format="date", description="First day to load (YYYY-MM-DD)"),
        "end_date": Param("2025-12-31", type="string", format="date", description="Last day to load (YYYY-MM-DD)"),
    },
    tags=["fairfield", "weather", "backfill"],
    doc_md=__doc__,
)
def fairfield_weather_backfill():

    @task
    def load_history() -> int:
        params = get_current_context()["params"]
        settings = Settings()
        today = local_today(settings.timezone)
        window = DateWindow(date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"]))
        if window.end >= today:
            raise ValueError(f"end_date {window.end} must be before today ({today}). Only days that are over can be loaded.")

        conn = PostgresHook(postgres_conn_id=WAREHOUSE_CONN_ID).get_conn()
        try:
            return pipeline.run_backfill(conn, OpenMeteoClient(settings), settings, window, today)
        finally:
            conn.close()

    load_history()


fairfield_weather_backfill()
