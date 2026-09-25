"""
Data Transformation and Relational Modeling Module (Class 7 Requirement).
Builds a Star Schema model with dimensions (zones, vendors, rate codes, payment types, time)
and an enriched fact table (fct_trips) ready for high-performance analytical queries.
"""

import sys
import logging
from pathlib import Path
from typing import Tuple
import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    PROCESSED_DATA_DIR,
    VENDOR_MAP,
    RATE_CODE_MAP,
    PAYMENT_TYPE_MAP,
    MANHATTAN_CBD_ZONE_IDS,
    AIRPORT_ZONE_IDS,
    DEFAULT_YEAR_MONTH
)

logger = logging.getLogger(__name__)


class DataTransformer:
    """
    Transforms validated clean trips into a normalized/star-schema analytical model.
    """

    def __init__(self, processed_dir: Path = PROCESSED_DATA_DIR):
        self.processed_dir = processed_dir
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def build_dimensional_model(
        self,
        con: duckdb.DuckDBPyConnection
    ) -> duckdb.DuckDBPyConnection:
        """
        Populates Dimension tables and enriched Fact table from clean_trips.
        """
        logger.info("Building dimensional model and star schema...")

        # 1. Dimension: Vendors
        vendor_tuples = ", ".join([f"({k}, '{v}')" for k, v in VENDOR_MAP.items()])
        con.execute(f"""
        CREATE OR REPLACE TABLE dim_vendors AS
        SELECT vendor_id, vendor_name
        FROM (VALUES {vendor_tuples}) AS t(vendor_id, vendor_name)
        """)

        # 2. Dimension: Rate Codes
        rate_tuples = ", ".join([f"({k}, '{v}')" for k, v in RATE_CODE_MAP.items()])
        con.execute(f"""
        CREATE OR REPLACE TABLE dim_rate_codes AS
        SELECT rate_code_id, rate_description
        FROM (VALUES {rate_tuples}) AS t(rate_code_id, rate_description)
        """)

        # 3. Dimension: Payment Types
        payment_tuples = ", ".join([f"({k}, '{v}')" for k, v in PAYMENT_TYPE_MAP.items()])
        con.execute(f"""
        CREATE OR REPLACE TABLE dim_payment_types AS
        SELECT 
            payment_type_id, 
            payment_description,
            CASE WHEN payment_type_id = 1 THEN TRUE ELSE FALSE END AS is_electronic_tip_recorded
        FROM (VALUES {payment_tuples}) AS t(payment_type_id, payment_description)
        """)

        # 4. Dimension: Taxi Zones (Enriched with Manhattan CBD & Airport designations)
        cbd_ids_str = ", ".join(map(str, MANHATTAN_CBD_ZONE_IDS))
        airport_ids_str = ", ".join(map(str, AIRPORT_ZONE_IDS.keys()))

        con.execute(f"""
        CREATE OR REPLACE TABLE dim_zones AS
        SELECT 
            CAST(LocationID AS INTEGER) AS location_id,
            Borough AS borough,
            Zone AS zone_name,
            service_zone,
            CASE WHEN LocationID IN ({cbd_ids_str}) THEN TRUE ELSE FALSE END AS is_manhattan_cbd,
            CASE WHEN LocationID IN ({airport_ids_str}) THEN TRUE ELSE FALSE END AS is_airport_zone
        FROM raw_zones
        WHERE LocationID BETWEEN 1 AND 263
        """)

        # 5. Enriched Fact Table: fct_trips
        logger.info("Materializing enriched fact table fct_trips...")
        con.execute(f"""
        CREATE OR REPLACE TABLE fct_trips AS
        SELECT 
            row_number() OVER () AS trip_id,
            t.VendorID AS vendor_id,
            COALESCE(t.RatecodeID, 99) AS rate_code_id,
            t.payment_type AS payment_type_id,
            t.PULocationID AS pickup_location_id,
            t.DOLocationID AS dropoff_location_id,
            t.tpep_pickup_datetime AS pickup_datetime,
            t.tpep_dropoff_datetime AS dropoff_datetime,
            EXTRACT(HOUR FROM t.tpep_pickup_datetime) AS pickup_hour,
            DAYNAME(t.tpep_pickup_datetime) AS pickup_day_name,
            EXTRACT(ISODOW FROM t.tpep_pickup_datetime) AS pickup_day_of_week,
            CASE 
                WHEN EXTRACT(ISODOW FROM t.tpep_pickup_datetime) IN (6, 7) THEN TRUE 
                ELSE FALSE 
            END AS is_weekend,
            CASE 
                WHEN EXTRACT(HOUR FROM t.tpep_pickup_datetime) BETWEEN 7 AND 9 THEN 'Morning Rush (07-10)'
                WHEN EXTRACT(HOUR FROM t.tpep_pickup_datetime) BETWEEN 10 AND 15 THEN 'Midday (10-16)'
                WHEN EXTRACT(HOUR FROM t.tpep_pickup_datetime) BETWEEN 16 AND 19 THEN 'Evening Rush (16-20)'
                ELSE 'Night / Off-Peak'
            END AS time_window,
            ROUND(t.duration_seconds / 60.0, 2) AS duration_minutes,
            ROUND(t.trip_distance, 2) AS trip_distance_miles,
            ROUND(t.effective_speed_mph, 2) AS effective_speed_mph,
            t.passenger_count,
            t.fare_amount,
            t.extra,
            t.mta_tax,
            t.tip_amount,
            t.tolls_amount,
            t.improvement_surcharge,
            COALESCE(t.congestion_surcharge, 0.0) AS congestion_surcharge,
            COALESCE(t.Airport_fee, 0.0) AS airport_fee,
            COALESCE(t.cbd_congestion_fee, 0.0) AS cbd_congestion_fee,
            t.total_amount,
            ROUND(t.total_amount / (t.duration_seconds / 60.0), 3) AS revenue_per_minute,
            CASE WHEN pz.borough = dz.borough THEN TRUE ELSE FALSE END AS is_intra_borough,
            CASE WHEN t.PULocationID IN ({airport_ids_str}) OR t.DOLocationID IN ({airport_ids_str}) THEN TRUE ELSE FALSE END AS is_airport_trip,
            CASE WHEN pz.is_manhattan_cbd OR dz.is_manhattan_cbd THEN TRUE ELSE FALSE END AS is_cbd_involved
        FROM clean_trips t
        LEFT JOIN dim_zones pz ON t.PULocationID = pz.location_id
        LEFT JOIN dim_zones dz ON t.DOLocationID = dz.location_id
        """)

        cnt_fct = con.execute("SELECT COUNT(*) FROM fct_trips").fetchone()[0]
        cnt_zones = con.execute("SELECT COUNT(*) FROM dim_zones").fetchone()[0]
        logger.info(f"Fact table created successfully with {cnt_fct:,} clean trips. Zones dimension: {cnt_zones} zones.")
        return con

    def export_processed_tables(
        self,
        con: duckdb.DuckDBPyConnection,
        target_month: str = DEFAULT_YEAR_MONTH
    ):
        """Exports dimensional tables to data/processed in Parquet format."""
        tables = ["dim_zones", "dim_vendors", "dim_rate_codes", "dim_payment_types", "fct_trips"]
        exported_paths = {}

        for table in tables:
            out_file = self.processed_dir / f"{table}.parquet"
            out_str = str(out_file).replace("\\", "/")
            con.execute(f"COPY {table} TO '{out_str}' (FORMAT PARQUET)")
            exported_paths[table] = out_file
            logger.info(f"Exported {table} to {out_file}")

        return exported_paths


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from src.retrieval import DataRetriever
    from src.validation import DataValidator

    retriever = DataRetriever()
    zone_p, _ = retriever.retrieve_taxi_zones_via_api()
    trip_p, _ = retriever.retrieve_trips_parquet()
    con = retriever.load_into_duckdb(trip_p, zone_p)

    validator = DataValidator()
    con, _ = validator.run_validation(con)

    transformer = DataTransformer()
    con = transformer.build_dimensional_model(con)
    transformer.export_processed_tables(con)
    print("\nDimensional Modeling Complete!")
