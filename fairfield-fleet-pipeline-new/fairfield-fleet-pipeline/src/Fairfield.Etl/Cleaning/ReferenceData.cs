namespace Fairfield.Etl.Cleaning;

using Row = Dictionary<string, string>;

/// <summary>Cleaning for the small lookup files: locations, routes, customers, products, fleet, rate card.</summary>
public static class ReferenceData
{
    public static readonly string[] Modes = { "Road", "Rail", "Sea" };
    public static readonly string[] AssetTypes = { "Truck", "Train", "Ship" };

    /// <summary>Which kind of asset can work which kind of route.</summary>
    public static readonly Dictionary<string, string> AssetTypeForMode = new()
    {
        ["Road"] = "Truck", ["Rail"] = "Train", ["Sea"] = "Ship"
    };

    public static CleanResult Locations(List<Row> rows)
    {
        var result = new CleanResult("Location",
            ("LocationCode", typeof(string)), ("LocationName", typeof(string)), ("LocationType", typeof(string)),
            ("City", typeof(string)), ("Latitude", typeof(decimal)), ("Longitude", typeof(decimal)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var code = Parse.Code(row.Get("LocationCode"));
            if (code == "") { result.Reject(row, "Missing location code"); continue; }
            if (!seen.Add(code)) { result.Reject(row, "Duplicate location"); continue; }

            result.Add(code, Parse.Text(row.Get("LocationName")), Parse.Title(row.Get("LocationType")),
                       Parse.Text(row.Get("City")), Parse.Number(row.Get("Latitude")), Parse.Number(row.Get("Longitude")));
        }
        return result;
    }

    public static CleanResult Routes(List<Row> rows, HashSet<string> locations)
    {
        var result = new CleanResult("Route",
            ("RouteID", typeof(string)), ("OriginCode", typeof(string)), ("DestinationCode", typeof(string)),
            ("Mode", typeof(string)), ("DistanceKm", typeof(decimal)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var id = Parse.Code(row.Get("RouteID"));
            var origin = Parse.Code(row.Get("OriginCode"));
            var destination = Parse.Code(row.Get("DestinationCode"));
            var mode = Parse.Title(row.Get("Mode"));
            var km = Parse.Number(row.Get("DistanceKm"));

            if (id == "") { result.Reject(row, "Missing route id"); continue; }
            if (!seen.Add(id)) { result.Reject(row, "Duplicate route"); continue; }
            if (!locations.Contains(origin) || !locations.Contains(destination)) { result.Reject(row, "Unknown origin or destination"); continue; }
            if (!Modes.Contains(mode)) { result.Reject(row, "Mode must be Road, Rail or Sea"); continue; }
            if (km == null || km <= 0) { result.Reject(row, "Invalid distance"); continue; }

            result.Add(id, origin, destination, mode, km);
        }
        return result;
    }

    public static CleanResult Customers(List<Row> rows)
    {
        var result = new CleanResult("Customer",
            ("CustomerID", typeof(string)), ("CustomerName", typeof(string)), ("Industry", typeof(string)),
            ("City", typeof(string)), ("CreditTermsDays", typeof(int)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var id = Parse.Code(row.Get("CustomerID"));
            if (id == "") { result.Reject(row, "Missing customer id"); continue; }
            if (!seen.Add(id)) { result.Reject(row, "Duplicate customer"); continue; }

            // no credit terms on file -> assume the standard 30 days
            var terms = Parse.Number(row.Get("CreditTermsDays"));
            if (terms == null) { terms = 30; result.CountFix("credit terms defaulted to 30 days"); }

            result.Add(id, Parse.Title(row.Get("CustomerName")), Parse.Text(row.Get("Industry")),
                       Parse.Text(row.Get("City")), (int)terms.Value);
        }
        return result;
    }

    public static CleanResult Products(List<Row> rows)
    {
        var result = new CleanResult("Product",
            ("ProductCode", typeof(string)), ("ProductName", typeof(string)), ("HazardClass", typeof(string)),
            ("HazardSurchargePct", typeof(decimal)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var code = Parse.Code(row.Get("ProductCode"));
            var surcharge = Parse.Number(row.Get("HazardSurchargePct")) ?? 0;

            if (code == "") { result.Reject(row, "Missing product code"); continue; }
            if (!seen.Add(code)) { result.Reject(row, "Duplicate product"); continue; }
            if (surcharge < 0 || surcharge > 100) { result.Reject(row, "Surcharge must be 0-100"); continue; }

            result.Add(code, Parse.Text(row.Get("ProductName")), Parse.Text(row.Get("HazardClass")), surcharge);
        }
        return result;
    }

    public static CleanResult Assets(List<Row> rows, HashSet<string> locations)
    {
        var result = new CleanResult("Asset",
            ("AssetID", typeof(string)), ("AssetType", typeof(string)), ("AssetName", typeof(string)),
            ("CapacityTonnes", typeof(decimal)), ("YearBuilt", typeof(int)), ("HomeLocationCode", typeof(string)),
            ("AssetStatus", typeof(string)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var id = Parse.Code(row.Get("AssetID"));
            var type = Parse.Title(row.Get("AssetType"));
            var capacity = Parse.Number(row.Get("CapacityTonnes"));
            var year = Parse.Number(row.Get("YearBuilt"));
            var home = Parse.Code(row.Get("HomeLocation"));

            if (id == "") { result.Reject(row, "Missing asset id"); continue; }
            if (!seen.Add(id)) { result.Reject(row, "Duplicate asset"); continue; }
            if (!AssetTypes.Contains(type)) { result.Reject(row, "Asset type must be Truck, Train or Ship"); continue; }
            if (capacity == null || capacity <= 0) { result.Reject(row, "Invalid capacity"); continue; }
            if (!locations.Contains(home)) { result.Reject(row, "Unknown home location"); continue; }

            result.Add(id, type, Parse.Text(row.Get("AssetName")), capacity,
                       year == null ? null : (int)year.Value, home, Parse.Sentence(row.Get("Status")));
        }
        return result;
    }

    public static CleanResult RateCard(List<Row> rows)
    {
        var result = new CleanResult("RateCard",
            ("Mode", typeof(string)), ("RatePerTonneKm", typeof(decimal)), ("MinimumCharge", typeof(decimal)),
            ("FuelPricePerLitre", typeof(decimal)));
        var seen = new HashSet<string>();

        foreach (var row in rows)
        {
            var mode = Parse.Title(row.Get("Mode"));
            var rate = Parse.Number(row.Get("RatePerTonneKm"));
            var minimum = Parse.Number(row.Get("MinimumCharge")) ?? 0;
            var fuel = Parse.Number(row.Get("FuelPricePerLitre"));

            if (!Modes.Contains(mode)) { result.Reject(row, "Mode must be Road, Rail or Sea"); continue; }
            if (!seen.Add(mode)) { result.Reject(row, "Duplicate mode"); continue; }
            if (rate == null || rate <= 0 || fuel == null || fuel <= 0) { result.Reject(row, "Invalid rate or fuel price"); continue; }

            result.Add(mode, rate, minimum, fuel);
        }
        return result;
    }
}
