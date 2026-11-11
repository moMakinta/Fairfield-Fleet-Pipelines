namespace Fairfield.Etl.Cleaning;

using Row = Dictionary<string, string>;

/// <summary>Cleaning for the files that change every day: sales orders, trips, maintenance, telemetry.</summary>
public static class Transactions
{
    private static readonly string[] OrderStatuses = { "Booked", "Delivered", "Cancelled" };

    public static CleanResult SalesOrders(List<Row> rows, HashSet<string> customers, HashSet<string> products, HashSet<string> routes)
    {
        var result = new CleanResult("SalesOrder",
            ("OrderID", typeof(string)), ("OrderDate", typeof(DateTime)), ("CustomerID", typeof(string)),
            ("ProductCode", typeof(string)), ("RouteID", typeof(string)), ("Tonnes", typeof(decimal)),
            ("RequestedDeliveryDate", typeof(DateTime)), ("OrderStatus", typeof(string)), ("SourceFile", typeof(string)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var id = Parse.Code(row.Get("OrderID"));
            var orderDate = Parse.Date(row.Get("OrderDate"));
            var customer = Parse.Code(row.Get("CustomerID"));
            var product = Parse.Code(row.Get("ProductCode"));
            var route = Parse.Code(row.Get("RouteID"));
            var tonnes = Parse.Number(row.Get("Tonnes"));
            var requested = Parse.Date(row.Get("RequestedDeliveryDate"));
            var status = Parse.Sentence(row.Get("OrderStatus"));

            if (id == "") { result.Reject(row, "Missing order id"); continue; }
            if (!seen.Add(id)) { result.Reject(row, "Duplicate order"); continue; }
            if (orderDate == null) { result.Reject(row, "Invalid or missing order date"); continue; }
            if (!customers.Contains(customer)) { result.Reject(row, "Unknown customer"); continue; }
            if (!products.Contains(product)) { result.Reject(row, "Unknown product"); continue; }
            if (!routes.Contains(route)) { result.Reject(row, "Unknown route"); continue; }
            if (tonnes == null || tonnes <= 0) { result.Reject(row, "Tonnes must be more than zero"); continue; }
            if (requested == null) { result.Reject(row, "Invalid requested delivery date"); continue; }
            if (requested < orderDate) { result.Reject(row, "Requested delivery is before the order date"); continue; }
            if (!OrderStatuses.Contains(status)) { result.Reject(row, "Unknown order status"); continue; }

            result.Add(id, orderDate.Value.Date, customer, product, route, tonnes, requested.Value.Date, status, row.Get("SourceFile"));
        }
        return result;
    }

    /// <summary>
    /// Trips are checked against the orders, routes and fleet:
    /// the asset has to exist, be the right kind for the route, and be big enough for the load.
    /// </summary>
    public static CleanResult Trips(List<Row> rows, CleanResult orders, CleanResult routes, CleanResult assets)
    {
        var result = new CleanResult("Trip",
            ("TripID", typeof(string)), ("OrderID", typeof(string)), ("AssetID", typeof(string)),
            ("DepartureDateTime", typeof(DateTime)), ("ArrivalDateTime", typeof(DateTime)),
            ("LoadedTonnes", typeof(decimal)), ("DistanceKm", typeof(decimal)), ("FuelLitres", typeof(decimal)),
            ("TripStatus", typeof(string)), ("DelayReason", typeof(string)), ("SourceFile", typeof(string)));

        var orderRoute = orders.Lookup<string>("OrderID", "RouteID");
        var routeMode = routes.Lookup<string>("RouteID", "Mode");
        var routeKm = routes.Lookup<decimal>("RouteID", "DistanceKm");
        var assetType = assets.Lookup<string>("AssetID", "AssetType");
        var assetCapacity = assets.Lookup<decimal>("AssetID", "CapacityTonnes");
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var id = Parse.Code(row.Get("TripID"));
            var order = Parse.Code(row.Get("OrderID"));
            var asset = Parse.Code(row.Get("AssetID"));
            var departure = Parse.Date(row.Get("DepartureDateTime"));
            var arrivalText = Parse.Text(row.Get("ArrivalDateTime"));
            var arrival = Parse.Date(arrivalText);
            var tonnes = Parse.Number(row.Get("LoadedTonnes"));
            var km = Parse.Number(row.Get("DistanceKm"));
            var fuel = Parse.Number(row.Get("FuelLitres"));

            if (id == "") { result.Reject(row, "Missing trip id"); continue; }
            if (!seen.Add(id)) { result.Reject(row, "Duplicate trip"); continue; }
            if (!orderRoute.ContainsKey(order)) { result.Reject(row, "Order not found"); continue; }
            if (!assetType.ContainsKey(asset)) { result.Reject(row, "Unknown asset"); continue; }

            var route = orderRoute[order];
            if (assetType[asset] != ReferenceData.AssetTypeForMode[routeMode[route]])
            {
                result.Reject(row, "Asset type does not match the route (e.g. a truck on a sea route)");
                continue;
            }

            if (departure == null) { result.Reject(row, "Invalid or missing departure date"); continue; }
            // no arrival date is fine, the trip is still on the way
            if (arrivalText != "" && arrival == null) { result.Reject(row, "Invalid arrival date"); continue; }
            if (arrival != null && arrival < departure) { result.Reject(row, "Arrival before departure"); continue; }

            if (tonnes == null || tonnes <= 0) { result.Reject(row, "Loaded tonnes must be more than zero"); continue; }
            // 5% tolerance because weighbridge readings are never exact
            // TODO: not sure rejecting is right, an overloaded tanker is something the business would want to see
            if (tonnes > assetCapacity[asset] * 1.05m) { result.Reject(row, "Load is more than the asset can carry"); continue; }

            if (km == null) { km = routeKm[route]; result.CountFix("missing distance filled from the route"); }
            if (km <= 0) { result.Reject(row, "Invalid distance"); continue; }
            if (fuel != null && fuel < 0) { result.Reject(row, "Fuel cannot be negative"); continue; }

            var status = arrival == null ? "In transit" : "Completed";
            var delay = Parse.Text(row.Get("DelayReason"));

            result.Add(id, order, asset, departure, arrival, tonnes, km, fuel, status,
                       delay == "" ? null : delay, row.Get("SourceFile"));
        }
        return result;
    }

    public static CleanResult Maintenance(List<Row> rows, HashSet<string> assets)
    {
        var result = new CleanResult("Maintenance",
            ("MaintenanceID", typeof(string)), ("AssetID", typeof(string)), ("StartDate", typeof(DateTime)),
            ("EndDate", typeof(DateTime)), ("MaintenanceType", typeof(string)), ("Cost", typeof(decimal)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var id = Parse.Code(row.Get("MaintenanceID"));
            var asset = Parse.Code(row.Get("AssetID"));
            var start = Parse.Date(row.Get("StartDate"));
            var end = Parse.Date(row.Get("EndDate"));
            var cost = Parse.Number(row.Get("Cost"));

            if (id == "") { result.Reject(row, "Missing maintenance id"); continue; }
            if (!seen.Add(id)) { result.Reject(row, "Duplicate maintenance record"); continue; }
            if (!assets.Contains(asset)) { result.Reject(row, "Unknown asset"); continue; }
            if (start == null || end == null) { result.Reject(row, "Invalid start or end date"); continue; }
            if (end < start) { result.Reject(row, "End date before start date"); continue; }
            if (cost == null || cost < 0) { result.Reject(row, "Invalid cost"); continue; }

            result.Add(id, asset, start.Value.Date, end.Value.Date, Parse.Sentence(row.Get("MaintenanceType")), cost);
        }
        return result;
    }

    /// <summary>
    /// The daily telemetry file is the output of the Spark job, so it is already clean.
    /// This only converts the types and drops rows for trucks that are not in the fleet file.
    /// </summary>
    public static CleanResult TelemetryDaily(List<Row> rows, HashSet<string> assets)
    {
        var result = new CleanResult("TelemetryDaily",
            ("AssetID", typeof(string)), ("PingDate", typeof(DateTime)), ("Pings", typeof(int)),
            ("MovingPings", typeof(int)), ("AvgMovingSpeedKmh", typeof(decimal)), ("MaxSpeedKmh", typeof(decimal)),
            ("SpeedingPings", typeof(int)), ("MaxTankTempC", typeof(decimal)), ("TempAlertPings", typeof(int)));

        foreach (var row in rows)
        {
            var asset = Parse.Code(row.Get("AssetID"));
            var date = Parse.Date(row.Get("PingDate"));

            if (!assets.Contains(asset)) { result.Reject(row, "Unknown asset"); continue; }
            if (date == null) { result.Reject(row, "Invalid date"); continue; }

            result.Add(asset, date.Value.Date,
                       (int)(Parse.Number(row.Get("Pings")) ?? 0),
                       (int)(Parse.Number(row.Get("MovingPings")) ?? 0),
                       Parse.Number(row.Get("AvgMovingSpeedKmh")),
                       Parse.Number(row.Get("MaxSpeedKmh")),
                       (int)(Parse.Number(row.Get("SpeedingPings")) ?? 0),
                       Parse.Number(row.Get("MaxTankTempC")),
                       (int)(Parse.Number(row.Get("TempAlertPings")) ?? 0));
        }
        return result;
    }
}
