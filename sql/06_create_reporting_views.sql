/* 06 - Reporting views. Connect Excel or Power BI to these, not to the core tables. */
USE FairfieldLogistics;
GO

/* One row per order: what it earned, what the fuel cost, and whether it arrived on time. */
CREATE OR ALTER VIEW reporting.vw_OrderSummary
AS
WITH TripTotals AS (
    SELECT OrderKey,
           COUNT(*)             AS Trips,
           SUM(LoadedTonnes)    AS TonnesMoved,
           SUM(DistanceKm)      AS DistanceKm,
           SUM(FuelCost)        AS FuelCost,
           MAX(ArrivalDateTime) AS LastArrival
    FROM   core.FactTrip
    GROUP BY OrderKey
)
SELECT o.OrderID,
       d.FullDate                 AS OrderDate,
       d.CalendarYear,
       d.MonthNumber,
       d.MonthName,
       c.CustomerName,
       c.Industry,
       p.ProductName,
       p.HazardClass,
       r.RouteID,
       r.Mode,
       lo.LocationName            AS Origin,
       ld.LocationName            AS Destination,
       o.Tonnes,
       o.OrderStatus,
       o.Revenue,
       COALESCE(t.Trips, 0)       AS Trips,
       COALESCE(t.TonnesMoved, 0) AS TonnesMoved,
       COALESCE(t.FuelCost, 0)    AS FuelCost,
       o.Revenue - COALESCE(t.FuelCost, 0) AS MarginAfterFuel,
       o.RequestedDeliveryDate,
       CASE WHEN o.OrderStatus = 'Delivered' THEN CAST(t.LastArrival AS date) END AS DeliveredDate,
       CASE WHEN o.OrderStatus <> 'Delivered' OR t.LastArrival IS NULL THEN NULL
            WHEN CAST(t.LastArrival AS date) <= o.RequestedDeliveryDate THEN 'On time'
            ELSE 'Late' END       AS DeliveryResult
FROM   core.FactOrder   AS o
JOIN   core.DimDate     AS d  ON d.DateKey      = o.OrderDateKey
JOIN   core.DimCustomer AS c  ON c.CustomerKey  = o.CustomerKey
JOIN   core.DimProduct  AS p  ON p.ProductKey   = o.ProductKey
JOIN   core.DimRoute    AS r  ON r.RouteKey     = o.RouteKey
JOIN   core.DimLocation AS lo ON lo.LocationKey = r.OriginLocationKey
JOIN   core.DimLocation AS ld ON ld.LocationKey = r.DestinationLocationKey
LEFT JOIN TripTotals    AS t  ON t.OrderKey     = o.OrderKey;
GO

/* Sales per month per mode. */
CREATE OR ALTER VIEW reporting.vw_MonthlySales
AS
SELECT CalendarYear,
       MonthNumber,
       MonthName,
       Mode,
       COUNT(*)                                                 AS Orders,
       SUM(CASE WHEN OrderStatus = 'Cancelled' THEN 1 ELSE 0 END) AS CancelledOrders,
       SUM(CASE WHEN OrderStatus <> 'Cancelled' THEN Tonnes ELSE 0 END) AS Tonnes,
       SUM(Revenue)                                             AS Revenue,
       SUM(FuelCost)                                            AS FuelCost,
       SUM(MarginAfterFuel)                                     AS MarginAfterFuel
FROM   reporting.vw_OrderSummary
GROUP BY CalendarYear, MonthNumber, MonthName, Mode;
GO

CREATE OR ALTER VIEW reporting.vw_CustomerSales
AS
SELECT CustomerName,
       Industry,
       COUNT(*)     AS Orders,
       SUM(Tonnes)  AS Tonnes,
       SUM(Revenue) AS Revenue,
       RANK() OVER (ORDER BY SUM(Revenue) DESC) AS RevenueRank
FROM   reporting.vw_OrderSummary
WHERE  OrderStatus <> 'Cancelled'
GROUP BY CustomerName, Industry;
GO

/* How hard each truck, train and ship worked each month.
   NOTE: a month where an asset did no trips at all does not show up here,
   even if it was in maintenance that month. */
CREATE OR ALTER VIEW reporting.vw_AssetUtilisation
AS
WITH TripMonths AS (
    SELECT t.AssetKey, d.CalendarYear, d.MonthNumber, d.MonthName,
           COUNT(*)                                      AS Trips,
           SUM(t.DistanceKm)                             AS DistanceKm,
           SUM(t.LoadedTonnes)                           AS TonnesCarried,
           SUM(t.DurationHours)                          AS HoursInTransit,
           AVG(100.0 * t.LoadedTonnes / a.CapacityTonnes) AS AvgLoadFactorPct,
           SUM(t.FuelLitres)                             AS FuelLitres,
           SUM(t.FuelCost)                               AS FuelCost,
           -- only trips that have a fuel figure, otherwise the litres per 100 km comes out too low
           SUM(CASE WHEN t.FuelLitres IS NOT NULL THEN t.DistanceKm END) AS DistanceWithFuelKm
    FROM   core.FactTrip AS t
    JOIN   core.DimAsset AS a ON a.AssetKey = t.AssetKey
    JOIN   core.DimDate  AS d ON d.DateKey  = t.DepartureDateKey
    GROUP BY t.AssetKey, d.CalendarYear, d.MonthNumber, d.MonthName
),
MaintMonths AS (
    SELECT m.AssetKey, d.CalendarYear, d.MonthNumber,
           SUM(m.DaysOutOfService) AS MaintenanceDays,
           SUM(m.Cost)             AS MaintenanceCost
    FROM   core.FactMaintenance AS m
    JOIN   core.DimDate         AS d ON d.DateKey = m.StartDateKey
    GROUP BY m.AssetKey, d.CalendarYear, d.MonthNumber
)
SELECT a.AssetID,
       a.AssetType,
       a.AssetName,
       a.CapacityTonnes,
       t.CalendarYear,
       t.MonthNumber,
       t.MonthName,
       t.Trips,
       t.DistanceKm,
       t.TonnesCarried,
       t.HoursInTransit,
       CAST(t.AvgLoadFactorPct AS decimal(5,1))  AS AvgLoadFactorPct,
       t.FuelLitres,
       t.FuelCost,
       CAST(100.0 * t.FuelLitres / NULLIF(t.DistanceWithFuelKm, 0) AS decimal(10,1)) AS LitresPer100Km,
       COALESCE(m.MaintenanceDays, 0)            AS MaintenanceDays,
       COALESCE(m.MaintenanceCost, 0)            AS MaintenanceCost
FROM   TripMonths    AS t
JOIN   core.DimAsset AS a ON a.AssetKey = t.AssetKey
LEFT JOIN MaintMonths AS m ON m.AssetKey = t.AssetKey
                          AND m.CalendarYear = t.CalendarYear
                          AND m.MonthNumber  = t.MonthNumber;
GO

/* On-time delivery per mode per month (by the month the order was placed). */
CREATE OR ALTER VIEW reporting.vw_OnTimeDelivery
AS
SELECT CalendarYear,
       MonthNumber,
       MonthName,
       Mode,
       COUNT(*)                                                    AS DeliveredOrders,
       SUM(CASE WHEN DeliveryResult = 'Late' THEN 1 ELSE 0 END)    AS LateOrders,
       CAST(100.0 * SUM(CASE WHEN DeliveryResult = 'On time' THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS OnTimePct
FROM   reporting.vw_OrderSummary
WHERE  DeliveryResult IS NOT NULL
GROUP BY CalendarYear, MonthNumber, MonthName, Mode;
GO

/* Truck safety from the GPS data: speeding and tank temperature alerts per truck per month. */
CREATE OR ALTER VIEW reporting.vw_TruckSafety
AS
SELECT a.AssetID,
       a.AssetName,
       d.CalendarYear,
       d.MonthNumber,
       d.MonthName,
       COUNT(*)              AS DaysOnTheRoad,
       SUM(f.Pings)          AS Pings,
       MAX(f.MaxSpeedKmh)    AS MaxSpeedKmh,
       SUM(f.SpeedingPings)  AS SpeedingPings,
       CAST(100.0 * SUM(f.SpeedingPings) / NULLIF(SUM(f.MovingPings), 0) AS decimal(5,1)) AS SpeedingPct,
       MAX(f.MaxTankTempC)   AS MaxTankTempC,
       SUM(f.TempAlertPings) AS TempAlertPings
FROM   core.FactTelemetryDaily AS f
JOIN   core.DimAsset           AS a ON a.AssetKey = f.AssetKey
JOIN   core.DimDate            AS d ON d.DateKey  = f.DateKey
GROUP BY a.AssetID, a.AssetName, d.CalendarYear, d.MonthNumber, d.MonthName;
GO
