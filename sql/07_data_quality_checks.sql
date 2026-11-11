/* 07 - Checks to run after a load.
   Everything should say PASS except the last one, see the README. */
USE FairfieldLogistics;
GO

WITH Checks AS (
    SELECT 'Landed orders missing from core' AS CheckName, COUNT(*) AS FailedRows
    FROM   landing.SalesOrder AS s
    WHERE  NOT EXISTS (SELECT 1 FROM core.FactOrder AS f WHERE f.OrderID = s.OrderID)
    UNION ALL
    SELECT 'Landed trips missing from core', COUNT(*)
    FROM   landing.Trip AS s
    WHERE  NOT EXISTS (SELECT 1 FROM core.FactTrip AS f WHERE f.TripID = s.TripID)
    UNION ALL
    SELECT 'Landed maintenance missing from core', COUNT(*)
    FROM   landing.Maintenance AS s
    WHERE  NOT EXISTS (SELECT 1 FROM core.FactMaintenance AS f WHERE f.MaintenanceID = s.MaintenanceID)
    UNION ALL
    SELECT 'Cancelled orders with revenue', COUNT(*)
    FROM   core.FactOrder
    WHERE  OrderStatus = 'Cancelled' AND Revenue <> 0
    UNION ALL
    SELECT 'Live orders with zero or negative revenue', COUNT(*)
    FROM   core.FactOrder
    WHERE  OrderStatus <> 'Cancelled' AND Revenue <= 0
    UNION ALL
    SELECT 'Trips where the asset type does not match the route mode', COUNT(*)
    FROM   core.FactTrip  AS t
    JOIN   core.FactOrder AS o ON o.OrderKey = t.OrderKey
    JOIN   core.DimRoute  AS r ON r.RouteKey = o.RouteKey
    JOIN   core.DimAsset  AS a ON a.AssetKey = t.AssetKey
    WHERE  NOT ((r.Mode = 'Road' AND a.AssetType = 'Truck')
             OR (r.Mode = 'Rail' AND a.AssetType = 'Train')
             OR (r.Mode = 'Sea'  AND a.AssetType = 'Ship'))
    UNION ALL
    SELECT 'Trips loaded more than 5% over capacity', COUNT(*)
    FROM   core.FactTrip AS t
    JOIN   core.DimAsset AS a ON a.AssetKey = t.AssetKey
    WHERE  t.LoadedTonnes > a.CapacityTonnes * 1.05
    UNION ALL
    SELECT 'Trips that arrive before they leave', COUNT(*)
    FROM   core.FactTrip
    WHERE  ArrivalDateTime < DepartureDateTime
    UNION ALL
    -- the same truck / train / ship cannot be on two trips at once
    SELECT 'Assets on two trips at the same time', COUNT(*)
    FROM   core.FactTrip AS t1
    JOIN   core.FactTrip AS t2 ON t2.AssetKey = t1.AssetKey
                              AND t2.TripKey  > t1.TripKey
                              AND t1.DepartureDateTime < t2.ArrivalDateTime
                              AND t2.DepartureDateTime < t1.ArrivalDateTime
    UNION ALL
    SELECT 'Trips for a cancelled order', COUNT(*)
    FROM   core.FactTrip  AS t
    JOIN   core.FactOrder AS o ON o.OrderKey = t.OrderKey
    WHERE  o.OrderStatus = 'Cancelled'
    UNION ALL
    -- this one is expected to fail at the moment, see "Known issues" in the README
    SELECT 'Delivered orders where trips moved less than 95% of the tonnes', COUNT(*)
    FROM   reporting.vw_OrderSummary
    WHERE  OrderStatus = 'Delivered' AND TonnesMoved < Tonnes * 0.95
)
SELECT CheckName,
       FailedRows,
       CASE WHEN FailedRows = 0 THEN 'PASS' ELSE 'FAIL' END AS Result
FROM   Checks;
GO

-- totals to compare with the numbers in the README
SELECT (SELECT COUNT(*) FROM core.FactOrder)                AS Orders,
       (SELECT SUM(Revenue) FROM core.FactOrder)            AS Revenue,
       (SELECT COUNT(*) FROM core.FactTrip)                 AS Trips,
       (SELECT SUM(FuelCost) FROM core.FactTrip)            AS FuelCost,
       (SELECT SUM(Cost) FROM core.FactMaintenance)         AS MaintenanceCost,
       (SELECT COUNT(*) FROM core.FactTelemetryDaily)       AS TelemetryDays;

SELECT TOP (20) * FROM audit.LoadLog ORDER BY LoadLogID DESC;
GO
