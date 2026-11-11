/* 03 - Core tables (star schema) and the load log.
   Careful: this drops and recreates everything in core. */
USE FairfieldLogistics;
GO

DROP TABLE IF EXISTS core.FactTelemetryDaily;
DROP TABLE IF EXISTS core.FactMaintenance;
DROP TABLE IF EXISTS core.FactTrip;
DROP TABLE IF EXISTS core.FactOrder;
DROP TABLE IF EXISTS core.RateCard;
DROP TABLE IF EXISTS core.DimAsset;
DROP TABLE IF EXISTS core.DimRoute;
DROP TABLE IF EXISTS core.DimProduct;
DROP TABLE IF EXISTS core.DimCustomer;
DROP TABLE IF EXISTS core.DimLocation;
DROP TABLE IF EXISTS core.DimDate;
DROP TABLE IF EXISTS audit.LoadLog;
GO

CREATE TABLE core.DimDate (
    DateKey         int          NOT NULL CONSTRAINT PK_DimDate PRIMARY KEY,   -- yyyymmdd
    FullDate        date         NOT NULL CONSTRAINT UQ_DimDate_FullDate UNIQUE,
    DayName         nvarchar(10) NOT NULL,
    MonthNumber     tinyint      NOT NULL,
    MonthName       nvarchar(10) NOT NULL,
    CalendarQuarter tinyint      NOT NULL,
    CalendarYear    smallint     NOT NULL,
    IsWeekend       bit          NOT NULL
);

CREATE TABLE core.DimLocation (
    LocationKey  int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimLocation PRIMARY KEY,
    LocationCode varchar(10)   NOT NULL CONSTRAINT UQ_DimLocation UNIQUE,
    LocationName nvarchar(100) NULL,
    LocationType nvarchar(30)  NULL,       -- Depot, Plant or Port
    City         nvarchar(50)  NULL,
    Latitude     decimal(9,5)  NULL,
    Longitude    decimal(9,5)  NULL
);

CREATE TABLE core.DimCustomer (
    CustomerKey     int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimCustomer PRIMARY KEY,
    CustomerID      varchar(10)   NOT NULL CONSTRAINT UQ_DimCustomer UNIQUE,
    CustomerName    nvarchar(100) NULL,
    Industry        nvarchar(50)  NULL,
    City            nvarchar(50)  NULL,
    CreditTermsDays int           NOT NULL
);

CREATE TABLE core.DimProduct (
    ProductKey         int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimProduct PRIMARY KEY,
    ProductCode        varchar(10)   NOT NULL CONSTRAINT UQ_DimProduct UNIQUE,
    ProductName        nvarchar(100) NULL,
    HazardClass        varchar(10)   NULL,
    HazardSurchargePct decimal(5,2)  NOT NULL     -- added on top of the freight charge for dangerous goods
);

CREATE TABLE core.DimRoute (
    RouteKey               int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimRoute PRIMARY KEY,
    RouteID                varchar(10)   NOT NULL CONSTRAINT UQ_DimRoute UNIQUE,
    OriginLocationKey      int           NOT NULL CONSTRAINT FK_Route_Origin REFERENCES core.DimLocation (LocationKey),
    DestinationLocationKey int           NOT NULL CONSTRAINT FK_Route_Dest   REFERENCES core.DimLocation (LocationKey),
    Mode                   varchar(10)   NOT NULL,
    DistanceKm             decimal(10,1) NOT NULL
);

-- the fleet: trucks, trains and ships in one table
CREATE TABLE core.DimAsset (
    AssetKey         int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimAsset PRIMARY KEY,
    AssetID          varchar(10)   NOT NULL CONSTRAINT UQ_DimAsset UNIQUE,
    AssetType        varchar(10)   NOT NULL,
    AssetName        nvarchar(100) NULL,
    CapacityTonnes   decimal(10,1) NOT NULL,
    YearBuilt        int           NULL,
    HomeLocationKey  int           NOT NULL CONSTRAINT FK_Asset_Home REFERENCES core.DimLocation (LocationKey),
    AssetStatus      varchar(20)   NULL
);

-- prices per mode. not a dimension, just a lookup the load procs use
CREATE TABLE core.RateCard (
    Mode              varchar(10)   NOT NULL CONSTRAINT PK_RateCard PRIMARY KEY,
    RatePerTonneKm    decimal(10,4) NOT NULL,
    MinimumCharge     decimal(12,2) NOT NULL,
    FuelPricePerLitre decimal(10,2) NOT NULL
);

-- sales: one row per customer order
CREATE TABLE core.FactOrder (
    OrderKey              int IDENTITY(1,1) NOT NULL CONSTRAINT PK_FactOrder PRIMARY KEY,
    OrderID               varchar(12)   NOT NULL CONSTRAINT UQ_FactOrder UNIQUE,
    OrderDateKey          int           NOT NULL CONSTRAINT FK_Order_Date     REFERENCES core.DimDate (DateKey),
    CustomerKey           int           NOT NULL CONSTRAINT FK_Order_Customer REFERENCES core.DimCustomer (CustomerKey),
    ProductKey            int           NOT NULL CONSTRAINT FK_Order_Product  REFERENCES core.DimProduct (ProductKey),
    RouteKey              int           NOT NULL CONSTRAINT FK_Order_Route    REFERENCES core.DimRoute (RouteKey),
    Tonnes                decimal(10,1) NOT NULL,
    RequestedDeliveryDate date          NOT NULL,
    OrderStatus           varchar(20)   NOT NULL,
    Revenue               decimal(14,2) NOT NULL     -- worked out in core.usp_LoadOrders
);

-- operations: one row per trip. a big order can need several trips
CREATE TABLE core.FactTrip (
    TripKey           int IDENTITY(1,1) NOT NULL CONSTRAINT PK_FactTrip PRIMARY KEY,
    TripID            varchar(12)   NOT NULL CONSTRAINT UQ_FactTrip UNIQUE,
    OrderKey          int           NOT NULL CONSTRAINT FK_Trip_Order REFERENCES core.FactOrder (OrderKey),
    AssetKey          int           NOT NULL CONSTRAINT FK_Trip_Asset REFERENCES core.DimAsset (AssetKey),
    DepartureDateKey  int           NOT NULL CONSTRAINT FK_Trip_Date  REFERENCES core.DimDate (DateKey),
    DepartureDateTime datetime2(0)  NOT NULL,
    ArrivalDateTime   datetime2(0)  NULL,
    DurationHours     decimal(8,1)  NULL,
    LoadedTonnes      decimal(10,1) NOT NULL,
    DistanceKm        decimal(10,1) NOT NULL,
    FuelLitres        decimal(12,1) NULL,
    FuelCost          decimal(14,2) NULL,
    TripStatus        varchar(20)   NOT NULL,
    DelayReason       nvarchar(50)  NULL
);
CREATE INDEX IX_FactTrip_Order ON core.FactTrip (OrderKey);
CREATE INDEX IX_FactTrip_Asset ON core.FactTrip (AssetKey);

CREATE TABLE core.FactMaintenance (
    MaintenanceKey   int IDENTITY(1,1) NOT NULL CONSTRAINT PK_FactMaintenance PRIMARY KEY,
    MaintenanceID    varchar(12)   NOT NULL CONSTRAINT UQ_FactMaintenance UNIQUE,
    AssetKey         int           NOT NULL CONSTRAINT FK_Maint_Asset REFERENCES core.DimAsset (AssetKey),
    StartDateKey     int           NOT NULL CONSTRAINT FK_Maint_Date  REFERENCES core.DimDate (DateKey),
    StartDate        date          NOT NULL,
    EndDate          date          NOT NULL,
    DaysOutOfService int           NOT NULL,
    MaintenanceType  nvarchar(30)  NULL,
    Cost             decimal(12,2) NOT NULL
);

-- one row per truck per day, from the Spark job
CREATE TABLE core.FactTelemetryDaily (
    AssetKey          int          NOT NULL CONSTRAINT FK_Telemetry_Asset REFERENCES core.DimAsset (AssetKey),
    DateKey           int          NOT NULL CONSTRAINT FK_Telemetry_Date  REFERENCES core.DimDate (DateKey),
    Pings             int          NOT NULL,
    MovingPings       int          NOT NULL,
    AvgMovingSpeedKmh decimal(6,1) NULL,
    MaxSpeedKmh       decimal(6,1) NULL,
    SpeedingPings     int          NOT NULL,
    MaxTankTempC      decimal(6,1) NULL,
    TempAlertPings    int          NOT NULL,
    CONSTRAINT PK_FactTelemetryDaily PRIMARY KEY (AssetKey, DateKey)
);

CREATE TABLE audit.LoadLog (
    LoadLogID    int IDENTITY(1,1) NOT NULL CONSTRAINT PK_LoadLog PRIMARY KEY,
    StepName     sysname        NOT NULL,
    StartTime    datetime2(0)   NOT NULL,
    EndTime      datetime2(0)   NOT NULL,
    RowsAffected int            NOT NULL,
    LoadStatus   varchar(10)    NOT NULL,
    ErrorMessage nvarchar(4000) NULL
);
GO
