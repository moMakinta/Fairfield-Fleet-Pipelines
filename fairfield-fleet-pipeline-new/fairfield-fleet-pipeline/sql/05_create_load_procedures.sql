/* 05 - Procs that load core from landing.
   Needs SQL Server 2016 SP1+ because of CREATE OR ALTER.
   Running them twice on the same landing data should not change anything. */
USE FairfieldLogistics;
GO

/* Locations, customers, products, routes, fleet and the rate card.
   Changes just overwrite the old values (no history kept). */
CREATE OR ALTER PROCEDURE core.usp_LoadDimensions
    @Rows int OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET @Rows = 0;

    -- the EXISTS / EXCEPT part checks if any column changed and it handles NULLs,
    -- which a normal <> comparison doesn't

    -- locations (first, because routes and assets point at them)
    UPDATE d
    SET    LocationName = s.LocationName, LocationType = s.LocationType, City = s.City,
           Latitude = s.Latitude, Longitude = s.Longitude
    FROM   core.DimLocation AS d
    JOIN   landing.Location AS s ON s.LocationCode = d.LocationCode
    WHERE  EXISTS (SELECT s.LocationName, s.LocationType, s.City, s.Latitude, s.Longitude
                   EXCEPT
                   SELECT d.LocationName, d.LocationType, d.City, d.Latitude, d.Longitude);
    SET @Rows += @@ROWCOUNT;

    INSERT INTO core.DimLocation (LocationCode, LocationName, LocationType, City, Latitude, Longitude)
    SELECT s.LocationCode, s.LocationName, s.LocationType, s.City, s.Latitude, s.Longitude
    FROM   landing.Location AS s
    WHERE  NOT EXISTS (SELECT 1 FROM core.DimLocation AS d WHERE d.LocationCode = s.LocationCode);
    SET @Rows += @@ROWCOUNT;

    -- customers
    UPDATE d
    SET    CustomerName = s.CustomerName, Industry = s.Industry, City = s.City, CreditTermsDays = s.CreditTermsDays
    FROM   core.DimCustomer AS d
    JOIN   landing.Customer AS s ON s.CustomerID = d.CustomerID
    WHERE  EXISTS (SELECT s.CustomerName, s.Industry, s.City, s.CreditTermsDays
                   EXCEPT
                   SELECT d.CustomerName, d.Industry, d.City, d.CreditTermsDays);
    SET @Rows += @@ROWCOUNT;

    INSERT INTO core.DimCustomer (CustomerID, CustomerName, Industry, City, CreditTermsDays)
    SELECT s.CustomerID, s.CustomerName, s.Industry, s.City, s.CreditTermsDays
    FROM   landing.Customer AS s
    WHERE  NOT EXISTS (SELECT 1 FROM core.DimCustomer AS d WHERE d.CustomerID = s.CustomerID);
    SET @Rows += @@ROWCOUNT;

    -- products
    UPDATE d
    SET    ProductName = s.ProductName, HazardClass = s.HazardClass, HazardSurchargePct = s.HazardSurchargePct
    FROM   core.DimProduct AS d
    JOIN   landing.Product AS s ON s.ProductCode = d.ProductCode
    WHERE  EXISTS (SELECT s.ProductName, s.HazardClass, s.HazardSurchargePct
                   EXCEPT
                   SELECT d.ProductName, d.HazardClass, d.HazardSurchargePct);
    SET @Rows += @@ROWCOUNT;

    INSERT INTO core.DimProduct (ProductCode, ProductName, HazardClass, HazardSurchargePct)
    SELECT s.ProductCode, s.ProductName, s.HazardClass, s.HazardSurchargePct
    FROM   landing.Product AS s
    WHERE  NOT EXISTS (SELECT 1 FROM core.DimProduct AS d WHERE d.ProductCode = s.ProductCode);
    SET @Rows += @@ROWCOUNT;

    -- routes
    UPDATE d
    SET    OriginLocationKey = o.LocationKey, DestinationLocationKey = de.LocationKey,
           Mode = s.Mode, DistanceKm = s.DistanceKm
    FROM   core.DimRoute    AS d
    JOIN   landing.Route    AS s  ON s.RouteID = d.RouteID
    JOIN   core.DimLocation AS o  ON o.LocationCode  = s.OriginCode
    JOIN   core.DimLocation AS de ON de.LocationCode = s.DestinationCode
    WHERE  EXISTS (SELECT o.LocationKey, de.LocationKey, s.Mode, s.DistanceKm
                   EXCEPT
                   SELECT d.OriginLocationKey, d.DestinationLocationKey, d.Mode, d.DistanceKm);
    SET @Rows += @@ROWCOUNT;

    INSERT INTO core.DimRoute (RouteID, OriginLocationKey, DestinationLocationKey, Mode, DistanceKm)
    SELECT s.RouteID, o.LocationKey, de.LocationKey, s.Mode, s.DistanceKm
    FROM   landing.Route    AS s
    JOIN   core.DimLocation AS o  ON o.LocationCode  = s.OriginCode
    JOIN   core.DimLocation AS de ON de.LocationCode = s.DestinationCode
    WHERE  NOT EXISTS (SELECT 1 FROM core.DimRoute AS d WHERE d.RouteID = s.RouteID);
    SET @Rows += @@ROWCOUNT;

    -- fleet
    UPDATE d
    SET    AssetType = s.AssetType, AssetName = s.AssetName, CapacityTonnes = s.CapacityTonnes,
           YearBuilt = s.YearBuilt, HomeLocationKey = h.LocationKey, AssetStatus = s.AssetStatus
    FROM   core.DimAsset    AS d
    JOIN   landing.Asset    AS s ON s.AssetID = d.AssetID
    JOIN   core.DimLocation AS h ON h.LocationCode = s.HomeLocationCode
    WHERE  EXISTS (SELECT s.AssetType, s.AssetName, s.CapacityTonnes, s.YearBuilt, h.LocationKey, s.AssetStatus
                   EXCEPT
                   SELECT d.AssetType, d.AssetName, d.CapacityTonnes, d.YearBuilt, d.HomeLocationKey, d.AssetStatus);
    SET @Rows += @@ROWCOUNT;

    INSERT INTO core.DimAsset (AssetID, AssetType, AssetName, CapacityTonnes, YearBuilt, HomeLocationKey, AssetStatus)
    SELECT s.AssetID, s.AssetType, s.AssetName, s.CapacityTonnes, s.YearBuilt, h.LocationKey, s.AssetStatus
    FROM   landing.Asset    AS s
    JOIN   core.DimLocation AS h ON h.LocationCode = s.HomeLocationCode
    WHERE  NOT EXISTS (SELECT 1 FROM core.DimAsset AS d WHERE d.AssetID = s.AssetID);
    SET @Rows += @@ROWCOUNT;

    -- rate card: only 3 rows, so just replace it
    -- TODO: rates should have a start date. at the moment a new rate re-prices every old order as well
    DELETE FROM core.RateCard;
    INSERT INTO core.RateCard (Mode, RatePerTonneKm, MinimumCharge, FuelPricePerLitre)
    SELECT Mode, RatePerTonneKm, MinimumCharge, FuelPricePerLitre
    FROM   landing.RateCard;
END;
GO

/* Sales orders, and what each one is worth.

   Freight  = Tonnes x route distance (km) x the rate per tonne-km for that mode
   but never less than the minimum charge for the mode.
   Revenue  = Freight + the hazard surcharge % of the product.
   A cancelled order has no revenue.                                            */
CREATE OR ALTER PROCEDURE core.usp_LoadOrders
    @Rows int OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET @Rows = 0;

    -- work the revenue out once, then use it for the update and the insert
    SELECT s.OrderID,
           CONVERT(int, CONVERT(char(8), s.OrderDate, 112)) AS OrderDateKey,
           c.CustomerKey, p.ProductKey, r.RouteKey,
           s.Tonnes, s.RequestedDeliveryDate, s.OrderStatus,
           CASE WHEN s.OrderStatus = 'Cancelled' THEN CAST(0 AS decimal(14,2))
                ELSE CAST(ROUND(f.Freight * (1 + p.HazardSurchargePct / 100.0), 2) AS decimal(14,2)) END AS Revenue
    INTO   #Orders
    FROM   landing.SalesOrder AS s
    JOIN   core.DimCustomer   AS c  ON c.CustomerID  = s.CustomerID
    JOIN   core.DimProduct    AS p  ON p.ProductCode = s.ProductCode
    JOIN   core.DimRoute      AS r  ON r.RouteID     = s.RouteID
    JOIN   core.RateCard      AS rc ON rc.Mode       = r.Mode
    CROSS APPLY (SELECT CASE WHEN s.Tonnes * r.DistanceKm * rc.RatePerTonneKm < rc.MinimumCharge
                             THEN rc.MinimumCharge
                             ELSE s.Tonnes * r.DistanceKm * rc.RatePerTonneKm END AS Freight) AS f;

    UPDATE f
    SET    CustomerKey = o.CustomerKey, ProductKey = o.ProductKey, RouteKey = o.RouteKey,
           Tonnes = o.Tonnes, RequestedDeliveryDate = o.RequestedDeliveryDate,
           OrderStatus = o.OrderStatus, Revenue = o.Revenue
    FROM   core.FactOrder AS f
    JOIN   #Orders        AS o ON o.OrderID = f.OrderID
    WHERE  EXISTS (SELECT o.CustomerKey, o.ProductKey, o.RouteKey, o.Tonnes, o.RequestedDeliveryDate, o.OrderStatus, o.Revenue
                   EXCEPT
                   SELECT f.CustomerKey, f.ProductKey, f.RouteKey, f.Tonnes, f.RequestedDeliveryDate, f.OrderStatus, f.Revenue);
    SET @Rows += @@ROWCOUNT;

    INSERT INTO core.FactOrder (OrderID, OrderDateKey, CustomerKey, ProductKey, RouteKey,
                                Tonnes, RequestedDeliveryDate, OrderStatus, Revenue)
    SELECT o.OrderID, o.OrderDateKey, o.CustomerKey, o.ProductKey, o.RouteKey,
           o.Tonnes, o.RequestedDeliveryDate, o.OrderStatus, o.Revenue
    FROM   #Orders AS o
    WHERE  NOT EXISTS (SELECT 1 FROM core.FactOrder AS f WHERE f.OrderID = o.OrderID);
    SET @Rows += @@ROWCOUNT;
END;
GO

/* Trips. Fuel cost = litres x the fuel price for that kind of asset.
   A trip that was still on the way last time gets updated when it arrives. */
CREATE OR ALTER PROCEDURE core.usp_LoadTrips
    @Rows int OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET @Rows = 0;

    SELECT s.TripID, o.OrderKey, a.AssetKey,
           CONVERT(int, CONVERT(char(8), s.DepartureDateTime, 112)) AS DepartureDateKey,
           s.DepartureDateTime, s.ArrivalDateTime,
           CAST(DATEDIFF(MINUTE, s.DepartureDateTime, s.ArrivalDateTime) / 60.0 AS decimal(8,1)) AS DurationHours,
           s.LoadedTonnes, s.DistanceKm, s.FuelLitres,
           CAST(ROUND(s.FuelLitres * rc.FuelPricePerLitre, 2) AS decimal(14,2)) AS FuelCost,
           s.TripStatus, s.DelayReason
    INTO   #Trips
    FROM   landing.Trip   AS s
    JOIN   core.FactOrder AS o  ON o.OrderID  = s.OrderID
    JOIN   core.DimRoute  AS r  ON r.RouteKey = o.RouteKey
    JOIN   core.RateCard  AS rc ON rc.Mode    = r.Mode
    JOIN   core.DimAsset  AS a  ON a.AssetID  = s.AssetID;

    UPDATE f
    SET    AssetKey = t.AssetKey, ArrivalDateTime = t.ArrivalDateTime, DurationHours = t.DurationHours,
           LoadedTonnes = t.LoadedTonnes, DistanceKm = t.DistanceKm, FuelLitres = t.FuelLitres,
           FuelCost = t.FuelCost, TripStatus = t.TripStatus, DelayReason = t.DelayReason
    FROM   core.FactTrip AS f
    JOIN   #Trips        AS t ON t.TripID = f.TripID
    WHERE  EXISTS (SELECT t.AssetKey, t.ArrivalDateTime, t.LoadedTonnes, t.DistanceKm, t.FuelLitres, t.FuelCost, t.TripStatus, t.DelayReason
                   EXCEPT
                   SELECT f.AssetKey, f.ArrivalDateTime, f.LoadedTonnes, f.DistanceKm, f.FuelLitres, f.FuelCost, f.TripStatus, f.DelayReason);
    SET @Rows += @@ROWCOUNT;

    INSERT INTO core.FactTrip (TripID, OrderKey, AssetKey, DepartureDateKey, DepartureDateTime, ArrivalDateTime,
                               DurationHours, LoadedTonnes, DistanceKm, FuelLitres, FuelCost, TripStatus, DelayReason)
    SELECT t.TripID, t.OrderKey, t.AssetKey, t.DepartureDateKey, t.DepartureDateTime, t.ArrivalDateTime,
           t.DurationHours, t.LoadedTonnes, t.DistanceKm, t.FuelLitres, t.FuelCost, t.TripStatus, t.DelayReason
    FROM   #Trips AS t
    WHERE  NOT EXISTS (SELECT 1 FROM core.FactTrip AS f WHERE f.TripID = t.TripID);
    SET @Rows += @@ROWCOUNT;
END;
GO

CREATE OR ALTER PROCEDURE core.usp_LoadMaintenance
    @Rows int OUTPUT
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO core.FactMaintenance (MaintenanceID, AssetKey, StartDateKey, StartDate, EndDate,
                                      DaysOutOfService, MaintenanceType, Cost)
    SELECT s.MaintenanceID, a.AssetKey,
           CONVERT(int, CONVERT(char(8), s.StartDate, 112)),
           s.StartDate, s.EndDate,
           DATEDIFF(DAY, s.StartDate, s.EndDate) + 1,     -- start and end day both count
           s.MaintenanceType, s.Cost
    FROM   landing.Maintenance AS s
    JOIN   core.DimAsset       AS a ON a.AssetID = s.AssetID
    WHERE  NOT EXISTS (SELECT 1 FROM core.FactMaintenance AS f WHERE f.MaintenanceID = s.MaintenanceID);
    SET @Rows = @@ROWCOUNT;
END;
GO

/* Daily truck telemetry from the Spark job. The Spark job recalculates every day
   each time it runs, so the days that are in landing are deleted and put back. */
CREATE OR ALTER PROCEDURE core.usp_LoadTelemetry
    @Rows int OUTPUT
AS
BEGIN
    SET NOCOUNT ON;

    DELETE f
    FROM   core.FactTelemetryDaily AS f
    JOIN   core.DimAsset           AS a ON a.AssetKey = f.AssetKey
    JOIN   landing.TelemetryDaily  AS s ON s.AssetID = a.AssetID
                                       AND CONVERT(int, CONVERT(char(8), s.PingDate, 112)) = f.DateKey;

    INSERT INTO core.FactTelemetryDaily (AssetKey, DateKey, Pings, MovingPings, AvgMovingSpeedKmh, MaxSpeedKmh,
                                         SpeedingPings, MaxTankTempC, TempAlertPings)
    SELECT a.AssetKey, CONVERT(int, CONVERT(char(8), s.PingDate, 112)),
           s.Pings, s.MovingPings, s.AvgMovingSpeedKmh, s.MaxSpeedKmh,
           s.SpeedingPings, s.MaxTankTempC, s.TempAlertPings
    FROM   landing.TelemetryDaily AS s
    JOIN   core.DimAsset          AS a ON a.AssetID = s.AssetID;
    SET @Rows = @@ROWCOUNT;
END;
GO

/* Main proc - runs all the steps in one transaction and logs the result. */
CREATE OR ALTER PROCEDURE core.usp_RunLoad
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @Start datetime2(0) = SYSDATETIME(), @Rows int;
    -- table variables are not rolled back, so the step results survive a failure
    DECLARE @Steps TABLE (StepNo int IDENTITY(1,1), StepName sysname, RowsAffected int);

    BEGIN TRY
        BEGIN TRANSACTION;

        EXEC core.usp_LoadDimensions @Rows = @Rows OUTPUT;
        INSERT INTO @Steps (StepName, RowsAffected) VALUES (N'core.usp_LoadDimensions', @Rows);

        EXEC core.usp_LoadOrders @Rows = @Rows OUTPUT;
        INSERT INTO @Steps (StepName, RowsAffected) VALUES (N'core.usp_LoadOrders', @Rows);

        EXEC core.usp_LoadTrips @Rows = @Rows OUTPUT;
        INSERT INTO @Steps (StepName, RowsAffected) VALUES (N'core.usp_LoadTrips', @Rows);

        EXEC core.usp_LoadMaintenance @Rows = @Rows OUTPUT;
        INSERT INTO @Steps (StepName, RowsAffected) VALUES (N'core.usp_LoadMaintenance', @Rows);

        EXEC core.usp_LoadTelemetry @Rows = @Rows OUTPUT;
        INSERT INTO @Steps (StepName, RowsAffected) VALUES (N'core.usp_LoadTelemetry', @Rows);

        COMMIT TRANSACTION;

        INSERT INTO audit.LoadLog (StepName, StartTime, EndTime, RowsAffected, LoadStatus)
        SELECT StepName, @Start, SYSDATETIME(), RowsAffected, 'Success'
        FROM   @Steps
        ORDER BY StepNo;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;

        INSERT INTO audit.LoadLog (StepName, StartTime, EndTime, RowsAffected, LoadStatus, ErrorMessage)
        VALUES (N'core.usp_RunLoad', @Start, SYSDATETIME(), 0, 'Failed', ERROR_MESSAGE());

        THROW;   -- so the C# program sees the error too
    END CATCH;
END;
GO
