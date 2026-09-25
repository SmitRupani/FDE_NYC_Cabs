"""
Unit tests for data retrieval and provenance integrity (Class 5).
"""

import pytest
from pathlib import Path
import duckdb
import pandas as pd

from src.retrieval import compute_sha256, DataRetriever
from src.config import RAW_DATA_DIR, TLC_ZONE_LOOKUP_FILENAME


def test_sha256_computation(tmp_path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Hello TLC Pipeline")
    hash_val = compute_sha256(test_file)
    assert isinstance(hash_val, str)
    assert len(hash_val) == 64


def test_zone_retrieval():
    retriever = DataRetriever(raw_dir=RAW_DATA_DIR)
    path, meta = retriever.retrieve_taxi_zones_via_api()
    assert path.exists()
    assert meta["record_count"] >= 260
    assert "LocationID" in meta["columns"]
    assert "Borough" in meta["columns"]


def test_duckdb_views_creation():
    retriever = DataRetriever(raw_dir=RAW_DATA_DIR)
    zone_p, _ = retriever.retrieve_taxi_zones_via_api()
    trip_p, _ = retriever.retrieve_trips_parquet()
    con = duckdb.connect()
    con = retriever.load_into_duckdb(trip_p, zone_p, con)

    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "raw_trips" in tables
    assert "raw_zones" in tables
