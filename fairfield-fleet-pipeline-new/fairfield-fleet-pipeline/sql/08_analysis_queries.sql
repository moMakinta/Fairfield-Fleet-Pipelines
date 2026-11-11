/* 08 - Queries I used to look at the data once it was loaded. */
USE FairfieldLogistics;
GO

-- 1. Road vs rail vs sea: volume, revenue and what a tonne-km earns
SELECT r.Mode,
       COUNT(*)                                   AS Orders,
       SUM(o.Tonnes)                              AS Tonnes,
       SUM(o.Tonnes * r.DistanceKm)               AS TonneKm,
       SUM(o.Revenue)                             AS Revenue,
       CAST(SUM(o.Revenue) / NULLIF(SUM(o.Tonnes * r.DistanceKm), 0) AS decimal(10,3)) AS RevenuePerTonneKm
FROM   core.FactOrder AS o
JOIN   core.DimRoute  AS r ON r.RouteKey = o.RouteKey
WHERE  o.OrderStatus <> 'Cancelled'
GROUP BY r.Mode
ORDER BY Revenue DESC;

-- 2. Monthly revenue with month-on-month change and a running total
WITH Monthly AS (
    SELECT CalendarYear, MonthNumber, MonthName, SUM(Revenue) AS Revenue
    FROM   reporting.vw_MonthlySales
    GROUP BY CalendarYear, MonthNumber, MonthName
)
SELECT CalendarYear, MonthNumber, MonthName, Revenue,
       Revenue - LAG(Revenue) OVER (ORDER BY CalendarYear, MonthNumber) AS ChangeFromLastMonth,
       SUM(Revenue) OVER (PARTITION BY CalendarYear ORDER BY MonthNumber
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS YearToDate
FROM   Monthly
ORDER BY CalendarYear, MonthNumber;

-- 3. Top 10 customers
SELECT TOP (10) RevenueRank, CustomerName, Industry, Orders, Tonnes, Revenue
FROM   reporting.vw_CustomerSales
ORDER BY RevenueRank;

-- 4. Which routes make the most after fuel?
SELECT RouteID, Mode, Origin, Destination,
       COUNT(*)             AS Orders,
       SUM(Revenue)         AS Revenue,
       SUM(FuelCost)        AS FuelCost,
       SUM(MarginAfterFuel) AS MarginAfterFuel,
       CAST(100.0 * SUM(MarginAfterFuel) / NULLIF(SUM(Revenue), 0) AS decimal(5,1)) AS MarginPct
FROM   reporting.vw_OrderSummary
WHERE  OrderStatus = 'Delivered'
GROUP BY RouteID, Mode, Origin, Destination
ORDER BY MarginAfterFuel DESC;

-- 5. Fleet for the whole year: busiest and least used assets per type
WITH Yearly AS (
    SELECT AssetID, AssetType, AssetName,
           SUM(Trips) AS Trips, SUM(DistanceKm) AS DistanceKm, SUM(TonnesCarried) AS TonnesCarried,
           SUM(MaintenanceDays) AS MaintenanceDays, SUM(MaintenanceCost) AS MaintenanceCost
    FROM   reporting.vw_AssetUtilisation
    GROUP BY AssetID, AssetType, AssetName
)
SELECT *,
       RANK() OVER (PARTITION BY AssetType ORDER BY DistanceKm DESC) AS RankInType
FROM   Yearly
ORDER BY AssetType, RankInType;

-- 6. Assets in the fleet list that did no trips at all (retired, or just not used)
SELECT a.AssetID, a.AssetType, a.AssetName, a.AssetStatus
FROM   core.DimAsset AS a
WHERE  NOT EXISTS (SELECT 1 FROM core.FactTrip AS t WHERE t.AssetKey = a.AssetKey);

-- 7. What causes delays, and how much longer do delayed trips take?
SELECT r.Mode,
       COALESCE(t.DelayReason, '(no delay)')         AS DelayReason,
       COUNT(*)                                      AS Trips,
       CAST(AVG(t.DurationHours) AS decimal(8,1))    AS AvgHours
FROM   core.FactTrip  AS t
JOIN   core.FactOrder AS o ON o.OrderKey = t.OrderKey
JOIN   core.DimRoute  AS r ON r.RouteKey = o.RouteKey
WHERE  t.ArrivalDateTime IS NOT NULL
GROUP BY r.Mode, t.DelayReason
ORDER BY r.Mode, Trips DESC;

-- 8. On-time delivery per mode for the year
SELECT Mode,
       SUM(DeliveredOrders) AS DeliveredOrders,
       SUM(LateOrders)      AS LateOrders,
       CAST(100.0 * (SUM(DeliveredOrders) - SUM(LateOrders)) / SUM(DeliveredOrders) AS decimal(5,1)) AS OnTimePct
FROM   reporting.vw_OnTimeDelivery
GROUP BY Mode;

-- 9. Trucks with the most speeding (from the GPS data)
SELECT TOP (10) AssetID, AssetName,
       SUM(SpeedingPings)  AS SpeedingPings,
       MAX(MaxSpeedKmh)    AS MaxSpeedKmh,
       SUM(TempAlertPings) AS TempAlertPings
FROM   reporting.vw_TruckSafety
GROUP BY AssetID, AssetName
ORDER BY SpeedingPings DESC;

-- 10. Maintenance cost per asset type and type of work
SELECT a.AssetType, m.MaintenanceType,
       COUNT(*)                AS Jobs,
       SUM(m.DaysOutOfService) AS DaysOutOfService,
       SUM(m.Cost)             AS Cost
FROM   core.FactMaintenance AS m
JOIN   core.DimAsset        AS a ON a.AssetKey = m.AssetKey
GROUP BY a.AssetType, m.MaintenanceType
ORDER BY a.AssetType, Cost DESC;
GO
