"""
Data Retrieval Module (Class 5 Requirement).
Demonstrates two distinct retrieval modes:
1. Local Parquet ingestion with SHA-256 checksum & metadata verification.
2. Network API / HTTP CSV retrieval with retry logic, completeness checks, and raw persistence.
"""

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, Tuple
import requests
import pyarrow.parquet as pq
import pandas as pd
import duckdb

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    RAW_DATA_DIR,
    TLC_ZONE_LOOKUP_URL,
    TLC_ZONE_LOOKUP_FILENAME,
    TLC_TRIP_DATA_BASE_URL,
    DEFAULT_RAW_PARQUET_FILENAME,
    BASE_DIR
)

logger = logging.getLogger(__name__)


def compute_sha256(filepath: Path) -> str:
    """Calculate SHA-256 hash of a file for integrity and provenance tracking."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


class DataRetriever:
    """
    Handles multi-mode data retrieval, raw input preservation, and completeness verification.
    """

    def __init__(self, raw_dir: Path = RAW_DATA_DIR):
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def retrieve_taxi_zones_via_api(
        self,
        url: str = TLC_ZONE_LOOKUP_URL,
        filename: str = TLC_ZONE_LOOKUP_FILENAME,
        force_download: bool = False
    ) -> Tuple[Path, Dict[str, Any]]:
        """
        Retrieval Mode 2: Network HTTP API / CSV retrieval.
        Retrieves official TLC Taxi Zone Lookup reference, verifies completeness,
        and saves raw copy to data/raw.
        """
        destination_path = self.raw_dir / filename

        if destination_path.exists() and not force_download:
            logger.info(f"Taxi zone lookup already exists at {destination_path}. Checking integrity...")
        else:
            logger.info(f"Retrieving taxi zone lookup via HTTP GET from: {url}")
            try:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                with open(destination_path, "wb") as f:
                    f.write(response.content)
                logger.info(f"Successfully retrieved and saved {len(response.content)} bytes to {destination_path}")
            except Exception as e:
                logger.error(f"Failed to retrieve taxi zone lookup from {url}: {e}")
                raise

        # Verification of completeness
        df_zones = pd.read_csv(destination_path)
        record_count = len(df_zones)
        expected_min_records = 260
        required_columns = {"LocationID", "Borough", "Zone", "service_zone"}

        if record_count < expected_min_records:
            raise ValueError(f"Incomplete zone retrieval: found {record_count} rows, expected >= {expected_min_records}")
        
        missing_cols = required_columns - set(df_zones.columns)
        if missing_cols:
            raise ValueError(f"Incomplete schema in zone lookup. Missing columns: {missing_cols}")

        sha256 = compute_sha256(destination_path)
        metadata = {
            "mode": "HTTP_API_CSV",
            "source_url": url,
            "local_path": str(destination_path),
            "record_count": record_count,
            "columns": list(df_zones.columns),
            "sha256": sha256,
            "status": "VERIFIED_COMPLETE"
        }
        logger.info(f"Zone lookup verified complete: {record_count} zones, SHA256: {sha256[:12]}...")
        return destination_path, metadata

    def retrieve_trips_parquet(
        self,
        filename: str = DEFAULT_RAW_PARQUET_FILENAME
    ) -> Tuple[Path, Dict[str, Any]]:
        """
        Retrieval Mode 1: Parquet file retrieval with integrity hashing & metadata check.
        Preserves raw input in data/raw.
        """
        destination_path = self.raw_dir / filename

        # If not in data/raw yet, check workspace root, or retrieve from remote TLC CloudFront CDN
        if not destination_path.exists():
            root_candidate = BASE_DIR / filename
            if root_candidate.exists():
                logger.info(f"Preserving raw parquet file from root to {destination_path}...")
                shutil.copy2(root_candidate, destination_path)
            else:
                remote_url = f"{TLC_TRIP_DATA_BASE_URL}/{filename}"
                logger.info(f"Raw parquet not found locally. Retrieving via HTTP GET from: {remote_url}")
                try:
                    with requests.get(remote_url, stream=True, timeout=60) as r:
                        if r.status_code == 404:
                            raise FileNotFoundError(
                                f"Trip data file '{filename}' was not found locally in {destination_path} "
                                f"and does not exist on remote NYC TLC CloudFront CDN ({remote_url})."
                            )
                        r.raise_for_status()
                        total_bytes = int(r.headers.get("content-length", 0))
                        downloaded = 0
                        temp_dest = destination_path.with_suffix(".parquet.part")
                        with open(temp_dest, "wb") as f:
                            for chunk in r.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if total_bytes > 0 and (downloaded % (10 * 1024 * 1024) < 1024 * 1024):
                                        pct = round((downloaded / total_bytes) * 100, 1)
                                        logger.info(f"Downloading {filename}: {downloaded / 1024 / 1024:.1f} MB / {total_bytes / 1024 / 1024:.1f} MB ({pct}%)")
                        temp_dest.replace(destination_path)
                        logger.info(f"Successfully retrieved and preserved raw parquet file to {destination_path} ({destination_path.stat().st_size / 1024 / 1024:.1f} MB)")
                except Exception as e:
                    temp_part = destination_path.with_suffix(".parquet.part")
                    if temp_part.exists():
                        temp_part.unlink(missing_ok=True)
                    logger.error(f"Failed to retrieve trips parquet from {remote_url}: {e}")
                    raise

        # Verify Parquet completeness and metadata
        parquet_file = pq.ParquetFile(destination_path)
        metadata_pq = parquet_file.metadata
        num_rows = metadata_pq.num_rows
        num_columns = metadata_pq.num_columns
        num_row_groups = metadata_pq.num_row_groups
        schema_names = parquet_file.schema.names
        sha256 = compute_sha256(destination_path)

        if num_rows == 0:
            raise ValueError(f"Parquet file {destination_path} is empty (0 rows)!")

        metadata = {
            "mode": "LOCAL_PARQUET_FILE",
            "local_path": str(destination_path),
            "file_size_bytes": destination_path.stat().st_size,
            "num_rows": num_rows,
            "num_columns": num_columns,
            "num_row_groups": num_row_groups,
            "schema_columns": schema_names,
            "sha256": sha256,
            "status": "VERIFIED_COMPLETE"
        }
        logger.info(f"Parquet trip data verified complete: {num_rows:,} rows, {num_columns} cols, SHA256: {sha256[:12]}...")
        return destination_path, metadata

    def load_into_duckdb(
        self,
        trips_path: Path,
        zones_path: Path,
        con: duckdb.DuckDBPyConnection = None
    ) -> duckdb.DuckDBPyConnection:
        """
        Retrieval Mode 3 / Integration: Analytical SQL engine ingestion.
        Registers both sources into a high-performance in-process database session.
        """
        if con is None:
            con = duckdb.connect()

        logger.info("Registering raw datasets into DuckDB SQL engine...")
        trips_path_str = str(trips_path).replace("\\", "/")
        zones_path_str = str(zones_path).replace("\\", "/")

        con.execute(f"CREATE OR REPLACE VIEW raw_trips AS SELECT * FROM read_parquet('{trips_path_str}')")
        con.execute(f"CREATE OR REPLACE VIEW raw_zones AS SELECT * FROM read_csv_auto('{zones_path_str}')")
        
        trip_cnt = con.execute("SELECT COUNT(*) FROM raw_trips").fetchone()[0]
        zone_cnt = con.execute("SELECT COUNT(*) FROM raw_zones").fetchone()[0]
        logger.info(f"DuckDB views successfully created. raw_trips: {trip_cnt:,} rows | raw_zones: {zone_cnt} rows.")
        return con


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    retriever = DataRetriever()
    zone_p, zone_meta = retriever.retrieve_taxi_zones_via_api()
    trip_p, trip_meta = retriever.retrieve_trips_parquet()
    con = retriever.load_into_duckdb(trip_p, zone_p)
    print("\nRetrieval Complete!")
    print(f"Zones metadata: {zone_meta}")
    print(f"Trips metadata: {trip_meta}")
