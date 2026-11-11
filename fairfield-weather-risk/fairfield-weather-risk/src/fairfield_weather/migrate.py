"""Creates and upgrades the database, and loads the reference data.

Migrations are numbered SQL files in the migrations folder. Each one is run
exactly once, in order, and recorded in audit.schema_migration. To change the
database later, add a new file with the next number. Never edit a file that
has already been applied somewhere, because that database will not run it again.

The reference data (locations and risk rules) lives in CSV files in the seeds
folder and is upserted every time, so editing a CSV and re-running is enough.
"""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

from fairfield_weather.warehouse import transaction

log = logging.getLogger(__name__)


def project_root() -> Path:
    """Where the migrations and seeds folders are. FAIRFIELD_HOME wins, otherwise it is worked out from this file."""
    if os.environ.get("FAIRFIELD_HOME"):
        return Path(os.environ["FAIRFIELD_HOME"])
    return Path(__file__).resolve().parents[2]


def apply_migrations(conn, migrations_dir: Path | None = None) -> list[str]:
    """Run every migration that has not been run on this database yet. Returns the versions applied."""
    migrations_dir = migrations_dir or project_root() / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"no migration files in {migrations_dir}")

    with transaction(conn) as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS audit")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS audit.schema_migration ("
            " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        # two processes starting at the same moment must not both run the migrations
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('fairfield_weather_migrations'))")
        cur.execute("SELECT version FROM audit.schema_migration")
        done = {row[0] for row in cur.fetchall()}

        applied = []
        for path in files:
            version = path.stem
            if version in done:
                continue
            log.info("Applying migration %s", version)
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO audit.schema_migration (version) VALUES (%s)", (version,))
            applied.append(version)
    return applied


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def load_seeds(conn, seeds_dir: Path | None = None) -> dict[str, int]:
    """Upsert the locations and risk rules from the CSV files."""
    seeds_dir = seeds_dir or project_root() / "seeds"
    locations = _read_csv(seeds_dir / "locations.csv")
    rules = _read_csv(seeds_dir / "risk_rules.csv")

    with transaction(conn) as cur:
        for row in locations:
            cur.execute(
                """
                INSERT INTO core.dim_location
                    (location_code, location_name, location_type, city, latitude, longitude, is_active)
                VALUES (%(location_code)s, %(location_name)s, %(location_type)s, %(city)s,
                        %(latitude)s, %(longitude)s, %(is_active)s)
                ON CONFLICT (location_code) DO UPDATE
                   SET location_name = EXCLUDED.location_name, location_type = EXCLUDED.location_type,
                       city = EXCLUDED.city, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
                       is_active = EXCLUDED.is_active
                """,
                {**row, "is_active": row.get("is_active", "true").lower() in ("true", "1", "yes")})

        for row in rules:
            cur.execute(
                """
                INSERT INTO core.risk_rule
                    (rule_code, description, location_type, metric, comparison, threshold, severity)
                VALUES (%(rule_code)s, %(description)s, %(location_type)s, %(metric)s,
                        %(comparison)s, %(threshold)s, %(severity)s)
                ON CONFLICT (rule_code) DO UPDATE
                   SET description = EXCLUDED.description, location_type = EXCLUDED.location_type,
                       metric = EXCLUDED.metric, comparison = EXCLUDED.comparison,
                       threshold = EXCLUDED.threshold, severity = EXCLUDED.severity
                """,
                {**row, "location_type": row["location_type"] or None})

        # a rule that was deleted from the CSV should stop applying
        cur.execute("DELETE FROM core.risk_rule WHERE rule_code <> ALL(%s)", ([row["rule_code"] for row in rules],))
    return {"locations": len(locations), "risk_rules": len(rules)}


def setup_database(conn) -> None:
    applied = apply_migrations(conn)
    seeded = load_seeds(conn)
    log.info("Migrations applied: %s. Seeds: %s", applied or "none (already up to date)", seeded)
