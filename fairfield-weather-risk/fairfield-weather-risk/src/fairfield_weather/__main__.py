"""Command line entry point, so the pipeline can be run without Airflow.

    python -m fairfield_weather setup
    python -m fairfield_weather check-api
    python -m fairfield_weather daily [--date 2026-11-10] [--no-forecast]
    python -m fairfield_weather backfill --start 2025-01-01 --end 2025-12-31

The database comes from the FAIRFIELD_DB_URL environment variable.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from fairfield_weather import migrate, pipeline
from fairfield_weather.api import OpenMeteoClient
from fairfield_weather.config import Settings, database_url
from fairfield_weather.dates import local_today
from fairfield_weather.models import DateWindow, Location
from fairfield_weather.parsing import parse_daily


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fairfield_weather", description="Fairfield weather risk pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("setup", help="create or upgrade the database and load the reference data")
    commands.add_parser("check-api", help="make one live API call and print the result (no database needed)")

    daily = commands.add_parser("daily", help="load recent observations and today's forecast")
    daily.add_argument("--date", type=date.fromisoformat, help="target date, default is yesterday")
    daily.add_argument("--no-forecast", action="store_true", help="observations only")

    backfill = commands.add_parser("backfill", help="load a range of history")
    backfill.add_argument("--start", type=date.fromisoformat, required=True)
    backfill.add_argument("--end", type=date.fromisoformat, required=True)
    return parser


def _connect(url: str):
    """Open the warehouse with whichever PostgreSQL driver is installed (the code works with both)."""
    try:
        import psycopg2 as driver
    except ImportError:
        import psycopg as driver
    return driver.connect(url)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s  %(message)s")
    settings = Settings()
    today = local_today(settings.timezone)

    if args.command == "check-api":
        yesterday = today - timedelta(days=1)
        durban = Location("DUR", "Durban Port Terminal", -29.87, 31.03)
        url, payload = OpenMeteoClient(settings).fetch_daily(durban, DateWindow(yesterday, today), today)
        print(url)
        for record in parse_daily(payload, durban.code):
            print(record)
        return 0

    conn = _connect(database_url())
    try:
        if args.command == "setup":
            migrate.setup_database(conn)
        elif args.command == "daily":
            target = args.date or today - timedelta(days=1)
            # a forecast can only be fetched for "now", so it is skipped when re-running an old date
            is_current = target >= today - timedelta(days=1)
            pipeline.run_daily(conn, OpenMeteoClient(settings), settings, target, today,
                               include_forecast=is_current and not args.no_forecast)
        elif args.command == "backfill":
            pipeline.run_backfill(conn, OpenMeteoClient(settings), settings, DateWindow(args.start, args.end), today)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
