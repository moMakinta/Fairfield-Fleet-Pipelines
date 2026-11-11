# Fairfield Weather Risk Pipeline

A scheduled data pipeline that tells Fairfield Chemical Transportation, every morning, where the weather was or will be a problem for moving chemicals: ports too windy to load ships, roads at risk of flooding, days hot enough to matter for volatile cargo.

It pulls live data from a public weather API, is orchestrated with Apache Airflow, stores everything in PostgreSQL, and runs in Docker with one command.

Author: Oregomoditse Makinta

This is the companion to my `fairfield-fleet-pipeline` repository for the same fictional company. That project is a batch ETL over files. This one covers what it does not: a live source, a schedule, retries, incremental loads and backfills.

| | |
|---|---|
| **Source** | [Open-Meteo](https://open-meteo.com) weather API (no key needed) |
| **Orchestration** | Apache Airflow 3 (two DAGs) |
| **Storage** | PostgreSQL 16, in layers: raw → staging → core → reporting |
| **Language** | Python 3.10+, SQL |
| **Runs in** | Docker Compose |
| **Quality** | 71 automated tests, data quality checks on every run, CI on GitHub Actions |

## What it does

Fairfield has 12 sites: depots in Johannesburg, Bloemfontein, Rustenburg and Polokwane, plants at Sasolburg and Secunda, and port terminals from Cape Town round to Maputo.

Every day at 05:00 South African time the pipeline:

1. **Fetches yesterday's weather** for all 12 sites, plus the two days before it, because weather services revise recent figures.
2. **Fetches the 7-day forecast** for all 12 sites.
3. **Stores the raw API answers** untouched, then parses them and merges them into the warehouse.
4. **Checks the data** and fails loudly if something is missing or impossible.
5. **Applies risk rules** so operations can see, per site and per day, what needs attention.

The rules are data, not code. They live in `seeds/risk_rules.csv`:

| Rule | Applies to | Triggers when | Severity |
|---|---|---|---|
| `PORT_WIND_HOLD` | Ports | gusts ≥ 60 km/h | High |
| `PORT_WIND_WATCH` | Ports | gusts ≥ 45 km/h | Medium |
| `STRONG_WIND` | All sites | gusts ≥ 75 km/h | High |
| `HEAVY_RAIN` | All sites | rain ≥ 50 mm | High |
| `RAIN_WATCH` | All sites | rain ≥ 20 mm | Medium |
| `EXTREME_HEAT` | All sites | max temperature ≥ 35 °C | High |
| `HEAT_WATCH` | All sites | max temperature ≥ 32 °C | Medium |
| `FROST` | All sites | min temperature ≤ 0 °C | Low |

The thresholds are illustrative. A real operations team would set their own, and can: edit the CSV and restart, no code change.

## Architecture

```
                         ┌──────────────────────── Airflow (scheduler, retries, UI) ───────────────────────┐
                         │                                                                                  │
  Open-Meteo API ──────► │  extract ──► raw.weather_response ──► transform ──► core.fact_weather_observed   │
  (forecast + archive)   │  (HTTP,       (JSON, exactly as        (parse,       core.fact_weather_forecast   │
                         │   retries)     received)                 upsert)              │                   │
                         │                                                               ▼                   │
                         │                                          quality checks ──► audit.*               │
                         └──────────────────────────────────────────────────────────────┬────────────────────┘
                                                                                        ▼
                                              core.risk_rule ──► reporting views ──► SQL / Excel / BI tool
```

### The two DAGs

**`fairfield_weather_daily`** runs at 05:00 every day.

```
plan_run ─┬─► extract_observed ──► transform_observed ──────────────────────┐
          │                                                                 ├─► quality_checks
          └─► forecast_is_current ──► extract_forecast ──► transform_forecast ┘
```

`plan_run` decides the dates once so every task agrees on them. `forecast_is_current` skips the forecast branch when an old date is re-run, because a forecast can only be fetched for "now". `quality_checks` still runs in that case.

**`fairfield_weather_backfill`** has no schedule. You trigger it with a start and end date to load history. It asks for 180 days per call instead of one day, so a whole year for 12 sites is 36 API calls rather than 4,380.

### The layers

| Schema | Holds | Why it exists |
|---|---|---|
| `raw` | The API's JSON answers, one per site per run | If the parsing or the model changes, everything can be rebuilt without calling the API again |
| `staging` | One run's answers parsed into rows | A clean hand-over point between Python and SQL |
| `core` | `dim_location`, `risk_rule`, `fact_weather_observed`, `fact_weather_forecast` | The modelled data everything reads from |
| `reporting` | Views: risk flags, forecast accuracy, monthly summary, pipeline health | What people and dashboards query |
| `audit` | Every step that ran, every check result, which migrations were applied | To answer "what happened last night?" |

Forecasts are stored per **issue date** and **target date**. Keeping every issue means the forecast for a day can later be compared with what actually happened (`reporting.v_forecast_accuracy`).

## Quick start with Docker

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (give it at least 4 GB of memory) and Python 3.10+ for one small script.

```bash
# 1. create .env with random passwords (prints the logins you will need)
python scripts/make_env.py

# 2. start everything. The first start downloads the images and takes a few minutes
docker compose up -d

# 3. wait until every service is healthy
docker compose ps
```

Then:

1. Open **http://localhost:8080** and log in with the Airflow login that `make_env.py` printed.
2. Run **`fairfield_weather_backfill`** once (the ▶ button). The default range is all of 2025, the same year as the fleet project's data.
3. Switch **`fairfield_weather_daily`** on with its toggle. It runs every morning from then on. Press ▶ to run it right away.

Look at the results in any PostgreSQL client (psql, DBeaver, pgAdmin, or Excel via ODBC) at `localhost:5433`, database `fairfield_weather`, with the warehouse login that `make_env.py` printed:

```sql
SELECT * FROM reporting.v_pipeline_health;
SELECT * FROM reporting.v_forecast_risk ORDER BY target_date;
```

`sql/analysis_queries.sql` has ten more, including consecutive rain days per site and whether yesterday's forecast warned about today's wind.

To stop: `docker compose down`. To stop and delete all data: `docker compose down -v`.

**Before the first real run**, this one-liner makes a single live API call and prints two days of weather for Durban. If it works, the pipeline can reach the API:

```bash
docker compose run --rm warehouse-init python -m fairfield_weather check-api
```

## Running without Docker or Airflow

The pipeline logic is a plain Python package, so it also runs from the command line against any PostgreSQL database.

```bash
python -m venv .venv
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

set FAIRFIELD_DB_URL=postgresql://user:password@localhost:5432/fairfield_weather     # macOS/Linux: export

python -m fairfield_weather setup           # create tables, load sites and rules
python -m fairfield_weather backfill --start 2025-01-01 --end 2025-12-31
python -m fairfield_weather daily           # yesterday + forecast
python -m fairfield_weather daily --date 2026-10-20     # re-run one day
```

### Trying it with no internet

`tools/fake_open_meteo.py` is a small web server that answers like Open-Meteo with invented, repeatable weather. Start it and point the pipeline at it:

```bash
python tools/fake_open_meteo.py --port 8089
set FAIRFIELD_FORECAST_URL=http://localhost:8089/v1/forecast
set FAIRFIELD_ARCHIVE_URL=http://localhost:8089/v1/archive
```

The tests and the CI pipeline use the same stand-in, so they never depend on someone else's server being up.

## Design decisions

**Every step can be run twice.** Raw answers are upserted per site and run date. Staging is replaced per run. Facts are upserted on their natural key, and only rewritten when a figure actually changed. So a retry, a re-run, or an overlapping backfill never duplicates or loses anything. There is a test that runs the same day twice and checks that not even the `loaded_at` timestamps move.

**Extract and transform are separate tasks.** Extract only talks to the API and stores what it got. Transform only reads what was stored. If parsing fails, the retry does not call the API again, and if the model changes later, history can be replayed from `raw`.

**Recent days are reloaded.** Weather models revise the last few days, so each run re-reads a 3-day window and overwrites it. `source_run_date` on each row records which run wrote it last.

**The schedule's date, not the clock.** A run's target date comes from when the run was *scheduled* (`data_interval_end`), not from the time the task happens to execute. A run that was due yesterday but only starts today still loads the right day. All dates are South African local dates wherever the code runs.

**Retries where they help.** HTTP 429 and 5xx are retried with increasing waits, at the HTTP level and again at the Airflow task level. HTTP 400 is not retried, because a wrong request stays wrong. The quality check has no retries, because checking bad data again does not fix it.

**One bad site does not hide the others.** Extract tries every site before failing, stores the ones that worked, and reports all the failures together.

**The database is versioned.** Tables are created by numbered migration files that are each applied exactly once and recorded in `audit.schema_migration`. Changing the schema later means adding file 004, not editing and re-running 002.

**No Airflow in the business logic.** `src/fairfield_weather` does not import Airflow. The DAGs are a thin layer over it. That is why the same code runs from the command line, and why the tests are fast.

**Driver-agnostic SQL code.** Airflow's PostgresHook returns a psycopg2 or a psycopg 3 connection depending on the provider version, and the two behave differently (`with conn:` commits in one and closes the connection in the other). The warehouse code uses only what both share, and every integration test runs once with each.

## Data quality checks

Run at the end of every DAG run. Any failure fails the run, and every result is kept in `audit.data_quality_result`.

| Check | Catches |
|---|---|
| Every active site has a row for every day | A site the API silently skipped |
| No missing measurements | Gaps in the source data |
| Minimum temperature is not above the maximum | Swapped or corrupt values |
| Values are physically plausible | Unit changes, sensor nonsense (−30 to 55 °C, 0 to 600 mm, and so on) |
| Nothing is dated after the run | Date or time zone mistakes |
| Every site has all 7 forecast days | A truncated forecast |
| Forecast lead days match the dates | Bugs in the date arithmetic |

## Tests

```bash
pytest                                                          # unit tests only
set TEST_DATABASE_URL=postgresql://user:password@localhost:5432/fairfield_test
pytest                                                          # plus the integration tests
```

The test database is wiped by the tests. Never point `TEST_DATABASE_URL` at one you care about.

| File | Tests | What they cover |
|---|---|---|
| `test_dates.py` | 11 | Target dates, windows, time zones, month and year boundaries, chunking |
| `test_parsing.py` | 11 | Reading a response, and eight ways a response can be damaged |
| `test_api.py` | 10 | Request parameters, endpoint choice, error answers, network failures, retry policy |
| `test_pipeline_integration.py` | 17 × 2 drivers | Whole runs against a real PostgreSQL: idempotency, revisions, replay from raw, partial failures, quality failures, backfill, every reporting view |
| `test_dags.py` | 5 | DAG files import, task wiring, trigger rules, schedule settings |

### CI

`.github/workflows/ci.yml` runs on every push:

1. **Lint and tests**: ruff, then all tests with a PostgreSQL service container.
2. **Airflow DAGs**: installs Airflow, loads the DAG files, then runs both DAGs from start to finish against PostgreSQL and the stand-in API, and checks the row counts in the warehouse.
3. **Compose**: validates `docker-compose.yaml`.

## Project layout

```
├── dags/                         the two Airflow DAGs (thin: they call the package)
├── src/fairfield_weather/
│   ├── config.py                 settings, each overridable by an environment variable
│   ├── dates.py                  target dates and windows
│   ├── api.py                    Open-Meteo client with retries
│   ├── parsing.py                JSON answer -> one record per day, with validation
│   ├── warehouse.py              all SQL that writes: raw, staging, upserts, audit
│   ├── quality.py                data quality checks
│   ├── pipeline.py               the steps: extract, transform, check
│   ├── migrate.py                migration runner and seed loader
│   └── __main__.py               command line
├── migrations/                   numbered SQL files, applied once each
├── seeds/                        locations.csv, risk_rules.csv
├── sql/analysis_queries.sql      example questions and answers
├── tools/fake_open_meteo.py      stand-in API for tests and offline runs
├── tests/
├── scripts/make_env.py           generates .env with random secrets
├── docs/RUNBOOK.md               what to do when something fails
├── docker-compose.yaml
└── .github/workflows/ci.yml
```

## Limitations

- **Single machine.** The LocalExecutor runs tasks inside the scheduler container. That suits 12 sites and a few dozen API calls a day. More would need the CeleryExecutor or KubernetesExecutor.
- **No alerting.** A failed run shows red in the Airflow UI, and `reporting.v_pipeline_health` shows it in SQL, but nothing emails or messages anyone. Airflow supports this through callbacks and notifiers once there is somewhere to send to.
- **Forecast history cannot be backfilled.** The backfill loads observations only. Forecasts are only stored from the day the daily DAG is switched on, so the accuracy view fills up over time.
- **Daily values only.** A gust at 03:00 and one during a loading shift count the same. Hourly data would make the port rules more precise.
- **Not joined to the fleet data.** The site codes match the fleet project's `DimLocation`, so trips could be matched to the weather at their origin and destination, but the two projects use different databases (SQL Server and PostgreSQL) and nothing copies data between them yet.
- **The code is mounted into the containers** rather than built into an image. That is convenient on one machine. A deployment would bake a versioned image.
- **Free API tier.** Open-Meteo's free tier is for non-commercial use, with a fair-use limit of about 10,000 calls a day. This pipeline makes 24 a day.

## Data source and licence

Weather data by [Open-Meteo.com](https://open-meteo.com), offered under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Fairfield Chemical Transportation is fictional. The places and the weather are real.
