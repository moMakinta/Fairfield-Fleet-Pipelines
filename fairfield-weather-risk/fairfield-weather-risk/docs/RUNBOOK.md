# Runbook

What to do when something goes wrong, and how to do the routine jobs.

## First: what happened?

```sql
-- one row: latest data, failures in the last week
SELECT * FROM reporting.v_pipeline_health;

-- every step of the most recent runs, newest first, with error messages
SELECT run_date, step, status, row_count, message, logged_at
FROM   audit.pipeline_step
ORDER  BY step_id DESC
LIMIT  20;

-- data quality checks that failed
SELECT run_date, check_name, failed_rows, checked_at
FROM   audit.data_quality_result
WHERE  NOT passed
ORDER  BY result_id DESC;
```

In the Airflow UI (http://localhost:8080): open the DAG, click the red square, open **Logs**.

## A task failed

| Task | Usual cause | What to do |
|---|---|---|
| `extract_observed` / `extract_forecast` | The API was unreachable, slow, or rate-limiting | Nothing at first. The task retries 3 times with growing waits. If it still fails, check https://open-meteo.com is up and your machine has internet, then **Clear** the task in the UI to run it again. Sites that did succeed are already stored and will simply be overwritten. |
| | "1 of 12 locations failed: XYZ: API returned HTTP 400" | The request for that site is wrong, most likely a bad latitude or longitude in `seeds/locations.csv`. Fix the CSV, restart (`docker compose up -d`), clear the task. |
| `transform_*` | "PayloadError": the API's answer does not have the expected structure | The raw answer is stored. Look at it: `SELECT payload FROM raw.weather_response WHERE run_date = '...' AND location_code = '...'`. If the API changed its format, `parsing.py` needs to follow. After the fix, clear the transform task. It replays from `raw` without calling the API. |
| `quality_checks` | The data broke a rule. The log names the check and the number of rows | See the next section. This task never retries on its own. |
| `plan_run` | "target_date ... is not in the past" | A manual run was given today's date or a future one. Trigger again with an earlier date. |

## A quality check failed

The data is already loaded when the checks run, so the question is whether it is wrong or the check is too strict.

1. Find the rows. For "every active location has a row for every day":
   ```sql
   SELECT l.location_code, d::date AS missing_day
   FROM   core.dim_location l
   CROSS  JOIN generate_series(date '2026-11-08', date '2026-11-10', interval '1 day') d
   LEFT   JOIN core.fact_weather_observed f ON f.location_key = l.location_key AND f.weather_date = d::date
   WHERE  l.is_active AND f.location_key IS NULL;
   ```
2. Compare with the raw answer for that site and run date in `raw.weather_response`.
3. If the API really had a gap, re-run the day later (the next daily run re-reads the last 3 days anyway, and often fills it).
4. If a real value is outside the plausible range, widen the range in `quality.py`.

## Re-running a day

Airflow UI → `fairfield_weather_daily` → ▶ **Trigger** → set `target_date` to the day (YYYY-MM-DD).

Or from a terminal:

```bash
docker compose exec airflow-scheduler airflow dags trigger fairfield_weather_daily --conf '{"target_date": "2026-10-20"}'
```

Re-running is always safe. The forecast branch is skipped for old dates.

## Filling a gap or loading more history

Airflow UI → `fairfield_weather_backfill` → ▶ **Trigger** → set `start_date` and `end_date`.

The daily DAG has `catchup=False`, so if the machine was off for a week, Airflow does not create seven runs when it comes back. It runs once, for yesterday. Use the backfill DAG for the days in between.

## Adding, changing or retiring a site

Edit `seeds/locations.csv`, then:

```bash
docker compose run --rm warehouse-init
```

- A new row is picked up by the next run. Backfill it if you want its history.
- To retire a site, set `is_active` to `false`. Its history stays, it is no longer fetched, and the checks stop expecting it. Do not delete the row.

Risk rules work the same way through `seeds/risk_rules.csv`. A rule deleted from the file is deleted from the database.

## Changing the database schema

Add a new file in `migrations/` with the next number, for example `004_add_humidity.sql`. It is applied on the next `docker compose up` (by `warehouse-init`) or by `python -m fairfield_weather setup`.

Do not edit a migration that has already been applied. A database that has run it will not run it again, so it would silently differ from a fresh one.

## Routine commands

```bash
docker compose ps                              # is everything healthy?
docker compose logs -f airflow-scheduler       # follow the scheduler
docker compose logs warehouse-init             # did the database set-up work?
docker compose restart airflow-dag-processor   # after adding a new DAG file, if it does not appear
docker compose down                            # stop, keep data
docker compose down -v                         # stop and delete everything
```

## Lost the passwords

They are in `.env`. If `.env` itself is lost, the databases cannot be opened with new passwords: run `docker compose down -v` (this deletes the data), then `python scripts/make_env.py` and start again. The weather history can be reloaded with the backfill DAG.
