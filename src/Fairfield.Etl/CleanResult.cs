using System.Data;

namespace Fairfield.Etl;

/// <summary>
/// What comes out of cleaning one source: the good rows in a DataTable
/// (ready for SqlBulkCopy) and the rejected rows with a reason.
/// The DataTable name is the name of the landing table it gets loaded into.
/// </summary>
public class CleanResult
{
    public DataTable Table { get; }
    public List<Dictionary<string, string>> Rejects { get; } = new();

    /// <summary>Things that were fixed instead of rejected, for the log.</summary>
    public Dictionary<string, int> Fixes { get; } = new();

    public CleanResult(string landingTable, params (string Name, Type Type)[] columns)
    {
        Table = new DataTable(landingTable);
        foreach (var (name, type) in columns)
            Table.Columns.Add(name, type);
    }

    public void Add(params object?[] values)
    {
        Table.Rows.Add(values.Select(v => v ?? DBNull.Value).ToArray());
    }

    public void Reject(Dictionary<string, string> row, string reason)
    {
        var copy = new Dictionary<string, string>(row);
        copy["RejectReason"] = reason;
        Rejects.Add(copy);
    }

    public void CountFix(string what)
    {
        Fixes[what] = Fixes.GetValueOrDefault(what, 0) + 1;
    }

    /// <summary>All the values in one column, used to check other files against this one.</summary>
    public HashSet<string> Keys(string column)
    {
        var keys = new HashSet<string>();
        foreach (DataRow row in Table.Rows)
            keys.Add((string)row[column]);
        return keys;
    }

    /// <summary>Lookup from a key column to another column, e.g. AssetID -> AssetType.</summary>
    public Dictionary<string, T> Lookup<T>(string keyColumn, string valueColumn)
    {
        var lookup = new Dictionary<string, T>();
        foreach (DataRow row in Table.Rows)
            lookup[(string)row[keyColumn]] = (T)row[valueColumn];
        return lookup;
    }
}
