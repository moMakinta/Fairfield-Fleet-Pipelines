"""Spark job: turn the raw truck GPS pings into one row per truck per day.

The ping files are the only "big" data in the project (one row every 10 minutes
per truck), so this is the part that is done in Spark instead of C#.

    python spark/telemetry_daily.py

Output: data/processed/telemetry_daily.csv  (the C# pipeline picks this up)
"""
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "telemetry"
OUT = ROOT / "data" / "processed" / "telemetry_daily.csv"

SPEED_LIMIT_KMH = 80      # limit for a loaded hazardous goods tanker
MAX_REAL_SPEED = 130      # anything above this is a sensor glitch
TEMP_ALERT_C = 45         # TODO: should really be per product, not one number

spark = (SparkSession.builder
         .appName("fairfield-telemetry-daily")
         .master("local[*]")
         .config("spark.sql.session.timeZone", "UTC")
         .config("spark.sql.execution.arrow.pyspark.enabled", "false")   # so pyarrow is not needed
         .getOrCreate())
spark.sparkContext.setLogLevel("WARN")

raw = spark.read.option("header", True).csv(str(RAW))     # every file in the folder
raw_count = raw.count()

# try_cast / try_to_timestamp give NULL for junk instead of failing the whole job
pings = raw.select(
    F.upper(F.trim("asset_id")).alias("asset_id"),
    F.try_to_timestamp("ping_time", F.lit("yyyy-MM-dd HH:mm:ss")).alias("ping_time"),
    F.expr("try_cast(lat as double)").alias("lat"),
    F.expr("try_cast(lon as double)").alias("lon"),
    F.expr("try_cast(speed_kmh as double)").alias("speed_kmh"),
    F.expr("try_cast(tank_temp_c as double)").alias("tank_temp_c"),
)

clean = (pings
         .filter(F.col("ping_time").isNotNull())
         .filter(F.col("speed_kmh").isNotNull())
         .filter((F.col("speed_kmh") >= 0) & (F.col("speed_kmh") <= MAX_REAL_SPEED))
         .filter(~((F.col("lat") == 0) & (F.col("lon") == 0)))      # GPS lost signal
         .dropDuplicates(["asset_id", "ping_time"]))
clean_count = clean.count()

daily = (clean
         .groupBy("asset_id", F.to_date("ping_time").alias("ping_date"))
         .agg(F.count("*").alias("Pings"),
              F.sum(F.when(F.col("speed_kmh") > 5, 1).otherwise(0)).alias("MovingPings"),
              F.round(F.avg(F.when(F.col("speed_kmh") > 5, F.col("speed_kmh"))), 1).alias("AvgMovingSpeedKmh"),
              F.max("speed_kmh").alias("MaxSpeedKmh"),
              F.sum(F.when(F.col("speed_kmh") > SPEED_LIMIT_KMH, 1).otherwise(0)).alias("SpeedingPings"),
              F.max("tank_temp_c").alias("MaxTankTempC"),
              F.sum(F.when(F.col("tank_temp_c") > TEMP_ALERT_C, 1).otherwise(0)).alias("TempAlertPings"))
         .withColumnRenamed("asset_id", "AssetID")
         .withColumnRenamed("ping_date", "PingDate")
         .orderBy("AssetID", "PingDate"))

# The result is small (a few thousand rows) so it is collected to pandas and
# written as one normal CSV. Writing with Spark itself on Windows needs
# winutils.exe set up, and it writes a folder of part files, which is harder
# to pick up from C#.
OUT.parent.mkdir(parents=True, exist_ok=True)
result = daily.toPandas()
result.to_csv(OUT, index=False)

print(f"raw pings:      {raw_count}")
print(f"after cleaning: {clean_count}  ({raw_count - clean_count} dropped)")
print(f"daily rows:     {len(result)} -> {OUT}")
spark.stop()
