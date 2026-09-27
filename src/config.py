"""
Configuration settings, file paths, and business rules for the NYC TLC Data Pipeline.
"""

from pathlib import Path

# Base Directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
QUARANTINE_DATA_DIR = DATA_DIR / "quarantine"
OUTPUTS_DIR = DATA_DIR / "outputs"
LOGS_DIR = BASE_DIR / "logs"
DOCS_DIR = BASE_DIR / "docs"

# Ensure directories exist
for directory in [DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, QUARANTINE_DATA_DIR, OUTPUTS_DIR, LOGS_DIR, DOCS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Remote Data Sources
TLC_ZONE_LOOKUP_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
TLC_ZONE_LOOKUP_FILENAME = "taxi_zone_lookup.csv"
TLC_TRIP_DATA_BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"

# Target Processing Month
DEFAULT_YEAR_MONTH = "2026-01"
DEFAULT_RAW_PARQUET_FILENAME = f"yellow_tripdata_{DEFAULT_YEAR_MONTH}.parquet"

# Validation Business Rules & Thresholds
VALIDATION_RULES = {
    "min_duration_seconds": 60,         # Exclude trips < 1 minute (meter drops/immediate cancellations)
    "max_duration_seconds": 86400,      # Exclude trips > 24 hours (unclosed meters)
    "min_distance_miles": 0.05,         # Exclude trips with virtually zero movement
    "max_distance_miles": 150.0,        # Physical NYC taxi operating perimeter
    "max_implausible_speed_mph": 85.0,  # Physical NYC traffic speed limit ceiling
    "min_fare_amount": 0.0,             # Exclude negative fares (refunds/chargebacks/meter errors)
    "max_total_amount": 1500.0,         # Outlier ceiling for standard passenger trips
    "valid_min_location_id": 1,
    "valid_max_location_id": 263,       # 264 (Unknown) and 265 (NA) treated as unmapped
}

# Domain Dictionaries
VENDOR_MAP = {
    1: "Creative Mobile Technologies (CMT)",
    2: "VeriFone Inc. (VTS)",
    6: "Pilot Provider Alpha",
    7: "Pilot Provider Beta"
}

RATE_CODE_MAP = {
    1: "Standard Rate",
    2: "JFK Airport Flat Rate",
    3: "Newark Airport",
    4: "Nassau / Westchester",
    5: "Negotiated Fare",
    6: "Group Ride",
    99: "Special / Out of Area Rate"
}

PAYMENT_TYPE_MAP = {
    0: "Unspecified / Void",
    1: "Credit Card",
    2: "Cash",
    3: "No Charge",
    4: "Dispute",
    5: "Unknown",
    6: "Voided Trip"
}

# Manhattan Central Business District (CBD) south of 60th St Location IDs
MANHATTAN_CBD_ZONE_IDS = {
    4, 12, 13, 24, 41, 42, 43, 45, 48, 50, 68, 79, 87, 88, 90, 100, 107, 113, 114, 
    116, 120, 125, 127, 128, 137, 140, 141, 142, 143, 144, 148, 151, 152, 153, 158, 
    161, 162, 163, 164, 166, 170, 186, 209, 211, 224, 229, 230, 231, 232, 233, 234, 
    236, 237, 238, 239, 243, 244, 246, 249, 261, 262, 263
}

AIRPORT_ZONE_IDS = {
    1: "Newark Liberty Airport (EWR)",
    132: "JFK International Airport",
    138: "LaGuardia Airport (LGA)"
}
