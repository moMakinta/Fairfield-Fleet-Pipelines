"""End-to-end tests against a real PostgreSQL database, with the API replaced by the fake one.

Skipped unless TEST_DATABASE_URL is set (see conftest.py).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import TODAY
from fairfield_weather import migrate, pipeline, warehouse
from fairfield_weather.models import DateWindow
from fairfield_weather.pipeline import ExtractError
from fairfield_weather.quality import DataQualityError
from fairfield_weather.warehouse import transaction

TARGET = TODAY - timedelta(days=1)       # 2026-11-10
ISSUE = TODAY                            # 2026-11-11


def one(conn, query: str, params: tuple = ()):
    with transaction(conn) as cur:
        cur.execute(query, params)
        return cur.fetchone()[0]


def rows(conn, query: str, params: tuple = ()):
    with transaction(conn) as cur:
        cur.execute(query, params)
        return cur.fetchall()


# ------------------------------------------------------------------ set-up

def test_setup_creates_everything_and_can_be_run_again(conn):
    assert one(conn, "SELECT count(*) FROM core.dim_location WHERE is_active") == 12
    assert one(conn, "SELECT count(*) FROM core.risk_rule") == 8
    assert one(conn, "SELECT count(*) FROM audit.schema_migration") == 3

    assert migrate.apply_migrations(conn) == []          # nothing left to apply
    migrate.load_seeds(conn)                             # seeding twice must not duplicate
    assert one(conn, "SELECT count(*) FROM core.dim_location") == 12
    assert one(conn, "SELECT count(*) FROM core.risk_rule") == 8


# --------------------------------------------------------------- daily run

def test_daily_run_loads_observed_and_forecast(conn, client, settings, session):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY)

    # 12 locations x 3 lookback days, and 12 locations x 7 forecast days
    assert one(conn, "SELECT count(*) FROM core.fact_weather_observed") == 36
    assert one(conn, "SELECT count(*) FROM core.fact_weather_forecast") == 84
    assert rows(conn, "SELECT min(weather_date), max(weather_date) FROM core.fact_weather_observed") == [
        (TARGET - timedelta(days=2), TARGET)]
    assert rows(conn, "SELECT min(target_date), max(target_date), min(lead_days), max(lead_days) "
                      "FROM core.fact_weather_forecast WHERE issue_date = %s", (ISSUE,)) == [
        (ISSUE, ISSUE + timedelta(days=6), 0, 6)]

    # one API call per location per dataset, and the raw answers are kept
    assert len(session.calls) == 24
    assert one(conn, "SELECT count(*) FROM raw.weather_response") == 24
    assert one(conn, "SELECT count(*) FROM audit.data_quality_result WHERE NOT passed") == 0


def test_values_in_the_database_match_what_the_api_sent(conn, client, settings):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY, include_forecast=False)
    stored = rows(conn, """
        SELECT f.temp_max_c, f.temp_min_c, f.precipitation_mm, f.wind_speed_max_kmh, f.wind_gust_max_kmh,
               r.payload->'daily'->'temperature_2m_max'->>2, r.payload->'daily'->'wind_gusts_10m_max'->>2
        FROM   core.fact_weather_observed AS f
        JOIN   core.dim_location AS l USING (location_key)
        JOIN   raw.weather_response AS r ON r.location_code = l.location_code AND r.dataset = 'observed'
        WHERE  l.location_code = 'DUR' AND f.weather_date = %s""", (TARGET,))
    temp_max, temp_min, rain, wind, gust, raw_temp_max, raw_gust = stored[0]
    assert float(temp_max) == float(raw_temp_max) and float(gust) == float(raw_gust)
    assert temp_min <= temp_max and rain >= 0 and wind <= gust


def test_running_the_same_day_twice_changes_nothing(conn, client, settings):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY)
    before = rows(conn, "SELECT location_key, weather_date, temp_max_c, loaded_at FROM core.fact_weather_observed ORDER BY 1, 2")

    pipeline.run_daily(conn, client, settings, TARGET, TODAY)
    after = rows(conn, "SELECT location_key, weather_date, temp_max_c, loaded_at FROM core.fact_weather_observed ORDER BY 1, 2")

    assert after == before                               # same rows, and not even re-stamped
    assert one(conn, "SELECT count(*) FROM core.fact_weather_forecast") == 84
    assert one(conn, "SELECT count(*) FROM raw.weather_response") == 24
    assert one(conn, "SELECT count(*) FROM staging.weather_daily") == 36 + 84


def test_consecutive_days_overlap_without_duplicates(conn, client, settings):
    pipeline.run_daily(conn, client, settings, TARGET - timedelta(days=1), TODAY, include_forecast=False)
    pipeline.run_daily(conn, client, settings, TARGET, TODAY, include_forecast=False)
    # windows 7-9 Nov and 8-10 Nov together cover 4 distinct days
    assert one(conn, "SELECT count(*) FROM core.fact_weather_observed") == 12 * 4


def test_a_revised_figure_overwrites_the_old_one(conn, client, settings, session):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY, include_forecast=False)
    old = one(conn, "SELECT f.temp_max_c FROM core.fact_weather_observed f JOIN core.dim_location l USING (location_key) "
                    "WHERE l.location_code = 'DUR' AND f.weather_date = %s", (TARGET,))

    def revise(payload, params):
        if float(params["latitude"]) == -29.87:
            payload["daily"]["temperature_2m_max"][-1] += 1.5
        return payload

    session.transform = revise
    pipeline.extract(conn, client, "observed", TARGET, DateWindow(TARGET - timedelta(days=2), TARGET), TODAY)
    assert pipeline.transform(conn, "observed", TARGET) == 1       # exactly one row was different

    new = one(conn, "SELECT f.temp_max_c FROM core.fact_weather_observed f JOIN core.dim_location l USING (location_key) "
                    "WHERE l.location_code = 'DUR' AND f.weather_date = %s", (TARGET,))
    assert float(new) == pytest.approx(float(old) + 1.5)
    assert one(conn, "SELECT count(*) FROM core.fact_weather_observed") == 36


def test_transform_can_be_replayed_from_raw_without_calling_the_api(conn, client, settings, session):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY, include_forecast=False)
    calls_so_far = len(session.calls)

    with transaction(conn) as cur:                     # lose the modelled data, keep the raw answers
        cur.execute("TRUNCATE core.fact_weather_observed, staging.weather_daily")
    pipeline.transform(conn, "observed", TARGET)

    assert one(conn, "SELECT count(*) FROM core.fact_weather_observed") == 36
    assert len(session.calls) == calls_so_far


# ---------------------------------------------------------------- failures

def test_one_failing_location_fails_the_step_but_the_others_are_still_stored(conn, client, settings, session):
    session.fail_for_latitudes = {-29.87}                # Durban
    with pytest.raises(ExtractError, match="1 of 12 locations failed: DUR"):
        pipeline.extract(conn, client, "observed", TARGET, DateWindow(TARGET, TARGET), TODAY)

    assert one(conn, "SELECT count(*) FROM raw.weather_response") == 11
    assert rows(conn, "SELECT status, row_count FROM audit.pipeline_step WHERE step = 'extract_observed'") == [("failed", 11)]

    session.fail_for_latitudes = set()                   # the API recovers, the retry completes the set
    pipeline.extract(conn, client, "observed", TARGET, DateWindow(TARGET, TARGET), TODAY)
    assert one(conn, "SELECT count(*) FROM raw.weather_response") == 12


def test_quality_check_fails_when_a_location_is_missing(conn, client, settings):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY, include_forecast=False)
    with transaction(conn) as cur:
        cur.execute("DELETE FROM core.fact_weather_observed WHERE weather_date = %s AND location_key = "
                    "(SELECT location_key FROM core.dim_location WHERE location_code = 'CPT')", (TARGET,))

    with pytest.raises(DataQualityError, match=r"every active location has a row for every day \(1 rows\)"):
        pipeline.check(conn, TARGET, observed=DateWindow(TARGET, TARGET), forecast=None)
    assert one(conn, "SELECT count(*) FROM audit.data_quality_result WHERE NOT passed") == 1


def test_quality_check_fails_on_impossible_and_missing_values(conn, client, settings, session):
    def corrupt(payload, params):
        if float(params["latitude"]) == -33.91:          # Cape Town
            payload["daily"]["temperature_2m_min"][-1] = payload["daily"]["temperature_2m_max"][-1] + 5
            payload["daily"]["wind_gusts_10m_max"][-1] = None
            payload["daily"]["precipitation_sum"][-1] = -3.0
        return payload

    session.transform = corrupt
    with pytest.raises(DataQualityError) as failure:
        pipeline.run_daily(conn, client, settings, TARGET, TODAY, include_forecast=False)
    message = str(failure.value)
    assert "3 data quality check(s) failed" in message
    assert "no missing measurements" in message and "not above the maximum" in message and "physically plausible" in message


def test_an_inactive_location_is_not_fetched_and_not_expected(conn, client, settings, session):
    with transaction(conn) as cur:
        cur.execute("UPDATE core.dim_location SET is_active = false WHERE location_code = 'MPM'")
    pipeline.run_daily(conn, client, settings, TARGET, TODAY, include_forecast=False)
    assert len(session.calls) == 11
    assert one(conn, "SELECT count(*) FROM core.fact_weather_observed") == 33


# ---------------------------------------------------------------- backfill

def test_backfill_loads_a_year_in_chunks(conn, client, settings, session):
    year = DateWindow(date(2025, 1, 1), date(2025, 12, 31))
    pipeline.run_backfill(conn, client, settings, year, TODAY)

    assert one(conn, "SELECT count(*) FROM core.fact_weather_observed") == 12 * 365
    assert one(conn, "SELECT count(DISTINCT weather_date) FROM core.fact_weather_observed") == 365
    assert len(session.calls) == 12 * 3                  # 365 days in chunks of 180 = 3 calls per location
    assert all(url == settings.archive_url for url, _ in session.calls)


def test_backfill_then_daily_run_fit_together(conn, client, settings):
    pipeline.run_backfill(conn, client, settings, DateWindow(TARGET - timedelta(days=9), TARGET - timedelta(days=1)), TODAY)
    pipeline.run_daily(conn, client, settings, TARGET, TODAY)
    assert one(conn, "SELECT count(DISTINCT weather_date) FROM core.fact_weather_observed") == 10
    assert one(conn, "SELECT count(*) FROM core.fact_weather_observed") == 120


# ------------------------------------------------------------------- views

def test_risk_views_apply_the_rules(conn, client, settings):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY)
    with transaction(conn) as cur:                     # make Durban's target day stormy and hot
        cur.execute("""UPDATE core.fact_weather_observed SET wind_gust_max_kmh = 68, precipitation_mm = 55, temp_max_c = 36
                       WHERE weather_date = %s AND location_key =
                             (SELECT location_key FROM core.dim_location WHERE location_code = 'DUR')""", (TARGET,))
        cur.execute("""UPDATE core.fact_weather_observed SET wind_gust_max_kmh = 68, precipitation_mm = 0, temp_max_c = 25, temp_min_c = 12
                       WHERE weather_date = %s AND location_key =
                             (SELECT location_key FROM core.dim_location WHERE location_code = 'JHB')""", (TARGET,))

    durban = {r[0] for r in rows(conn, "SELECT rule_code FROM reporting.v_observed_risk WHERE location_code = 'DUR' AND weather_date = %s", (TARGET,))}
    assert durban == {"PORT_WIND_HOLD", "PORT_WIND_WATCH", "HEAVY_RAIN", "RAIN_WATCH", "EXTREME_HEAT", "HEAT_WATCH"}

    # the same 68 km/h gust at an inland depot breaks no rule: the port rules do not apply and 75 is not reached
    assert rows(conn, "SELECT rule_code FROM reporting.v_observed_risk WHERE location_code = 'JHB' AND weather_date = %s", (TARGET,)) == []

    with transaction(conn) as cur:
        cur.execute("""UPDATE core.fact_weather_observed SET temp_min_c = -2
                       WHERE weather_date = %s AND location_key =
                             (SELECT location_key FROM core.dim_location WHERE location_code = 'BFN')""", (TARGET,))
    assert rows(conn, "SELECT rule_code, comparison FROM reporting.v_observed_risk WHERE location_code = 'BFN' AND weather_date = %s AND metric = 'temp_min_c'", (TARGET,)) == [("FROST", "<=")]

    assert one(conn, "SELECT count(DISTINCT issue_date) FROM reporting.v_forecast_risk") <= 1


def test_forecast_accuracy_compares_forecasts_with_what_happened(conn, client, settings, session):
    # yesterday's run stored a forecast for today and tomorrow. A day later, those days are observed.
    pipeline.run_daily(conn, client, settings, TARGET, TODAY)
    later = TODAY + timedelta(days=2)
    session.today = later
    pipeline.run_daily(conn, client, settings, later - timedelta(days=1), later)

    accuracy = rows(conn, "SELECT lead_days, forecasts_compared, temp_max_mean_abs_error_c FROM reporting.v_forecast_accuracy ORDER BY 1")
    assert [(lead, compared) for lead, compared, _ in accuracy] == [(0, 12), (1, 12)]
    assert all(error is not None and error >= 0 for _, _, error in accuracy)


def test_monthly_summary_and_health_views(conn, client, settings):
    pipeline.run_backfill(conn, client, settings, DateWindow(date(2025, 1, 1), date(2025, 2, 28)), TODAY)
    summary = rows(conn, "SELECT month_start, days_recorded FROM reporting.v_site_monthly_summary WHERE location_code = 'JHB' ORDER BY 1")
    assert summary == [(date(2025, 1, 1), 31), (date(2025, 2, 1), 28)]

    health = rows(conn, "SELECT latest_observed_date, active_locations, observed_rows, failed_steps_last_7_days, failed_checks_last_7_days FROM reporting.v_pipeline_health")
    assert health == [(date(2025, 2, 28), 12, 12 * 59, 0, 0)]


def test_steps_are_logged(conn, client, settings):
    pipeline.run_daily(conn, client, settings, TARGET, TODAY)
    logged = rows(conn, "SELECT step, status FROM audit.pipeline_step ORDER BY step_id")
    assert logged == [("extract_observed", "success"), ("transform_observed", "success"),
                      ("extract_forecast", "success"), ("transform_forecast", "success"),
                      ("quality_checks", "success")]
    assert warehouse.active_locations(conn)[0].code == "BFN"
