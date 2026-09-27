"""
End-to-End Repeatable Pipeline Orchestrator (Class 8 Requirement).
Executes: Ingest -> Validate -> Transform/Model -> Metric Output.
Includes comprehensive logging, data integrity checks, rerun idempotency, and failure handling.
"""

import sys
import logging
import argparse
import time
from pathlib import Path
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    DEFAULT_YEAR_MONTH,
    DEFAULT_RAW_PARQUET_FILENAME,
    LOGS_DIR,
    OUTPUTS_DIR
)
from src.retrieval import DataRetriever
from src.validation import DataValidator
from src.transformation import DataTransformer
from src.metrics import MetricCalculator

# Configure logger
logger = logging.getLogger("NYC_TLC_Pipeline")


def setup_pipeline_logging(verbose: bool = False):
    """Configures both file and console logging handlers."""
    log_file = LOGS_DIR / "pipeline.log"
    log_level = logging.DEBUG if verbose else logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates on reruns
    root_logger.handlers.clear()

    # File handler
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setLevel(log_level)
    fh.setFormatter(formatter)
    root_logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(log_level)
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    return log_file


class TLCPipeline:
    """
    Production-grade ETL & Analytics Pipeline orchestrator.
    Guarantees deterministic, idempotent execution for any given monthly batch.
    """

    def __init__(self, target_month: str = DEFAULT_YEAR_MONTH, force_download: bool = False):
        self.target_month = target_month
        self.force_download = force_download
        self.retriever = DataRetriever()
        self.validator = DataValidator()
        self.transformer = DataTransformer()
        self.calculator = MetricCalculator()

    def run(self) -> Dict[str, Any]:
        """
        Executes the 4-stage pipeline with timing, audit logging, and exception safety.
        """
        start_time = time.time()
        logger.info("=" * 80)
        logger.info(f"STARTING NYC TLC DATA FOUNDATIONS PIPELINE [MONTH: {self.target_month}]")
        logger.info("=" * 80)

        execution_manifest = {
            "target_month": self.target_month,
            "status": "IN_PROGRESS",
            "stages": {}
        }

        try:
            # -------------------------------------------------------------
            # Stage 1: Ingestion & Retrieval (Class 5)
            # -------------------------------------------------------------
            stage1_start = time.time()
            logger.info(">>> STAGE 1: INGESTION & RETRIEVAL (Multi-Mode)")
            
            zone_path, zone_meta = self.retriever.retrieve_taxi_zones_via_api(
                force_download=self.force_download
            )
            raw_parquet_name = f"yellow_tripdata_{self.target_month}.parquet"
            trip_path, trip_meta = self.retriever.retrieve_trips_parquet(raw_parquet_name)

            con = self.retriever.load_into_duckdb(trip_path, zone_path)
            execution_manifest["stages"]["retrieval"] = {
                "duration_seconds": round(time.time() - stage1_start, 2),
                "zones": zone_meta,
                "trips": trip_meta
            }

            # -------------------------------------------------------------
            # Stage 2: Profile & Validate (Class 6)
            # -------------------------------------------------------------
            stage2_start = time.time()
            logger.info(">>> STAGE 2: DATA PROFILING, VALIDATION & QUARANTINE")
            
            con, audit_report = self.validator.run_validation(con, self.target_month)
            quarantine_path, audit_path = self.validator.export_quarantine_and_audit(
                con, audit_report, self.target_month
            )
            execution_manifest["stages"]["validation"] = {
                "duration_seconds": round(time.time() - stage2_start, 2),
                "audit_summary": audit_report,
                "quarantine_file": str(quarantine_path),
                "audit_report_file": str(audit_path)
            }

            # -------------------------------------------------------------
            # Stage 3: Relational Modeling & Transformations (Class 7)
            # -------------------------------------------------------------
            stage3_start = time.time()
            logger.info(">>> STAGE 3: RELATIONAL MODELING (Star Schema)")
            
            con = self.transformer.build_dimensional_model(con)
            exported_tables = self.transformer.export_processed_tables(con, self.target_month)
            execution_manifest["stages"]["transformation"] = {
                "duration_seconds": round(time.time() - stage3_start, 2),
                "exported_tables": {k: str(v) for k, v in exported_tables.items()}
            }

            # -------------------------------------------------------------
            # Stage 4: Metric & KPI Generation (Class 7 & 8)
            # -------------------------------------------------------------
            stage4_start = time.time()
            logger.info(">>> STAGE 4: OPERATIONAL METRICS & KPI EXPORT")
            
            metrics = self.calculator.calculate_all_metrics(con, self.target_month)
            exported_metrics = self.calculator.export_metrics_to_csv(metrics, self.target_month)
            execution_manifest["stages"]["metrics"] = {
                "duration_seconds": round(time.time() - stage4_start, 2),
                "exported_metrics": {k: str(v) for k, v in exported_metrics.items()}
            }

            # -------------------------------------------------------------
            # Stage 5: Visual Evidence Dashboard Generation
            # -------------------------------------------------------------
            try:
                from generate_dashboard import generate_html_dashboard
                dashboard_path = generate_html_dashboard(self.target_month)
                execution_manifest["stages"]["dashboard"] = {
                    "file": str(dashboard_path)
                }
                logger.info(f">>> STAGE 5: EVIDENCE DASHBOARD GENERATED -> {dashboard_path}")
            except Exception as dash_err:
                logger.warning(f"Could not generate evidence dashboard: {dash_err}")

            total_elapsed = round(time.time() - start_time, 2)
            execution_manifest["status"] = "SUCCESS"
            execution_manifest["total_duration_seconds"] = total_elapsed

            logger.info("=" * 80)
            logger.info(f"PIPELINE RUN COMPLETED SUCCESSFULLY IN {total_elapsed} SECONDS")
            logger.info(f"Total Trips Processed: {audit_report['total_records']:,}")
            logger.info(f"Clean Trips Materialized: {audit_report['clean_records']:,} ({audit_report['clean_rate_pct']}%)")
            logger.info(f"Quarantined Anomalies: {audit_report['quarantined_records']:,} ({audit_report['quarantine_rate_pct']}%)")
            logger.info("=" * 80)

            return execution_manifest

        except Exception as e:
            logger.critical(f"FATAL PIPELINE ERROR: {e}", exc_info=True)
            execution_manifest["status"] = "FAILED"
            execution_manifest["error"] = str(e)
            raise


def main():
    parser = argparse.ArgumentParser(description="NYC TLC Data Foundations Repeatable Pipeline CLI")
    parser.add_argument("--month", type=str, default=DEFAULT_YEAR_MONTH, help="Target month format YYYY-MM")
    parser.add_argument("--force-download", action="store_true", help="Force re-download of taxi zones API")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()
    setup_pipeline_logging(verbose=args.verbose)

    pipeline = TLCPipeline(target_month=args.month, force_download=args.force_download)
    manifest = pipeline.run()
    print("\nPipeline run manifest:")
    print(f"Status: {manifest['status']} in {manifest.get('total_duration_seconds')}s")


if __name__ == "__main__":
    main()
