#!/usr/bin/env python
"""
Main Execution Script for NYC TLC Data Foundations Pipeline.
Usage:
    python run_pipeline.py [--month 2026-01] [--force-download] [--verbose]
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.pipeline import main

if __name__ == "__main__":
    main()
