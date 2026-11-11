"""Shared test setup.

The integration tests need a PostgreSQL database they are allowed to wipe.
Point TEST_DATABASE_URL at one, for example:

    set TEST_DATABASE_URL=postgresql://fairfield:fairfield@localhost:5433/fairfield_test

Without it, those tests are skipped and only the unit tests run.
"""
from __future__ import annotations

import os
from datetime import date

import pytest

from fairfield_weather.api import OpenMeteoClient
from fairfield_weather.config import Settings
from fake_open_meteo import FakeSession

TODAY = date(2026, 11, 11)      # a fixed "today" so the tests give the same result on any day


@pytest.fixture
def settings() -> Settings:
    return Settings(pause_between_requests_seconds=0, lookback_days=3, forecast_days=7)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession(today=TODAY)


@pytest.fixture
def client(settings, session) -> OpenMeteoClient:
    return OpenMeteoClient(settings, session=session)


# Every integration test runs twice: once with psycopg2 (what the command line uses) and once
# with psycopg 3 (what newer Airflow PostgresHooks hand out), because the two behave differently.
@pytest.fixture(params=["psycopg2", "psycopg"])
def conn(request):
    """A connection to an empty, freshly migrated and seeded test database."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    driver = pytest.importorskip(request.param)

    from fairfield_weather import migrate
    from fairfield_weather.warehouse import transaction

    connection = driver.connect(url)
    with transaction(connection) as cur:
        cur.execute("DROP SCHEMA IF EXISTS raw, staging, core, reporting, audit CASCADE")
    migrate.setup_database(connection)
    yield connection
    connection.close()
