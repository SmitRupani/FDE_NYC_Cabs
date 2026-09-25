"""
Unit tests for data transformation, dimensional models, and metrics calculations (Class 7).
"""

import pytest
import duckdb
import pandas as pd

from src.retrieval import DataRetriever
from src.validation import DataValidator
from src.transformation import DataTransformer
from src.metrics import MetricCalculator
from src.config import RAW_DATA_DIR


@pytest.fixture(scope="module")
def populated_con():
    retriever = DataRetriever(raw_dir=RAW_DATA_DIR)
    zone_p, _ = retriever.retrieve_taxi_zones_via_api()
    trip_p, _ = retriever.retrieve_trips_parquet()
    con = duckdb.connect()
    con = retriever.load_into_duckdb(trip_p, zone_p, con)

    validator = DataValidator()
    con, _ = validator.run_validation(con, target_month="2026-01")

    transformer = DataTransformer()
    con = transformer.build_dimensional_model(con)
    return con


def test_star_schema_tables(populated_con):
    tables = [r[0] for r in populated_con.execute("SHOW TABLES").fetchall()]
    assert "dim_zones" in tables
    assert "dim_vendors" in tables
    assert "dim_rate_codes" in tables
    assert "dim_payment_types" in tables
    assert "fct_trips" in tables

    # Verify fact table counts and key integrity
    fct_count = populated_con.execute("SELECT COUNT(*) FROM fct_trips").fetchone()[0]
    assert fct_count > 3_000_000

    # Ensure no nulls in critical derived metrics
    null_speeds = populated_con.execute("SELECT COUNT(*) FROM fct_trips WHERE effective_speed_mph IS NULL").fetchone()[0]
    assert null_speeds == 0


def test_metric_calculations(populated_con):
    calculator = MetricCalculator()
    metrics = calculator.calculate_all_metrics(populated_con, target_month="2026-01")

    assert "metric_1_congestion_speed" in metrics
    assert "metric_2_revenue_productivity" in metrics
    assert "metric_3_zone_flow_imbalance" in metrics
    assert "metric_4_airport_corridor" in metrics
    assert "metric_5_data_trust_vendor" in metrics
    assert "executive_summary_kpis" in metrics

    df_exec = metrics["executive_summary_kpis"]
    assert len(df_exec) == 1
    assert df_exec["clean_trip_volume"][0] > 3_000_000
    assert df_exec["total_passenger_expenditure_usd"][0] > 50_000_000
    assert df_exec["overall_median_speed_mph"][0] > 0
