"""
Operational Metrics and KPI Calculation Module (Class 7 Requirement).
Calculates 5 dependable operational business metrics linked to urban transit,
driver earnings, fleet repositioning, airport operations, and data trust.
"""

import sys
import logging
from pathlib import Path
from typing import Dict, Any
import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import OUTPUTS_DIR, DEFAULT_YEAR_MONTH

logger = logging.getLogger(__name__)


class MetricCalculator:
    """
    Computes business-critical operational KPIs from the enriched star schema in DuckDB.
    """

    def __init__(self, outputs_dir: Path = OUTPUTS_DIR):
        self.outputs_dir = outputs_dir
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def calculate_all_metrics(
        self,
        con: duckdb.DuckDBPyConnection,
        target_month: str = DEFAULT_YEAR_MONTH
    ) -> Dict[str, pd.DataFrame]:
        """
        Executes analytical queries to compute the 5 core operational metrics.
        """
        logger.info("Computing 5 operational metrics from curated data model...")
        results = {}

        # ---------------------------------------------------------------------
        # Metric 1: Congestion & Transit Speed Index
        # ---------------------------------------------------------------------
        logger.info("Calculating Metric 1: Congestion & Effective Speed Index...")
        df_speed = con.execute("""
        SELECT 
            pz.borough AS pickup_borough,
            f.time_window,
            COUNT(*) AS trip_count,
            ROUND(AVG(f.duration_minutes), 1) AS avg_duration_min,
            ROUND(AVG(f.trip_distance_miles), 2) AS avg_distance_miles,
            ROUND(MEDIAN(f.effective_speed_mph), 2) AS median_speed_mph,
            ROUND(QUANTILE_CONT(f.effective_speed_mph, 0.10), 2) AS p10_speed_mph,
            ROUND(QUANTILE_CONT(f.effective_speed_mph, 0.90), 2) AS p90_speed_mph
        FROM fct_trips f
        JOIN dim_zones pz ON f.pickup_location_id = pz.location_id
        GROUP BY pz.borough, f.time_window
        ORDER BY pz.borough, 
            CASE f.time_window
                WHEN 'Morning Rush (07-10)' THEN 1
                WHEN 'Midday (10-16)' THEN 2
                WHEN 'Evening Rush (16-20)' THEN 3
                ELSE 4
            END
        """).fetchdf()
        results["metric_1_congestion_speed"] = df_speed

        # ---------------------------------------------------------------------
        # Metric 2: Driver Revenue Productivity ($/in-transit min)
        # ---------------------------------------------------------------------
        logger.info("Calculating Metric 2: Driver Revenue Productivity...")
        df_rev = con.execute("""
        SELECT 
            pz.borough AS pickup_borough,
            f.is_weekend,
            f.time_window,
            COUNT(*) AS trip_count,
            ROUND(SUM(f.total_amount), 2) AS total_gross_revenue,
            ROUND(AVG(f.total_amount), 2) AS avg_fare_per_trip,
            ROUND(AVG(f.revenue_per_minute), 2) AS avg_revenue_per_active_min,
            ROUND(MEDIAN(f.revenue_per_minute), 2) AS median_revenue_per_active_min,
            ROUND(AVG(f.tip_amount), 2) AS avg_tip_amount,
            ROUND(AVG(CASE WHEN f.payment_type_id = 1 AND f.fare_amount > 0 THEN (f.tip_amount / f.fare_amount) * 100 ELSE NULL END), 1) AS avg_cc_tip_pct
        FROM fct_trips f
        JOIN dim_zones pz ON f.pickup_location_id = pz.location_id
        GROUP BY pz.borough, f.is_weekend, f.time_window
        ORDER BY pz.borough, f.is_weekend, f.time_window
        """).fetchdf()
        results["metric_2_revenue_productivity"] = df_rev

        # ---------------------------------------------------------------------
        # Metric 3: Zone Flow Imbalance (Supply-Demand Displacement)
        # ---------------------------------------------------------------------
        logger.info("Calculating Metric 3: Zone Flow Imbalance & Staging Demand...")
        df_flow = con.execute("""
        WITH pu_trips AS (
            SELECT pickup_location_id AS loc_id, COUNT(*) AS pickups
            FROM fct_trips
            GROUP BY pickup_location_id
        ),
        droff_trips AS (
            SELECT dropoff_location_id AS loc_id, COUNT(*) AS dropoffs
            FROM fct_trips
            GROUP BY dropoff_location_id
        )
        SELECT 
            z.location_id,
            z.borough,
            z.zone_name,
            COALESCE(pu.pickups, 0) AS total_pickups,
            COALESCE(droff.dropoffs, 0) AS total_dropoffs,
            (COALESCE(pu.pickups, 0) - COALESCE(droff.dropoffs, 0)) AS net_passenger_flow,
            ROUND(CAST(COALESCE(pu.pickups, 0) AS DOUBLE) / NULLIF(COALESCE(droff.dropoffs, 0), 0), 3) AS flow_ratio,
            CASE 
                WHEN (COALESCE(pu.pickups, 0) - COALESCE(droff.dropoffs, 0)) > 5000 THEN 'Critical Deficit (Demand Source)'
                WHEN (COALESCE(pu.pickups, 0) - COALESCE(droff.dropoffs, 0)) < -5000 THEN 'Critical Surplus (Fleet Sink)'
                ELSE 'Balanced Flow'
            END AS operational_status
        FROM dim_zones z
        LEFT JOIN pu_trips pu ON z.location_id = pu.loc_id
        LEFT JOIN droff_trips droff ON z.location_id = droff.loc_id
        WHERE (COALESCE(pu.pickups, 0) + COALESCE(droff.dropoffs, 0)) > 1000
        ORDER BY ABS(COALESCE(pu.pickups, 0) - COALESCE(droff.dropoffs, 0)) DESC
        """).fetchdf()
        results["metric_3_zone_flow_imbalance"] = df_flow

        # ---------------------------------------------------------------------
        # Metric 4: Airport Corridor Performance & Flat Rate Economics
        # ---------------------------------------------------------------------
        logger.info("Calculating Metric 4: Airport Corridor Performance...")
        df_airport = con.execute("""
        SELECT 
            CASE 
                WHEN f.pickup_location_id = 132 OR f.dropoff_location_id = 132 THEN 'JFK International Airport'
                WHEN f.pickup_location_id = 138 OR f.dropoff_location_id = 138 THEN 'LaGuardia Airport (LGA)'
                WHEN f.pickup_location_id = 1 OR f.dropoff_location_id = 1 THEN 'Newark Airport (EWR)'
                ELSE 'Citywide Non-Airport'
            END AS airport_corridor,
            COUNT(*) AS total_trips,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fct_trips), 2) AS pct_of_all_trips,
            ROUND(AVG(f.trip_distance_miles), 2) AS avg_distance_miles,
            ROUND(AVG(f.duration_minutes), 1) AS avg_duration_min,
            ROUND(MEDIAN(f.effective_speed_mph), 2) AS median_speed_mph,
            ROUND(AVG(f.total_amount), 2) AS avg_total_fare,
            ROUND(SUM(f.total_amount), 2) AS total_revenue,
            ROUND(AVG(f.airport_fee), 2) AS avg_airport_fee,
            ROUND(AVG(f.tolls_amount), 2) AS avg_tolls,
            ROUND(AVG(f.revenue_per_minute), 2) AS avg_revenue_per_min
        FROM fct_trips f
        GROUP BY 1
        ORDER BY total_trips DESC
        """).fetchdf()
        results["metric_4_airport_corridor"] = df_airport

        # ---------------------------------------------------------------------
        # Metric 5: Data Trust & Vendor Anomaly Quarantine Rate
        # ---------------------------------------------------------------------
        logger.info("Calculating Metric 5: Data Trust & Vendor Quarantine Rate...")
        df_trust = con.execute("""
        SELECT 
            v.vendor_name,
            COUNT(*) AS total_records_received,
            SUM(CASE WHEN t.total_violations = 0 THEN 1 ELSE 0 END) AS passed_records,
            SUM(CASE WHEN t.total_violations > 0 THEN 1 ELSE 0 END) AS quarantined_records,
            ROUND(SUM(CASE WHEN t.total_violations = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS trust_score_pct,
            ROUND(SUM(CASE WHEN t.total_violations > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS quarantine_rate_pct,
            SUM(t.flag_zero_or_neg_distance) AS zero_dist_count,
            SUM(t.flag_negative_or_zero_fare) AS non_positive_fare_count,
            SUM(t.flag_duration_too_short) AS short_duration_count,
            SUM(t.flag_implausible_speed) AS implausible_speed_count
        FROM trips_tagged t
        LEFT JOIN dim_vendors v ON t.VendorID = v.vendor_id
        GROUP BY v.vendor_name
        ORDER BY total_records_received DESC
        """).fetchdf()
        results["metric_5_data_trust_vendor"] = df_trust

        # ---------------------------------------------------------------------
        # Executive Summary KPI Table
        # ---------------------------------------------------------------------
        logger.info("Assembling Executive Summary KPI Table...")
        df_exec = con.execute("""
        SELECT 
            COUNT(*) AS clean_trip_volume,
            ROUND(SUM(total_amount), 2) AS total_passenger_expenditure_usd,
            ROUND(AVG(total_amount), 2) AS overall_avg_trip_fare_usd,
            ROUND(AVG(trip_distance_miles), 2) AS overall_avg_distance_miles,
            ROUND(AVG(duration_minutes), 1) AS overall_avg_duration_minutes,
            ROUND(MEDIAN(effective_speed_mph), 2) AS overall_median_speed_mph,
            ROUND(AVG(revenue_per_minute), 2) AS overall_avg_revenue_per_active_min,
            ROUND(SUM(congestion_surcharge), 2) AS total_mta_congestion_surcharge_collected,
            ROUND(SUM(airport_fee), 2) AS total_airport_access_fees_collected
        FROM fct_trips
        """).fetchdf()
        results["executive_summary_kpis"] = df_exec

        return results

    def export_metrics_to_csv(
        self,
        metrics_dict: Dict[str, pd.DataFrame],
        target_month: str = DEFAULT_YEAR_MONTH
    ) -> Dict[str, Path]:
        """Saves metric tables to data/outputs in CSV format for reporting."""
        month_suffix = target_month.replace("-", "_")
        exported_files = {}

        for name, df in metrics_dict.items():
            csv_path = self.outputs_dir / f"{name}_{month_suffix}.csv"
            df.to_csv(csv_path, index=False)
            exported_files[name] = csv_path
            logger.info(f"Saved {name} to {csv_path}")

        return exported_files


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from src.retrieval import DataRetriever
    from src.validation import DataValidator
    from src.transformation import DataTransformer

    retriever = DataRetriever()
    zone_p, _ = retriever.retrieve_taxi_zones_via_api()
    trip_p, _ = retriever.retrieve_trips_parquet()
    con = retriever.load_into_duckdb(trip_p, zone_p)

    validator = DataValidator()
    con, _ = validator.run_validation(con)

    transformer = DataTransformer()
    con = transformer.build_dimensional_model(con)

    calculator = MetricCalculator()
    metrics = calculator.calculate_all_metrics(con)
    calculator.export_metrics_to_csv(metrics)

    print("\n--- Executive Summary KPIs ---")
    print(metrics["executive_summary_kpis"].T.to_string())

    print("\n--- Airport Corridors ---")
    print(metrics["metric_4_airport_corridor"].to_string(index=False))

    print("\n--- Data Trust by Vendor ---")
    print(metrics["metric_5_data_trust_vendor"].to_string(index=False))
