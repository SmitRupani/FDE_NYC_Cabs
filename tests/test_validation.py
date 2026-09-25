"""
Unit tests for data validation rules and quarantine routing (Class 6).
"""

import pytest
import duckdb
import pandas as pd
from src.validation import DataValidator


@pytest.fixture
def dirty_sample_duckdb():
    con = duckdb.connect()
    # Create synthetic dirty records covering each rule
    dirty_data = pd.DataFrame([
        {  # 1. Valid record
            "VendorID": 1,
            "tpep_pickup_datetime": pd.Timestamp("2026-01-15 10:00:00"),
            "tpep_dropoff_datetime": pd.Timestamp("2026-01-15 10:15:00"),
            "passenger_count": 1,
            "trip_distance": 2.5,
            "RatecodeID": 1,
            "store_and_fwd_flag": "N",
            "PULocationID": 100,
            "DOLocationID": 140,
            "payment_type": 1,
            "fare_amount": 15.0,
            "extra": 0.0,
            "mta_tax": 0.5,
            "tip_amount": 3.0,
            "tolls_amount": 0.0,
            "improvement_surcharge": 1.0,
            "total_amount": 19.5,
            "congestion_surcharge": 2.5,
            "Airport_fee": 0.0,
            "cbd_congestion_fee": 0.0
        },
        {  # 2. Anomaly: Dropoff before pickup (Time travel)
            "VendorID": 1,
            "tpep_pickup_datetime": pd.Timestamp("2026-01-15 10:15:00"),
            "tpep_dropoff_datetime": pd.Timestamp("2026-01-15 10:00:00"),
            "passenger_count": 1,
            "trip_distance": 2.0,
            "RatecodeID": 1,
            "store_and_fwd_flag": "N",
            "PULocationID": 100,
            "DOLocationID": 140,
            "payment_type": 1,
            "fare_amount": 12.0,
            "extra": 0.0,
            "mta_tax": 0.5,
            "tip_amount": 2.0,
            "tolls_amount": 0.0,
            "improvement_surcharge": 1.0,
            "total_amount": 15.5,
            "congestion_surcharge": 2.5,
            "Airport_fee": 0.0,
            "cbd_congestion_fee": 0.0
        },
        {  # 3. Anomaly: Negative fare / refund
            "VendorID": 2,
            "tpep_pickup_datetime": pd.Timestamp("2026-01-15 11:00:00"),
            "tpep_dropoff_datetime": pd.Timestamp("2026-01-15 11:20:00"),
            "passenger_count": 1,
            "trip_distance": 3.0,
            "RatecodeID": 1,
            "store_and_fwd_flag": "N",
            "PULocationID": 100,
            "DOLocationID": 140,
            "payment_type": 4,
            "fare_amount": -15.0,
            "extra": 0.0,
            "mta_tax": -0.5,
            "tip_amount": 0.0,
            "tolls_amount": 0.0,
            "improvement_surcharge": -1.0,
            "total_amount": -16.5,
            "congestion_surcharge": 0.0,
            "Airport_fee": 0.0,
            "cbd_congestion_fee": 0.0
        },
        {  # 4. Anomaly: Out of period (December 2025)
            "VendorID": 2,
            "tpep_pickup_datetime": pd.Timestamp("2025-12-31 23:50:00"),
            "tpep_dropoff_datetime": pd.Timestamp("2026-01-01 00:05:00"),
            "passenger_count": 1,
            "trip_distance": 1.5,
            "RatecodeID": 1,
            "store_and_fwd_flag": "N",
            "PULocationID": 100,
            "DOLocationID": 140,
            "payment_type": 1,
            "fare_amount": 10.0,
            "extra": 0.0,
            "mta_tax": 0.5,
            "tip_amount": 2.0,
            "tolls_amount": 0.0,
            "improvement_surcharge": 1.0,
            "total_amount": 13.5,
            "congestion_surcharge": 2.5,
            "Airport_fee": 0.0,
            "cbd_congestion_fee": 0.0
        },
        {  # 5. Anomaly: Zero distance with duration
            "VendorID": 1,
            "tpep_pickup_datetime": pd.Timestamp("2026-01-15 12:00:00"),
            "tpep_dropoff_datetime": pd.Timestamp("2026-01-15 12:10:00"),
            "passenger_count": 1,
            "trip_distance": 0.0,
            "RatecodeID": 1,
            "store_and_fwd_flag": "N",
            "PULocationID": 100,
            "DOLocationID": 140,
            "payment_type": 1,
            "fare_amount": 8.0,
            "extra": 0.0,
            "mta_tax": 0.5,
            "tip_amount": 0.0,
            "tolls_amount": 0.0,
            "improvement_surcharge": 1.0,
            "total_amount": 9.5,
            "congestion_surcharge": 0.0,
            "Airport_fee": 0.0,
            "cbd_congestion_fee": 0.0
        }
    ])
    con.register("raw_trips", dirty_data)
    return con


def test_validator_quarantine_routing(dirty_sample_duckdb):
    validator = DataValidator()
    con, audit = validator.run_validation(dirty_sample_duckdb, target_month="2026-01")

    assert audit["total_records"] == 5
    assert audit["clean_records"] == 1
    assert audit["quarantined_records"] == 4

    clean_count = con.execute("SELECT COUNT(*) FROM clean_trips").fetchone()[0]
    quarantine_count = con.execute("SELECT COUNT(*) FROM quarantined_trips").fetchone()[0]

    assert clean_count == 1
    assert quarantine_count == 4

    # Ensure quarantine reasons are correctly recorded
    reasons = con.execute("SELECT quarantine_reasons FROM quarantined_trips").fetchall()
    reasons_flat = " ".join([r[0] for r in reasons])
    assert "NEGATIVE_DURATION" in reasons_flat
    assert "NON_POSITIVE_FARE" in reasons_flat
    assert "OUT_OF_PERIOD" in reasons_flat
    assert "DISTANCE_UNDER_MIN" in reasons_flat
