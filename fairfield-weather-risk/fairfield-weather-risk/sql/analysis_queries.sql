-- Example questions the warehouse can answer. PostgreSQL syntax.
-- Connect with psql, DBeaver or pgAdmin: localhost, port 5433, database fairfield_weather.

-- 1. Is the pipeline healthy? (one row)
SELECT * FROM reporting.v_pipeline_health;

-- 2. This week's plan: which sites are forecast to break a risk rule, most serious first?
SELECT target_date, location_name, location_type, severity, description, metric, value, threshold
FROM   reporting.v_forecast_risk
ORDER  BY CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, target_date, location_name;

-- 3. How many days was each port unable to load ships because of wind, per month?
SELECT location_name,
       date_trunc('month', weather_date)::date AS month_start,
       count(*)                                AS wind_hold_days
FROM   reporting.v_observed_risk
WHERE  rule_code = 'PORT_WIND_HOLD'
GROUP  BY location_name, date_trunc('month', weather_date)
ORDER  BY location_name, month_start;

-- 4. Which site is the riskiest overall? High-risk days per site, with rank.
SELECT location_code,
       location_name,
       sum(high_risk_days)                             AS high_risk_days,
       rank() OVER (ORDER BY sum(high_risk_days) DESC) AS risk_rank
FROM   reporting.v_site_monthly_summary
GROUP  BY location_code, location_name
ORDER  BY risk_rank;

-- 5. Longest run of consecutive rain days at each site (a "gaps and islands" query).
--    Days in the same unbroken run share the same value of (date - row number).
WITH rain AS (
    SELECT l.location_name,
           f.weather_date,
           f.weather_date - (row_number() OVER (PARTITION BY f.location_key ORDER BY f.weather_date))::int AS run_id
    FROM   core.fact_weather_observed AS f
    JOIN   core.dim_location          AS l USING (location_key)
    WHERE  f.precipitation_mm >= 1
),
runs AS (
    SELECT location_name, min(weather_date) AS first_day, max(weather_date) AS last_day, count(*) AS days
    FROM   rain
    GROUP  BY location_name, run_id
)
SELECT DISTINCT ON (location_name) location_name, first_day, last_day, days
FROM   runs
ORDER  BY location_name, days DESC, first_day;

-- 6. How good are the forecasts, by how many days ahead they were made?
--    (Fills up over time: a forecast can only be scored once its day has been observed.)
SELECT * FROM reporting.v_forecast_accuracy ORDER BY lead_days;

-- 7. Did yesterday's forecast warn us? Forecast risk flags against what actually happened.
SELECT fc.target_date,
       l.location_name,
       fc.wind_gust_max_kmh AS forecast_gust,
       ob.wind_gust_max_kmh AS observed_gust,
       fc.wind_gust_max_kmh >= 60 AS hold_was_forecast,
       ob.wind_gust_max_kmh >= 60 AS hold_happened
FROM   core.fact_weather_forecast AS fc
JOIN   core.fact_weather_observed AS ob ON ob.location_key = fc.location_key AND ob.weather_date = fc.target_date
JOIN   core.dim_location          AS l  ON l.location_key  = fc.location_key
WHERE  fc.lead_days = 1 AND l.location_type = 'Port'
  AND  (fc.wind_gust_max_kmh >= 60 OR ob.wind_gust_max_kmh >= 60)
ORDER  BY fc.target_date, l.location_name;

-- 8. Hottest and wettest month at each site.
SELECT DISTINCT ON (location_code)
       location_code, location_name, month_start AS hottest_month, avg_temp_max_c
FROM   reporting.v_site_monthly_summary
ORDER  BY location_code, avg_temp_max_c DESC;

-- 9. What did the pipeline do in the last week?
SELECT run_date, step, status, row_count, message, logged_at
FROM   audit.pipeline_step
WHERE  logged_at > now() - interval '7 days'
ORDER  BY step_id DESC;

-- 10. Peek at a raw API answer: pull values straight out of the stored JSON.
SELECT location_code,
       run_date,
       payload->'daily'->'time'->>0               AS first_day,
       payload->'daily'->'temperature_2m_max'->>0 AS first_day_temp_max,
       payload->'daily_units'->>'wind_gusts_10m_max' AS gust_unit,
       fetched_at
FROM   raw.weather_response
WHERE  dataset = 'observed'
ORDER  BY fetched_at DESC
LIMIT  5;
