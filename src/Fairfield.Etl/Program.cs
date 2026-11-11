using System.Data;
using System.Text.Json;
using Fairfield.Etl;
using Fairfield.Etl.Cleaning;

// Fairfield Chemical Transportation - ETL
//
//   dotnet run --project src/Fairfield.Etl                 full run (needs SQL Server)
//   dotnet run --project src/Fairfield.Etl -- --skip-load  cleaning only

bool skipLoad = args.Contains("--skip-load");

string root = FindProjectRoot();
string rawDir = Path.Combine(root, "data", "raw");
string cleanDir = Path.Combine(root, "data", "clean");
string rejectDir = Path.Combine(root, "data", "rejects");
string telemetryFile = Path.Combine(root, "data", "processed", "telemetry_daily.csv");

Console.WriteLine($"Project folder: {root}");
Console.WriteLine();

// ---- extract + transform
// reference data first, because the orders and trips get checked against it
var locations = ReferenceData.Locations(CsvFile.Read(Path.Combine(rawDir, "locations.csv")));
var routes = ReferenceData.Routes(CsvFile.Read(Path.Combine(rawDir, "routes.csv")), locations.Keys("LocationCode"));
var customers = ReferenceData.Customers(CsvFile.Read(Path.Combine(rawDir, "customers.csv")));
var products = ReferenceData.Products(CsvFile.Read(Path.Combine(rawDir, "products.csv")));
var assets = ReferenceData.Assets(CsvFile.Read(Path.Combine(rawDir, "assets.csv")), locations.Keys("LocationCode"));
var rateCard = ReferenceData.RateCard(CsvFile.Read(Path.Combine(rawDir, "rate_card.csv")));

var orders = Transactions.SalesOrders(CsvFile.ReadAll(rawDir, "sales_orders_*.csv"),
    customers.Keys("CustomerID"), products.Keys("ProductCode"), routes.Keys("RouteID"));
var trips = Transactions.Trips(CsvFile.ReadAll(rawDir, "trips_*.csv"), orders, routes, assets);
var maintenance = Transactions.Maintenance(CsvFile.Read(Path.Combine(rawDir, "maintenance.csv")), assets.Keys("AssetID"));

List<Dictionary<string, string>> telemetryRows = new();
if (File.Exists(telemetryFile))
    telemetryRows = CsvFile.Read(telemetryFile);
else
    Console.WriteLine("WARNING: data/processed/telemetry_daily.csv not found. Run spark/telemetry_daily.py first. Carrying on without telemetry.");
var telemetry = Transactions.TelemetryDaily(telemetryRows, assets.Keys("AssetID"));

// the order matters for the load: parents before children
var results = new List<CleanResult>
{
    locations, routes, customers, products, assets, rateCard, orders, trips, maintenance, telemetry
};

Console.WriteLine($"{"Source",-16} {"Kept",8} {"Rejected",9}");
foreach (var result in results)
{
    string name = result.Table.TableName;
    CsvFile.Write(Path.Combine(cleanDir, name + ".csv"), result.Table);
    CsvFile.Write(Path.Combine(rejectDir, name + "_rejects.csv"), result.Rejects);

    Console.WriteLine($"{name,-16} {result.Table.Rows.Count,8} {result.Rejects.Count,9}");
    foreach (var reason in result.Rejects.GroupBy(r => r["RejectReason"]).OrderByDescending(g => g.Count()))
        Console.WriteLine($"      {reason.Count(),5}  {reason.Key}");
    foreach (var fix in result.Fixes)
        Console.WriteLine($"      {fix.Value,5}  (fixed) {fix.Key}");
}
Console.WriteLine();

if (skipLoad)
{
    Console.WriteLine("--skip-load given. Cleaned files are in data/clean, rejects in data/rejects.");
    return 0;
}

// ---- load
string? connectionString = ReadConnectionString(root);
if (connectionString == null)
{
    Console.WriteLine("ERROR: appsettings.json not found. Copy appsettings.example.json to appsettings.json and edit it.");
    return 1;
}

try
{
    Console.WriteLine("Loading landing tables...");
    SqlLoader.LoadLanding(connectionString, results.Select(r => r.Table));

    Console.WriteLine("Running core.usp_RunLoad...");
    SqlLoader.RunCoreLoad(connectionString);

    Console.WriteLine("Done.");
    return 0;
}
catch (Exception ex)
{
    // TODO: proper logging to a file instead of just the console
    Console.WriteLine("LOAD FAILED: " + ex.Message);
    return 1;
}


// Walks up from the current folder until it finds the one that has data/raw in it,
// so the program works whether it is started from the repo root or from the project folder.
static string FindProjectRoot()
{
    var folder = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (folder != null)
    {
        if (Directory.Exists(Path.Combine(folder.FullName, "data", "raw")))
            return folder.FullName;
        folder = folder.Parent;
    }
    throw new DirectoryNotFoundException("Could not find the data/raw folder. Run this from inside the project folder.");
}

static string? ReadConnectionString(string root)
{
    string path = Path.Combine(root, "appsettings.json");
    if (!File.Exists(path)) return null;

    using var json = JsonDocument.Parse(File.ReadAllText(path));
    return json.RootElement.GetProperty("ConnectionString").GetString();
}
