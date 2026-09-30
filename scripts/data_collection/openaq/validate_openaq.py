#!/usr/bin/env python3
"""Validate generated OpenAQ station-hour files without needing API credentials."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import pandas as pd

try:  # Support both direct script execution and imports from tests/tools.
    from .common import DATA_DIR, EXPECTED_COLUMNS, FINAL_UNITS, VARIABLES
except ImportError:
    from common import DATA_DIR, EXPECTED_COLUMNS, FINAL_UNITS, VARIABLES


def main() -> int:
    aq_path = DATA_DIR / "air_quality_hourly.csv"
    meta_path = DATA_DIR / "station_metadata.csv"
    availability_path = DATA_DIR / "station_availability.csv"
    quality_path = DATA_DIR / "data_quality_report.csv"
    manifest_path = DATA_DIR / "collection_manifest.json"
    missing = [str(p.name) for p in (aq_path, meta_path, availability_path, quality_path, manifest_path) if not p.exists()]
    if missing:
        print("Validation cannot run; missing generated files: " + ", ".join(missing))
        print("Add OPENAQ_API_KEY to .env and run the sample download, then process it.")
        return 2
    frame = pd.read_csv(aq_path, keep_default_na=True)
    metadata = pd.read_csv(meta_path)
    availability = pd.read_csv(availability_path)
    quality = pd.read_csv(quality_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems, warnings = [], []
    missing_columns = sorted(set(EXPECTED_COLUMNS) - set(frame.columns))
    if missing_columns: problems.append(f"missing columns: {missing_columns}")
    if not frame.empty:
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        if timestamps.isna().any(): problems.append(f"{int(timestamps.isna().sum())} invalid timestamps")
        if frame.duplicated(["station_id", "timestamp"]).any(): problems.append("duplicate station_id + timestamp rows")
        start = pd.Timestamp(manifest["requested_start_date"], tz="UTC")
        end = pd.Timestamp(date.fromisoformat(manifest["requested_end_date"]) + timedelta(days=1), tz="UTC")
        if ((timestamps < start) | (timestamps >= end)).any(): problems.append("timestamps outside requested inclusive date range")
        if not set(frame["station_id"].astype(str)).issubset(set(metadata["station_id"].astype(str))):
            problems.append("station metadata join failed for one or more output station IDs")
        numeric = frame[VARIABLES].apply(pd.to_numeric, errors="coerce")
        if numeric["relative_humidity"].dropna().gt(100).any(): problems.append("relative humidity exceeds 100%")
        if numeric["wind_direction"].dropna().gt(360).any(): problems.append("wind direction exceeds 360 degrees")
        for column in ("PM2.5", "PM10", "NO2", "NOx", "O3", "CO", "SO2", "wind_speed"):
            if numeric[column].dropna().lt(0).any(): problems.append(f"negative values in {column}")
        if numeric.isna().all(axis=None): warnings.append("all normalized measurements are null; inspect unit support and API responses")
    if availability.empty:
        warnings.append("no locations were returned in the configured region")
    if quality.empty:
        problems.append("data quality report is empty")
    else:
        bad_pct = quality["missing_percentage"].dropna().between(0, 100, inclusive="both")
        if not bad_pct.all(): problems.append("missing_percentage outside 0..100")
    print(f"Rows: {len(frame):,}; stations with downloaded hourly grid: {frame.station_id.nunique() if not frame.empty else 0}")
    print(f"Discovered stations: {len(metadata):,}; PM2.5-capable stations: {availability.get('has_pm25', pd.Series(dtype=bool)).astype(str).str.lower().isin(['true','1']).sum():,}")
    print("Timestamp field: UTC hourly interval start")
    print("Final units: " + ", ".join(f"{v}={FINAL_UNITS[v]}" for v in VARIABLES))
    for warning in warnings: print("WARNING: " + warning)
    for problem in problems: print("ERROR: " + problem)
    print("Validation: " + ("FAILED" if problems else "PASSED"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
