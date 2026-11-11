using System.Globalization;
using System.Text.RegularExpressions;

namespace Fairfield.Etl;

/// <summary>Helpers for turning the text in the files into real values.</summary>
public static class Parse
{
    // the source systems don't agree on a date format
    private static readonly string[] DateFormats =
    {
        "yyyy-MM-dd HH:mm", "dd/MM/yyyy HH:mm", "yyyy-MM-dd", "dd/MM/yyyy",
        "dd-MMM-yyyy", "yyyy-MM-dd HH:mm:ss"
    };

    /// <summary>Returns null if the text is empty or not a date we recognise.</summary>
    public static DateTime? Date(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return null;
        if (DateTime.TryParseExact(text.Trim(), DateFormats, CultureInfo.InvariantCulture,
                                   DateTimeStyles.None, out var value))
            return value;

        // a real date cell in Excel is stored as a number: days since 1900, with the time as the fraction.
        // 20000 to 80000 covers the years 1954 to 2119, so a normal number is not mistaken for a date.
        if (double.TryParse(text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var serial)
            && serial > 20000 && serial < 80000)
        {
            var date = DateTime.FromOADate(serial);
            // the fraction is not exact (07:00 can come back as 06:59:59.999), so round to the nearest second
            long seconds = (date.Ticks + TimeSpan.TicksPerSecond / 2) / TimeSpan.TicksPerSecond;
            return new DateTime(seconds * TimeSpan.TicksPerSecond);
        }
        return null;
    }

    /// <summary>
    /// "R 1,250.00" -> 1250.00, "45.5 t" -> 45.5, "570 km" -> 570.
    /// Everything that is not a digit, a dot or a minus sign is thrown away first.
    /// </summary>
    public static decimal? Number(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return null;
        var cleaned = Regex.Replace(text, @"[^0-9.\-]", "");
        if (decimal.TryParse(cleaned, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint,
                             CultureInfo.InvariantCulture, out var value))
            return value;
        return null;
    }

    /// <summary>Ids and codes: trimmed and upper case, so " trk-004 " matches "TRK-004".</summary>
    public static string Code(string? text) => (text ?? "").Trim().ToUpperInvariant();

    public static string Text(string? text) => (text ?? "").Trim();

    /// <summary>"HIGHVELD AGRI" -> "Highveld Agri"</summary>
    public static string Title(string? text)
    {
        var trimmed = Text(text);
        if (trimmed == "") return "";
        return CultureInfo.InvariantCulture.TextInfo.ToTitleCase(trimmed.ToLowerInvariant());
    }

    /// <summary>"COMPLETED" / " completed" -> "Completed". Only the first letter is upper case.</summary>
    public static string Sentence(string? text)
    {
        var trimmed = Text(text).ToLowerInvariant();
        if (trimmed == "") return "";
        return char.ToUpperInvariant(trimmed[0]) + trimmed.Substring(1);
    }

    /// <summary>Shortcut so a missing column gives "" instead of an exception.</summary>
    public static string Get(this Dictionary<string, string> row, string column) =>
        row.GetValueOrDefault(column, "");
}
