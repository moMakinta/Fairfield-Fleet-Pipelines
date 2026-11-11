"""Everything that talks to the PostgreSQL warehouse.

Every function takes an open database connection and does its work in one
transaction: it either all happens or none of it does. Every write is an
upsert or a replace, so running the same step twice leaves the same data.

The code only uses what psycopg2 and psycopg 3 have in common. That matters
because Airflow's PostgresHook hands out one or the other depending on the
provider version, and the two disagree on details (for example, `with conn:`
commits in psycopg2 but closes the connection in psycopg 3).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from fairfield_weather.models import DailyWeather, Dataset, Location


@contextmanager
def transaction(conn) -> Iterator[Any]:
    """A cursor whose work is committed if the block finishes and rolled back if it raises."""
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        cur.close()


def active_locations(conn) -> list[Location]:
    with transaction(conn) as cur:
        cur.execute(
            "SELECT location_code, location_name, latitude, longitude "
            "FROM core.dim_location WHERE is_active ORDER BY location_code")
        return [Location(code, name, float(lat), float(lon)) for code, name, lat, lon in cur.fetchall()]


# ---------------------------------------------------------------- raw layer

def save_raw_response(conn, dataset: Dataset, location_code: str, run_date: date,
                      request_url: str, payload: dict[str, Any]) -> None:
    """Keep the API answer exactly as received. A re-run for the same day replaces it."""
    with transaction(conn) as cur:
        cur.execute(
            """
            INSERT INTO raw.weather_response (dataset, location_code, run_date, request_url, payload)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (dataset, location_code, run_date) DO UPDATE
               SET request_url = EXCLUDED.request_url,
                   payload     = EXCLUDED.payload,
                   fetched_at  = now()
            """,
            (dataset, location_code, run_date, request_url, json.dumps(payload)))


def raw_responses(conn, dataset: Dataset, run_date: date) -> list[tuple[str, dict[str, Any]]]:
    with transaction(conn) as cur:
        cur.execute(
            "SELECT location_code, payload FROM raw.weather_response "
            "WHERE dataset = %s AND run_date = %s ORDER BY location_code",
            (dataset, run_date))
        # the drivers already turn jsonb into a dict; the isinstance check covers one that returns text
        return [(code, payload if isinstance(payload, dict) else json.loads(payload))
                for code, payload in cur.fetchall()]


# ------------------------------------------------------------ staging layer

def replace_staging(conn, dataset: Dataset, run_date: date, records: list[DailyWeather]) -> int:
    """Staging holds the parsed rows of one run. Old rows for the same run are cleared first."""
    rows = [(dataset, run_date, r.location_code, r.weather_date, r.temp_max_c, r.temp_min_c,
             r.precipitation_mm, r.wind_speed_max_kmh, r.wind_gust_max_kmh) for r in records]
    with transaction(conn) as cur:
        cur.execute("DELETE FROM staging.weather_daily WHERE dataset = %s AND run_date = %s", (dataset, run_date))
        if rows:
            cur.executemany(
                """
                INSERT INTO staging.weather_daily
                    (dataset, run_date, location_code, weather_date, temp_max_c, temp_min_c,
                     precipitation_mm, wind_speed_max_kmh, wind_gust_max_kmh)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, rows)
    return len(rows)


# --------------------------------------------------------------- core layer

def merge_observed(conn, run_date: date) -> int:
    """Insert new days and overwrite days whose figures were revised. Returns the rows inserted or changed."""
    with transaction(conn) as cur:
        cur.execute(
            """
            INSERT INTO core.fact_weather_observed AS f
                (location_key, weather_date, temp_max_c, temp_min_c, precipitation_mm,
                 wind_speed_max_kmh, wind_gust_max_kmh, source_run_date)
            SELECT l.location_key, s.weather_date, s.temp_max_c, s.temp_min_c, s.precipitation_mm,
                   s.wind_speed_max_kmh, s.wind_gust_max_kmh, s.run_date
            FROM   staging.weather_daily AS s
            JOIN   core.dim_location     AS l ON l.location_code = s.location_code
            WHERE  s.dataset = 'observed' AND s.run_date = %s
            ON CONFLICT (location_key, weather_date) DO UPDATE
               SET temp_max_c         = EXCLUDED.temp_max_c,
                   temp_min_c         = EXCLUDED.temp_min_c,
                   precipitation_mm   = EXCLUDED.precipitation_mm,
                   wind_speed_max_kmh = EXCLUDED.wind_speed_max_kmh,
                   wind_gust_max_kmh  = EXCLUDED.wind_gust_max_kmh,
                   source_run_date    = EXCLUDED.source_run_date,
                   loaded_at          = now()
             -- only touch the row when a figure really changed (IS DISTINCT FROM also handles NULLs)
             WHERE (f.temp_max_c, f.temp_min_c, f.precipitation_mm, f.wind_speed_max_kmh, f.wind_gust_max_kmh)
                   IS DISTINCT FROM
                   (EXCLUDED.temp_max_c, EXCLUDED.temp_min_c, EXCLUDED.precipitation_mm,
                    EXCLUDED.wind_speed_max_kmh, EXCLUDED.wind_gust_max_kmh)
            """,
            (run_date,))
        return cur.rowcount


def merge_forecast(conn, issue_date: date) -> int:
    """One row per location, per day the forecast was issued, per day it is for."""
    with transaction(conn) as cur:
        cur.execute(
            """
            INSERT INTO core.fact_weather_forecast AS f
                (location_key, issue_date, target_date, lead_days, temp_max_c, temp_min_c,
                 precipitation_mm, wind_speed_max_kmh, wind_gust_max_kmh)
            SELECT l.location_key, s.run_date, s.weather_date, s.weather_date - s.run_date,
                   s.temp_max_c, s.temp_min_c, s.precipitation_mm, s.wind_speed_max_kmh, s.wind_gust_max_kmh
            FROM   staging.weather_daily AS s
            JOIN   core.dim_location     AS l ON l.location_code = s.location_code
            WHERE  s.dataset = 'forecast' AND s.run_date = %s
            ON CONFLICT (location_key, issue_date, target_date) DO UPDATE
               SET temp_max_c         = EXCLUDED.temp_max_c,
                   temp_min_c         = EXCLUDED.temp_min_c,
                   precipitation_mm   = EXCLUDED.precipitation_mm,
                   wind_speed_max_kmh = EXCLUDED.wind_speed_max_kmh,
                   wind_gust_max_kmh  = EXCLUDED.wind_gust_max_kmh,
                   loaded_at          = now()
             WHERE (f.temp_max_c, f.temp_min_c, f.precipitation_mm, f.wind_speed_max_kmh, f.wind_gust_max_kmh)
                   IS DISTINCT FROM
                   (EXCLUDED.temp_max_c, EXCLUDED.temp_min_c, EXCLUDED.precipitation_mm,
                    EXCLUDED.wind_speed_max_kmh, EXCLUDED.wind_gust_max_kmh)
            """,
            (issue_date,))
        return cur.rowcount


# -------------------------------------------------------------------- audit

def log_step(conn, run_date: date, step: str, status: str, row_count: int = 0, message: str | None = None) -> None:
    with transaction(conn) as cur:
        cur.execute(
            "INSERT INTO audit.pipeline_step (run_date, step, status, row_count, message) VALUES (%s, %s, %s, %s, %s)",
            (run_date, step, status, row_count, message))
