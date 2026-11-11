using System.Globalization;
using System.IO.Compression;
using System.Xml.Linq;

namespace Fairfield.Etl;

/// <summary>
/// Reads the first sheet of an Excel .xlsx file into rows of column name -> text.
/// An .xlsx file is really a zip file with XML inside, so this opens the zip and reads the XML directly.
/// It only reads the cell values. Dates come through as Excel serial numbers (Parse.Date deals with that).
/// TODO: swap this for a library like ClosedXML. This only handles a simple sheet with a header row.
/// </summary>
public static class XlsxFile
{
    private static readonly XNamespace Ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";

    public static List<Dictionary<string, string>> Read(string path)
    {
        using var zip = ZipFile.OpenRead(path);

        // Excel keeps each different text value once in a shared list, and the cells point into it by number
        var sharedStrings = new List<string>();
        var sharedEntry = zip.GetEntry("xl/sharedStrings.xml");
        if (sharedEntry != null)
        {
            using var stream = sharedEntry.Open();
            foreach (var item in XDocument.Load(stream).Root!.Elements(Ns + "si"))
                sharedStrings.Add(string.Concat(item.Descendants(Ns + "t").Select(t => t.Value)));
        }

        // assumes the data is on the first sheet that was created in the workbook
        var sheetEntry = zip.GetEntry("xl/worksheets/sheet1.xml")
            ?? throw new InvalidDataException($"No sheet1 found in {path}");

        var rows = new List<Dictionary<string, string>>();
        List<string>? header = null;

        using (var stream = sheetEntry.Open())
        {
            var sheetData = XDocument.Load(stream).Root!.Element(Ns + "sheetData");
            if (sheetData == null) return rows;

            foreach (var rowElement in sheetData.Elements(Ns + "row"))
            {
                // empty cells are simply not in the file, so each value is stored under its column number
                var values = new Dictionary<int, string>();
                int next = 0;
                foreach (var cell in rowElement.Elements(Ns + "c"))
                {
                    var reference = (string?)cell.Attribute("r");
                    int column = reference == null ? next : ColumnIndex(reference);
                    values[column] = CellText(cell, sharedStrings);
                    next = column + 1;
                }
                if (values.Count == 0) continue;

                if (header == null)
                {
                    header = new List<string>();
                    for (int i = 0; i <= values.Keys.Max(); i++)
                        header.Add(values.GetValueOrDefault(i, "").Trim());
                    continue;
                }

                if (values.Values.All(string.IsNullOrWhiteSpace)) continue;

                var row = new Dictionary<string, string>();
                for (int i = 0; i < header.Count; i++)
                    if (header[i] != "") row[header[i]] = values.GetValueOrDefault(i, "");
                rows.Add(row);
            }
        }
        return rows;
    }

    /// <summary>Reads every file that matches the pattern and adds a SourceFile column.</summary>
    public static List<Dictionary<string, string>> ReadAll(string folder, string pattern)
    {
        var rows = new List<Dictionary<string, string>>();
        foreach (var path in Directory.GetFiles(folder, pattern).OrderBy(p => p))
        {
            // Excel makes a hidden "~$name.xlsx" lock file while a workbook is open
            if (Path.GetFileName(path).StartsWith("~$")) continue;

            foreach (var row in Read(path))
            {
                row["SourceFile"] = Path.GetFileName(path);
                rows.Add(row);
            }
        }
        return rows;
    }

    private static string CellText(XElement cell, List<string> sharedStrings)
    {
        var type = (string?)cell.Attribute("t");
        var value = cell.Element(Ns + "v")?.Value ?? "";

        if (type == "s") return sharedStrings[int.Parse(value)];
        if (type == "inlineStr") return string.Concat(cell.Descendants(Ns + "t").Select(t => t.Value));

        // numbers, dates (as serial numbers) and formula results.
        // Excel saves numbers with all 17 digits, so 80.9 is in the file as 80.900000000000006.
        // Reading it as a double and writing it back out gives the short version again.
        if (double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number))
            return number.ToString(CultureInfo.InvariantCulture);
        return value;
    }

    /// <summary>"A1" -> 0, "C7" -> 2, "AA3" -> 26</summary>
    private static int ColumnIndex(string cellReference)
    {
        int index = 0;
        foreach (char c in cellReference)
        {
            if (!char.IsLetter(c)) break;
            index = index * 26 + (char.ToUpperInvariant(c) - 'A' + 1);
        }
        return index - 1;
    }
}
