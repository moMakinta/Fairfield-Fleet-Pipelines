/* 04 - Fill the date dimension, one row per day.
   Can be re-run, it only inserts dates that are missing.
   TODO: date range is hard-coded below */
USE FairfieldLogistics;
GO

DECLARE @StartDate date = '2024-01-01',
        @EndDate   date = '2026-12-31';

WITH Numbers AS (
    SELECT TOP (DATEDIFF(DAY, @StartDate, @EndDate) + 1)
           ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS n
    FROM sys.all_objects AS a
    CROSS JOIN sys.all_objects AS b
),
Dates AS (
    SELECT DATEADD(DAY, n, @StartDate) AS d FROM Numbers
)
INSERT INTO core.DimDate (DateKey, FullDate, DayName, MonthNumber, MonthName,
                          CalendarQuarter, CalendarYear, IsWeekend)
SELECT YEAR(d) * 10000 + MONTH(d) * 100 + DAY(d),
       d,
       DATENAME(WEEKDAY, d),
       MONTH(d),
       DATENAME(MONTH, d),
       DATEPART(QUARTER, d),
       YEAR(d),
       -- 1900-01-01 was a Monday, so this gives 0 = Mon ... 5 = Sat, 6 = Sun
       CASE WHEN DATEDIFF(DAY, '19000101', d) % 7 >= 5 THEN 1 ELSE 0 END
FROM Dates
WHERE NOT EXISTS (SELECT 1 FROM core.DimDate AS x WHERE x.FullDate = Dates.d);
GO
