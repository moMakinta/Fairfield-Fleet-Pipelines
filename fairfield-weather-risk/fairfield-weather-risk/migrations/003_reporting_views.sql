-- 003: reporting views.

-- Days on which the observed weather broke a risk rule.
-- The LATERAL (VALUES ...) part turns the five measurement columns into five rows,
-- so one join can compare every measurement against every rule for that metric.
CREATE VIEW reporting.v_observed_risk AS
SELECT l.location_code,
       l.location_name,
       l.location_type,
       f.weather_date,
       r.rule_code,
       r.severity,
       r.description,
       m.metric,
       m.value,
       r.comparison,
       r.threshold
FROM   core.fact_weather_observed AS f
JOIN   core.dim_location          AS l USING (location_key)
CROSS  JOIN LATERAL (VALUES ('temp_max_c',         f.temp_max_c),
                            ('temp_min_c',         f.temp_min_c),
                            ('precipitation_mm',   f.precipitation_mm),
                            ('wind_speed_max_kmh', f.wind_speed_max_kmh),
                            ('wind_gust_max_kmh',  f.wind_gust_max_kmh)) AS m (metric, value)
JOIN   core.risk_rule AS r
       ON  r.metric = m.metric
       AND (r.location_type IS NULL OR r.location_type = l.location_type)
       AND ((r.comparison = '>=' AND m.value >= r.threshold) OR (r.comparison = '<=' AND m.value <= r.threshold));

-- The same rules applied to the most recent forecast: what should operations plan around this week?
CREATE VIEW reporting.v_forecast_risk AS
SELECT l.location_code,
       l.location_name,
       l.location_type,
       f.issue_date,
       f.target_date,
       f.lead_days,
       r.rule_code,
       r.severity,
       r.description,
       m.metric,
       m.value,
       r.comparison,
       r.threshold
FROM   core.fact_weather_forecast AS f
JOIN   core.dim_location          AS l USING (location_key)
CROSS  JOIN LATERAL (VALUES ('temp_max_c',         f.temp_max_c),
                            ('temp_min_c',         f.temp_min_c),
                            ('precipitation_mm',   f.precipitation_mm),
                            ('wind_speed_max_kmh', f.wind_speed_max_kmh),
                            ('wind_gust_max_kmh',  f.wind_gust_max_kmh)) AS m (metric, value)
JOIN   core.risk_rule AS r
       ON  r.metric = m.metric
       AND (r.location_type IS NULL OR r.location_type = l.location_type)
       AND ((r.comparison = '>=' AND m.value >= r.threshold) OR (r.comparison = '<=' AND m.value <= r.threshold))
WHERE  f.issue_date = (SELECT max(issue_date) FROM core.fact_weather_forecast);

-- How far off were the forecasts? Each forecast is compared with what was later observed
-- for the same location and day, grouped by how many days ahead the forecast was made.
CREATE VIEW reporting.v_forecast_accuracy AS
SELECT fc.lead_days,
       count(*)                                                            AS forecasts_compared,
       round(avg(abs(fc.temp_max_c         - ob.temp_max_c)), 2)           AS temp_max_mean_abs_error_c,
       round(avg(abs(fc.precipitation_mm   - ob.precipitation_mm)), 2)     AS precipitation_mean_abs_error_mm,
       round(avg(abs(fc.wind_gust_max_kmh  - ob.wind_gust_max_kmh)), 2)    AS wind_gust_mean_abs_error_kmh
FROM   core.fact_weather_forecast AS fc
JOIN   core.fact_weather_observed AS ob
       ON ob.location_key = fc.location_key AND ob.weather_date = fc.target_date
GROUP  BY fc.lead_days;

-- One row per location per month.
CREATE VIEW reporting.v_site_monthly_summary AS
WITH monthly AS (
    SELECT f.location_key,
           date_trunc('month', f.weather_date)::date       AS month_start,
           count(*)                                        AS days_recorded,
           round(avg(f.temp_max_c), 1)                     AS avg_temp_max_c,
           max(f.temp_max_c)                               AS hottest_day_c,
           min(f.temp_min_c)                               AS coldest_night_c,
           sum(f.precipitation_mm)                         AS total_rain_mm,
           count(*) FILTER (WHERE f.precipitation_mm >= 1) AS rain_days,
           max(f.wind_gust_max_kmh)                        AS strongest_gust_kmh
    FROM   core.fact_weather_observed AS f
    GROUP  BY f.location_key, date_trunc('month', f.weather_date)
),
high_risk AS (
    -- a day that breaks several High rules still counts as one high-risk day
    SELECT location_code,
           date_trunc('month', weather_date)::date AS month_start,
           count(DISTINCT weather_date)            AS high_risk_days
    FROM   reporting.v_observed_risk
    WHERE  severity = 'High'
    GROUP  BY location_code, date_trunc('month', weather_date)
)
SELECT l.location_code,
       l.location_name,
       l.location_type,
       m.month_start,
       m.days_recorded,
       m.avg_temp_max_c,
       m.hottest_day_c,
       m.coldest_night_c,
       m.total_rain_mm,
       m.rain_days,
       m.strongest_gust_kmh,
       coalesce(h.high_risk_days, 0) AS high_risk_days
FROM   monthly           AS m
JOIN   core.dim_location AS l USING (location_key)
LEFT   JOIN high_risk    AS h ON h.location_code = l.location_code AND h.month_start = m.month_start;

-- Is the pipeline healthy? One row, meant for a dashboard tile or a morning glance.
CREATE VIEW reporting.v_pipeline_health AS
SELECT (SELECT max(weather_date) FROM core.fact_weather_observed)                  AS latest_observed_date,
       (SELECT max(issue_date)   FROM core.fact_weather_forecast)                  AS latest_forecast_issue_date,
       (SELECT count(*) FROM core.dim_location WHERE is_active)                    AS active_locations,
       (SELECT count(*) FROM core.fact_weather_observed)                           AS observed_rows,
       (SELECT count(*) FROM core.fact_weather_forecast)                           AS forecast_rows,
       (SELECT max(logged_at) FROM audit.pipeline_step WHERE status = 'success')   AS last_successful_step_at,
       (SELECT count(*) FROM audit.pipeline_step
         WHERE status = 'failed' AND logged_at > now() - interval '7 days')        AS failed_steps_last_7_days,
       (SELECT count(*) FROM audit.data_quality_result
         WHERE NOT passed AND checked_at > now() - interval '7 days')              AS failed_checks_last_7_days;
