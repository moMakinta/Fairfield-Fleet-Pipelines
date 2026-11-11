-- 001: schemas, the raw layer, staging and audit tables.
--
-- Layers:
--   raw        the API answers exactly as received (JSON)
--   staging    one run's answers parsed into rows, replaced on every run
--   core       the modelled tables everything else reads from
--   reporting  views for people and dashboards
--   audit      what the pipeline did and whether the data passed its checks

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS reporting;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE raw.weather_response (
    response_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset       text        NOT NULL CHECK (dataset IN ('observed', 'forecast')),
    location_code text        NOT NULL,
    run_date      date        NOT NULL,     -- observed: the target date of the run. forecast: the issue date
    request_url   text        NOT NULL,
    payload       jsonb       NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_weather_response UNIQUE (dataset, location_code, run_date)
);

CREATE TABLE staging.weather_daily (
    dataset            text         NOT NULL CHECK (dataset IN ('observed', 'forecast')),
    run_date           date         NOT NULL,
    location_code      text         NOT NULL,
    weather_date       date         NOT NULL,
    temp_max_c         numeric(5,1),
    temp_min_c         numeric(5,1),
    precipitation_mm   numeric(6,1),
    wind_speed_max_kmh numeric(5,1),
    wind_gust_max_kmh  numeric(5,1),
    CONSTRAINT pk_staging_weather_daily PRIMARY KEY (dataset, run_date, location_code, weather_date)
);

CREATE TABLE audit.pipeline_step (
    step_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_date  date        NOT NULL,
    step      text        NOT NULL,
    status    text        NOT NULL CHECK (status IN ('success', 'failed')),
    row_count integer     NOT NULL DEFAULT 0,
    message   text,
    logged_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_pipeline_step_run_date ON audit.pipeline_step (run_date);

CREATE TABLE audit.data_quality_result (
    result_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_date    date        NOT NULL,
    check_name  text        NOT NULL,
    passed      boolean     NOT NULL,
    failed_rows integer     NOT NULL,
    checked_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_data_quality_result_run_date ON audit.data_quality_result (run_date);
