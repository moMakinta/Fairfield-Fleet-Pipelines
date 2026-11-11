/* 02 - Landing tables. The C# program truncates and bulk copies into these on every run.
   Table and column names have to match the DataTables in the C# code exactly. */
USE FairfieldLogistics;
GO

DROP TABLE IF EXISTS landing.TelemetryDaily;
DROP TABLE IF EXISTS landing.Maintenance;
DROP TABLE IF EXISTS landing.Trip;
DROP TABLE IF EXISTS landing.SalesOrder;
DROP TABLE IF EXISTS landing.RateCard;
DROP TABLE IF EXISTS landing.Asset;
DROP TABLE IF EXISTS landing.Product;
DROP TABLE IF EXISTS landing.Customer;
DROP TABLE IF EXISTS landing.Route;
DROP TABLE IF EXISTS landing.Location;
GO

CREATE TABLE landing.Location (
    LocationCode varchar(10)   NOT NULL,
    LocationName nvarchar(100) NULL,
    LocationType nvarchar(30)  NULL,
    City         nvarchar(50)  NULL,
    Latitude     decimal(9,5)  NULL,
    Longitude    decimal(9,5)  NULL
);

CREATE TABLE landing.Route (
    RouteID         varchar(10)   NOT NULL,
    OriginCode      varchar(10)   NOT NULL,
    DestinationCode varchar(10)   NOT NULL,
    Mode            varchar(10)   NOT NULL,      -- Road, Rail or Sea
    DistanceKm      decimal(10,1) NOT NULL
);

CREATE TABLE landing.Customer (
    CustomerID      varchar(10)   NOT NULL,
    CustomerName    nvarchar(100) NULL,
    Industry        nvarchar(50)  NULL,
    City            nvarchar(50)  NULL,
    CreditTermsDays int           NOT NULL
);

CREATE TABLE landing.Product (
    ProductCode        varchar(10)   NOT NULL,
    ProductName        nvarchar(100) NULL,
    HazardClass        varchar(10)   NULL,
    HazardSurchargePct decimal(5,2)  NOT NULL
);

CREATE TABLE landing.Asset (
    AssetID          varchar(10)   NOT NULL,
    AssetType        varchar(10)   NOT NULL,     -- Truck, Train or Ship
    AssetName        nvarchar(100) NULL,
    CapacityTonnes   decimal(10,1) NOT NULL,
    YearBuilt        int           NULL,
    HomeLocationCode varchar(10)   NOT NULL,
    AssetStatus      varchar(20)   NULL
);

CREATE TABLE landing.RateCard (
    Mode              varchar(10)   NOT NULL,
    RatePerTonneKm    decimal(10,4) NOT NULL,
    MinimumCharge     decimal(12,2) NOT NULL,
    FuelPricePerLitre decimal(10,2) NOT NULL
);

CREATE TABLE landing.SalesOrder (
    OrderID               varchar(12)   NOT NULL,
    OrderDate             date          NOT NULL,
    CustomerID            varchar(10)   NOT NULL,
    ProductCode           varchar(10)   NOT NULL,
    RouteID               varchar(10)   NOT NULL,
    Tonnes                decimal(10,1) NOT NULL,
    RequestedDeliveryDate date          NOT NULL,
    OrderStatus           varchar(20)   NOT NULL,   -- Booked, Delivered or Cancelled
    SourceFile            varchar(60)   NULL
);

CREATE TABLE landing.Trip (
    TripID            varchar(12)   NOT NULL,
    OrderID           varchar(12)   NOT NULL,
    AssetID           varchar(10)   NOT NULL,
    DepartureDateTime datetime2(0)  NOT NULL,
    ArrivalDateTime   datetime2(0)  NULL,          -- NULL = still on the way
    LoadedTonnes      decimal(10,1) NOT NULL,
    DistanceKm        decimal(10,1) NOT NULL,
    FuelLitres        decimal(12,1) NULL,
    TripStatus        varchar(20)   NOT NULL,
    DelayReason       nvarchar(50)  NULL,
    SourceFile        varchar(60)   NULL
);

CREATE TABLE landing.Maintenance (
    MaintenanceID   varchar(12)   NOT NULL,
    AssetID         varchar(10)   NOT NULL,
    StartDate       date          NOT NULL,
    EndDate         date          NOT NULL,
    MaintenanceType nvarchar(30)  NULL,
    Cost            decimal(12,2) NOT NULL
);

CREATE TABLE landing.TelemetryDaily (
    AssetID           varchar(10)  NOT NULL,
    PingDate          date         NOT NULL,
    Pings             int          NOT NULL,
    MovingPings       int          NOT NULL,
    AvgMovingSpeedKmh decimal(6,1) NULL,
    MaxSpeedKmh       decimal(6,1) NULL,
    SpeedingPings     int          NOT NULL,
    MaxTankTempC      decimal(6,1) NULL,
    TempAlertPings    int          NOT NULL
);
GO
