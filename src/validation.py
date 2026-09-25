"""
Data Validation and Quality Assurance Module (Class 6 Requirement).
Profiles records, evaluates explicit business validation rules, isolates anomalies into
a quarantined dataset with explicit failure reasons, and generates an auditable DQ summary.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple
import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    VALIDATION_RULES,
    QUARANTINE_DATA_DIR,
    OUTPUTS_DIR,
    DEFAULT_YEAR_MONTH
)

logger = logging.getLogger(__name__)


class DataValidator:
    """
    Executes declarative, business-oriented validation rules on NYC TLC trip data.
    Instead of silently discarding records, anomalies are tagged with specific violation codes
    and routed to a dedicated quarantine store.
    """

    def __init__(self, rules: Dict[str, Any] = None):
        self.rules = rules or VALIDATION_RULES

    def run_validation(
        self,
        con: duckdb.DuckDBPyConnection,
        target_month: str = DEFAULT_YEAR_MONTH
    ) -> Tuple[duckdb.DuckDBPyConnection, Dict[str, Any]]:
        """
        Validates raw_trips in DuckDB, tagging each record with quarantine flags.
        Creates clean_trips and quarantined_trips views.
        """
        logger.info(f"Initiating data validation for period: {target_month}...")

        # Parse target year and month boundaries
        year, month = target_month.split("-")
        next_month = f"{year}-02-01" if month == "01" else f"{year}-{int(month)+1:02d}-01"
        start_date = f"{target_month}-01 00:00:00"
        end_date = f"{next_month} 00:00:00"

        min_dur = self.rules["min_duration_seconds"]
        max_dur = self.rules["max_duration_seconds"]
        min_dist = self.rules["min_distance_miles"]
        max_dist = self.rules["max_distance_miles"]
        max_speed = self.rules["max_implausible_speed_mph"]
        min_fare = self.rules["min_fare_amount"]
        max_total = self.rules["max_total_amount"]
        min_loc = self.rules["valid_min_location_id"]
        max_loc = self.rules["valid_max_location_id"]

        # Tag each record with violation reasons
        con.execute(f"""
        CREATE OR REPLACE TABLE trips_validated AS
        SELECT 
            t.*,
            epoch(t.tpep_dropoff_datetime) - epoch(t.tpep_pickup_datetime) AS duration_seconds,
            CASE 
                WHEN (epoch(t.tpep_dropoff_datetime) - epoch(t.tpep_pickup_datetime)) > 0 
                THEN (t.trip_distance / ((epoch(t.tpep_dropoff_datetime) - epoch(t.tpep_pickup_datetime)) / 3600.0))
                ELSE 0.0 
            END AS effective_speed_mph,
            -- Violation Indicators
            CASE WHEN t.tpep_pickup_datetime < '{start_date}' OR t.tpep_pickup_datetime >= '{end_date}' THEN 1 ELSE 0 END AS flag_out_of_period,
            CASE WHEN t.tpep_dropoff_datetime < t.tpep_pickup_datetime THEN 1 ELSE 0 END AS flag_negative_duration,
            CASE WHEN (epoch(t.tpep_dropoff_datetime) - epoch(t.tpep_pickup_datetime)) < {min_dur} THEN 1 ELSE 0 END AS flag_duration_too_short,
            CASE WHEN (epoch(t.tpep_dropoff_datetime) - epoch(t.tpep_pickup_datetime)) > {max_dur} THEN 1 ELSE 0 END AS flag_duration_too_long,
            CASE WHEN t.trip_distance < {min_dist} THEN 1 ELSE 0 END AS flag_zero_or_neg_distance,
            CASE WHEN t.trip_distance > {max_dist} THEN 1 ELSE 0 END AS flag_excessive_distance,
            CASE WHEN (epoch(t.tpep_dropoff_datetime) - epoch(t.tpep_pickup_datetime)) >= {min_dur} 
                      AND (t.trip_distance / ((epoch(t.tpep_dropoff_datetime) - epoch(t.tpep_pickup_datetime)) / 3600.0)) > {max_speed} 
                 THEN 1 ELSE 0 END AS flag_implausible_speed,
            CASE WHEN t.fare_amount < {min_fare} OR t.total_amount <= 0 THEN 1 ELSE 0 END AS flag_negative_or_zero_fare,
            CASE WHEN t.total_amount > {max_total} THEN 1 ELSE 0 END AS flag_excessive_fare,
            CASE WHEN t.PULocationID < {min_loc} OR t.PULocationID > {max_loc} 
                      OR t.DOLocationID < {min_loc} OR t.DOLocationID > {max_loc} THEN 1 ELSE 0 END AS flag_unknown_location
        FROM raw_trips t
        """)

        # Add composite quarantine check and failure reason string
        con.execute("""
        CREATE OR REPLACE TABLE trips_tagged AS
        SELECT 
            *,
            (flag_out_of_period + flag_negative_duration + flag_duration_too_short + 
             flag_duration_too_long + flag_zero_or_neg_distance + flag_excessive_distance + 
             flag_implausible_speed + flag_negative_or_zero_fare + flag_excessive_fare + 
             flag_unknown_location) AS total_violations,
            concat_ws('; ',
                CASE WHEN flag_out_of_period = 1 THEN 'OUT_OF_PERIOD' END,
                CASE WHEN flag_negative_duration = 1 THEN 'NEGATIVE_DURATION' END,
                CASE WHEN flag_duration_too_short = 1 THEN 'DURATION_UNDER_1MIN' END,
                CASE WHEN flag_duration_too_long = 1 THEN 'DURATION_OVER_24H' END,
                CASE WHEN flag_zero_or_neg_distance = 1 THEN 'DISTANCE_UNDER_MIN' END,
                CASE WHEN flag_excessive_distance = 1 THEN 'DISTANCE_OVER_150MI' END,
                CASE WHEN flag_implausible_speed = 1 THEN 'SPEED_OVER_85MPH' END,
                CASE WHEN flag_negative_or_zero_fare = 1 THEN 'NON_POSITIVE_FARE' END,
                CASE WHEN flag_excessive_fare = 1 THEN 'FARE_OVER_1500' END,
                CASE WHEN flag_unknown_location = 1 THEN 'UNKNOWN_OR_OUT_OF_BOUNDS_LOCATION' END
            ) AS quarantine_reasons
        FROM trips_validated
        """)

        # Create Clean and Quarantined Views
        con.execute("CREATE OR REPLACE VIEW clean_trips AS SELECT * FROM trips_tagged WHERE total_violations = 0")
        con.execute("CREATE OR REPLACE VIEW quarantined_trips AS SELECT * FROM trips_tagged WHERE total_violations > 0")

        # Compile Quality Audit Report
        audit_summary = self._compile_audit_report(con)
        logger.info(
            f"Validation Completed: Total={audit_summary['total_records']:,} | "
            f"Passed={audit_summary['clean_records']:,} ({audit_summary['clean_rate_pct']}%) | "
            f"Quarantined={audit_summary['quarantined_records']:,} ({audit_summary['quarantine_rate_pct']}%)"
        )

        return con, audit_summary

    def _compile_audit_report(self, con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
        """Calculates exact anomaly breakdowns and violation frequencies."""
        summary = con.execute("""
        SELECT 
            COUNT(*) as total_records,
            SUM(CASE WHEN total_violations = 0 THEN 1 ELSE 0 END) as clean_records,
            SUM(CASE WHEN total_violations > 0 THEN 1 ELSE 0 END) as quarantined_records,
            SUM(flag_out_of_period) as out_of_period,
            SUM(flag_negative_duration) as negative_duration,
            SUM(flag_duration_too_short) as duration_too_short,
            SUM(flag_duration_too_long) as duration_too_long,
            SUM(flag_zero_or_neg_distance) as zero_or_neg_distance,
            SUM(flag_excessive_distance) as excessive_distance,
            SUM(flag_implausible_speed) as implausible_speed,
            SUM(flag_negative_or_zero_fare) as non_positive_fare,
            SUM(flag_excessive_fare) as excessive_fare,
            SUM(flag_unknown_location) as unknown_location
        FROM trips_tagged
        """).fetchdf().to_dict(orient="records")[0]

        total = summary["total_records"]
        clean = summary["clean_records"]
        quarantine = summary["quarantined_records"]

        audit_report = {
            "total_records": int(total),
            "clean_records": int(clean),
            "clean_rate_pct": round((clean / total) * 100, 2),
            "quarantined_records": int(quarantine),
            "quarantine_rate_pct": round((quarantine / total) * 100, 2),
            "violations_by_rule": {
                "out_of_period": int(summary["out_of_period"]),
                "negative_duration": int(summary["negative_duration"]),
                "duration_under_1min": int(summary["duration_too_short"]),
                "duration_over_24h": int(summary["duration_too_long"]),
                "distance_under_0_05mi": int(summary["zero_or_neg_distance"]),
                "distance_over_150mi": int(summary["excessive_distance"]),
                "speed_over_85mph": int(summary["implausible_speed"]),
                "non_positive_fare_or_total": int(summary["non_positive_fare"]),
                "fare_over_1500": int(summary["excessive_fare"]),
                "unknown_or_unmapped_zone": int(summary["unknown_location"])
            },
            "fde_assumptions_and_policy": {
                "passenger_count_nulls": "Preserved in clean dataset for operational and revenue KPIs; excluded only for per-passenger metrics. Dropping 29.2% of nulls would severely bias trip volume.",
                "ratecode_id_nulls": "Mapped to 'Unassigned / Digital Dispatch' rather than dropping.",
                "quarantine_policy": "Records failing physical travel laws (speed > 85mph, negative fares, duration < 1m) are segregated to quarantine parquet with diagnostic tags for vendor SLA reviews."
            }
        }
        return audit_report

    def export_quarantine_and_audit(
        self,
        con: duckdb.DuckDBPyConnection,
        audit_report: Dict[str, Any],
        target_month: str = DEFAULT_YEAR_MONTH
    ) -> Tuple[Path, Path]:
        """Persists quarantined records and JSON audit report for governance auditability."""
        quarantine_file = QUARANTINE_DATA_DIR / f"quarantined_trips_{target_month.replace('-', '_')}.parquet"
        audit_file = OUTPUTS_DIR / f"validation_audit_report_{target_month.replace('-', '_')}.json"

        quarantine_str = str(quarantine_file).replace("\\", "/")
        con.execute(f"COPY (SELECT * FROM quarantined_trips) TO '{quarantine_str}' (FORMAT PARQUET)")
        logger.info(f"Quarantined {audit_report['quarantined_records']:,} anomalous records to {quarantine_file}")

        with open(audit_file, "w", encoding="utf-8") as f:
            json.dump(audit_report, f, indent=2)
        logger.info(f"Data quality audit report exported to {audit_file}")

        return quarantine_file, audit_file


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from src.retrieval import DataRetriever
    
    retriever = DataRetriever()
    zone_p, _ = retriever.retrieve_taxi_zones_via_api()
    trip_p, _ = retriever.retrieve_trips_parquet()
    con = retriever.load_into_duckdb(trip_p, zone_p)

    validator = DataValidator()
    con, report = validator.run_validation(con)
    q_file, a_file = validator.export_quarantine_and_audit(con, report)
    print("\nValidation Anomaly Breakdown:")
    for k, v in report["violations_by_rule"].items():
        print(f"  - {k}: {v:,}")
