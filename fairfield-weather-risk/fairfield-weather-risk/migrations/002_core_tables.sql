-- 002: the core model.

-- Fairfield's depots, plants and ports. The codes are the same ones used in the fleet pipeline.
CREATE TABLE core.dim_location (
    location_key  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_code text         NOT NULL UNIQUE,
    location_name text         NOT NULL,
    location_type text         NOT NULL CHECK (location_type IN ('Depot', 'Plant', 'Port')),
    city          text         NOT NULL,
    latitude      numeric(8,5) NOT NULL CHECK (latitude  BETWEEN -90  AND 90),
    longitude     numeric(8,5) NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    is_active     boolean      NOT NULL DEFAULT true
);

-- When does weather become an operational problem? Kept as data, not code,
-- so the operations team can change a threshold without a code change.
CREATE TABLE core.risk_rule (
    rule_code     text PRIMARY KEY,
    description   text    NOT NULL,
    location_type text    CHECK (location_type IN ('Depot', 'Plant', 'Port')),   -- NULL = applies everywhere
    metric        text    NOT NULL CHECK (metric IN ('temp_max_c', 'temp_min_c', 'precipitation_mm',
                                                     'wind_speed_max_kmh', 'wind_gust_max_kmh')),
    comparison    text    NOT NULL CHECK (comparison IN ('>=', '<=')),
    threshold     numeric NOT NULL,
    severity      text    NOT NULL CHECK (severity IN ('Low', 'Medium', 'High'))
);

-- What the weather was. One row per location per day.
CREATE TABLE core.fact_weather_observed (
    location_key       integer      NOT NULL REFERENCES core.dim_location (location_key),
    weather_date       date         NOT NULL,
    temp_max_c         numeric(5,1),
    temp_min_c         numeric(5,1),
    precipitation_mm   numeric(6,1),
    wind_speed_max_kmh numeric(5,1),
    wind_gust_max_kmh  numeric(5,1),
    source_run_date    date         NOT NULL,                 -- which run last wrote this row
    loaded_at          timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_fact_weather_observed PRIMARY KEY (location_key, weather_date)
);
CREATE INDEX ix_fact_weather_observed_date ON core.fact_weather_observed (weather_date);

-- What the weather was expected to be. One row per location, per day the forecast
-- was issued, per day it is for. Keeping every issue makes it possible to measure
-- afterwards how good the forecasts were.
CREATE TABLE core.fact_weather_forecast (
    location_key       integer      NOT NULL REFERENCES core.dim_location (location_key),
    issue_date         date         NOT NULL,
    target_date        date         NOT NULL,
    lead_days          smallint     NOT NULL CHECK (lead_days >= 0),   -- 0 = the issue date itself
    temp_max_c         numeric(5,1),
    temp_min_c         numeric(5,1),
    precipitation_mm   numeric(6,1),
    wind_speed_max_kmh numeric(5,1),
    wind_gust_max_kmh  numeric(5,1),
    loaded_at          timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_fact_weather_forecast PRIMARY KEY (location_key, issue_date, target_date)
);
CREATE INDEX ix_fact_weather_forecast_target ON core.fact_weather_forecast (target_date);
