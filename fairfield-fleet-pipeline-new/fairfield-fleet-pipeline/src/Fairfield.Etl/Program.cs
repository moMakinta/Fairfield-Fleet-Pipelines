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
// the business files are Excel workbooks. the telemetry summary from Spark is still a CSV
// reference data first, because the orders and trips get checked against it
var locations = ReferenceData.Locations(XlsxFile.Read(Path.Combine(rawDir, "locations.xlsx")));
var routes = ReferenceData.Routes(XlsxFile.Read(Path.Combine(rawDir, "routes.xlsx")), locations.Keys("LocationCode"));
var customers = ReferenceData.Customers(XlsxFile.Read(Path.Combine(rawDir, "customers.xlsx")));
var products = ReferenceData.Products(XlsxFile.Read(Path.Combine(rawDir, "products.xlsx")));
var assets = ReferenceData.Assets(XlsxFile.Read(Path.Combine(rawDir, "assets.xlsx")), locations.Keys("LocationCode"));
var rateCard = ReferenceData.RateCard(XlsxFile.Read(Path.Combine(rawDir, "rate_card.xlsx")));

var orders = Transactions.SalesOrders(XlsxFile.ReadAll(rawDir, "sales_orders_*.xlsx"),
    customers.Keys("CustomerID"), products.Keys("ProductCode"), routes.Keys("RouteID"));
var trips = Transactions.Trips(XlsxFile.ReadAll(rawDir, "trips_*.xlsx"), orders, routes, assets);
var maintenance = Transactions.Maintenance(XlsxFile.Read(Path.Combine(rawDir, "maintenance.xlsx")), assets.Keys("AssetID"));

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
