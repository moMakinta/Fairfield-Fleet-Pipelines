using System.Data;
using System.Globalization;
using System.Text;

namespace Fairfield.Etl;

/// <summary>
/// Small CSV reader and writer.
/// Handles quoted values with commas in them, but NOT line breaks inside a quoted value.
/// TODO: swap this for the CsvHelper package.
/// </summary>
public static class CsvFile
{
    /// <summary>Reads a file into a list of rows, each row is column name -> text value.</summary>
    public static List<Dictionary<string, string>> Read(string path)
    {
        var rows = new List<Dictionary<string, string>>();
        string[]? header = null;

        foreach (var line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var values = SplitLine(line);

            if (header == null)
            {
                header = values.Select(v => v.Trim().TrimStart('﻿')).ToArray();
                continue;
            }

            var row = new Dictionary<string, string>();
            for (int i = 0; i < header.Length; i++)
                row[header[i]] = i < values.Count ? values[i] : "";
            rows.Add(row);
        }
        return rows;
    }

    /// <summary>Reads every file that matches the pattern and adds a SourceFile column.</summary>
    public static List<Dictionary<string, string>> ReadAll(string folder, string pattern)
    {
        var rows = new List<Dictionary<string, string>>();
        foreach (var path in Directory.GetFiles(folder, pattern).OrderBy(p => p))
        {
            foreach (var row in Read(path))
            {
                row["SourceFile"] = Path.GetFileName(path);
                rows.Add(row);
            }
        }
        return rows;
    }

    public static void Write(string path, List<Dictionary<string, string>> rows)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        using var writer = new StreamWriter(path, false, new UTF8Encoding(false));
        if (rows.Count == 0) return;

        var header = rows[0].Keys.ToList();
        writer.WriteLine(string.Join(",", header.Select(Escape)));
        foreach (var row in rows)
            writer.WriteLine(string.Join(",", header.Select(h => Escape(row.GetValueOrDefault(h, "")))));
    }

    public static void Write(string path, DataTable table)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        using var writer = new StreamWriter(path, false, new UTF8Encoding(false));
        writer.WriteLine(string.Join(",", table.Columns.Cast<DataColumn>().Select(c => c.ColumnName)));
        foreach (DataRow row in table.Rows)
            writer.WriteLine(string.Join(",", row.ItemArray.Select(v => Escape(Format(v)))));
    }

    private static string Format(object? value) => value switch
    {
        null or DBNull => "",
        DateTime d => d.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture),
        decimal m => m.ToString(CultureInfo.InvariantCulture),
        _ => value.ToString() ?? ""
    };

    private static string Escape(string value)
    {
        if (value.Contains(',') || value.Contains('"'))
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        return value;
    }

    private static List<string> SplitLine(string line)
    {
        var values = new List<string>();
        var current = new StringBuilder();
        bool inQuotes = false;

        for (int i = 0; i < line.Length; i++)
        {
            char c = line[i];
            if (inQuotes)
            {
                if (c == '"' && i + 1 < line.Length && line[i + 1] == '"') { current.Append('"'); i++; }
                else if (c == '"') inQuotes = false;
                else current.Append(c);
            }
            else if (c == '"') inQuotes = true;
            else if (c == ',') { values.Add(current.ToString()); current.Clear(); }
            else current.Append(c);
        }
        values.Add(current.ToString());
        return values;
    }
}
