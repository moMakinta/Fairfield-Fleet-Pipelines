using System.Data;
using Microsoft.Data.SqlClient;

namespace Fairfield.Etl;

/// <summary>Puts the cleaned tables into SQL Server and runs the stored procedure that builds the core tables.</summary>
public static class SqlLoader
{
    /// <summary>
    /// Empties each landing table and bulk copies the cleaned rows in.
    /// The DataTable name and column names have to match the landing table exactly.
    /// TODO: this is not in a transaction, so if it fails half way some landing tables are new and some are old.
    /// </summary>
    public static void LoadLanding(string connectionString, IEnumerable<DataTable> tables)
    {
        using var connection = new SqlConnection(connectionString);
        connection.Open();

        foreach (var table in tables)
        {
            using (var truncate = new SqlCommand($"TRUNCATE TABLE landing.[{table.TableName}]", connection))
                truncate.ExecuteNonQuery();

            using var bulk = new SqlBulkCopy(connection);
            bulk.DestinationTableName = $"landing.[{table.TableName}]";
            bulk.BulkCopyTimeout = 120;
            foreach (DataColumn column in table.Columns)
                bulk.ColumnMappings.Add(column.ColumnName, column.ColumnName);
            bulk.WriteToServer(table);

            Console.WriteLine($"  landing.{table.TableName,-16} {table.Rows.Count,7} rows");
        }
    }

    /// <summary>Runs core.usp_RunLoad and prints what it wrote to the load log.</summary>
    public static void RunCoreLoad(string connectionString)
    {
        using var connection = new SqlConnection(connectionString);
        connection.Open();

        using (var command = new SqlCommand("core.usp_RunLoad", connection))
        {
            command.CommandType = CommandType.StoredProcedure;
            command.CommandTimeout = 300;
            command.ExecuteNonQuery();
        }

        const string logQuery =
            "SELECT StepName, RowsAffected, LoadStatus FROM audit.LoadLog " +
            "WHERE StartTime = (SELECT MAX(StartTime) FROM audit.LoadLog) ORDER BY LoadLogID";
        using var log = new SqlCommand(logQuery, connection);
        using var reader = log.ExecuteReader();
        while (reader.Read())
            Console.WriteLine($"  {reader.GetString(0),-28} {reader.GetInt32(1),7} rows  {reader.GetString(2)}");
    }
}
