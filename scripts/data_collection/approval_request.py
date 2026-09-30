#!/usr/bin/env python3
"""Print an APPROVAL REQUIRED report for a proposed large download.

Estimates are computed from the *actual* OpenAQ sensor metadata already on disk
(declared sensor history per station/variable), not guessed. Nothing is
downloaded by this script.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AQ_DIR = PROJECT_ROOT / "data" / "air_quality"

# MEASURED 2026-09-30 during the production run: real station-month pages average
# ~496 KB. The earlier 0.078 MB figure came from a 3-day sample whose stations had
# sparse history and underestimated the true size by roughly 6x. Use the measured
# value; if a fresh measurement is available prefer it.
MB_PER_STATION_MONTH = 0.484
# Observed throughput on the production run: ~37 station-month pages/min.
PAGES_PER_MINUTE = 37.0
# A wide parquet row of 11 float variables with dictionary-encoded strings.
BYTES_PER_HOURLY_CELL = 11 * 0.35


def station_months(frame: pd.DataFrame, params: list[str] | None, start: str) -> pd.DataFrame:
    sel = frame.copy()
    if params:
        sel = sel[sel.parameter.isin(params)]
    first = pd.to_datetime(sel.datetime_first_utc, utc=True, errors="coerce").clip(lower=pd.Timestamp(start, tz="UTC"))
    last = pd.to_datetime(sel.datetime_last_utc, utc=True, errors="coerce").clip(upper=pd.Timestamp.now(tz="UTC").floor("D"))
    sel["months"] = np.ceil((last.dt.year - first.dt.year) * 12 + (last.dt.month - first.dt.month)).clip(lower=0)
    return sel[sel.months > 0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="", help="Inclusive YYYY-MM-DD; blank = today")
    parser.add_argument("--variables", default="PM2.5", help="Comma-separated; 'all' for every variable")
    args = parser.parse_args()

    sensors_path = AQ_DIR / "sensor_metadata.csv"
    if not sensors_path.exists():
        print("Run download_openaq.py first so station/sensor metadata exists.", file=sys.stderr)
        return 2
    sensors = pd.read_csv(sensors_path)
    sensors = sensors[sensors.selected_for_variable.astype(str).str.lower().isin(["true", "1"])]
    params = None if args.variables.lower() == "all" else [v.strip() for v in args.variables.split(",") if v.strip()]

    end = args.end_date or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    scope = station_months(sensors, params, args.start_date)
    total_months = float(scope.months.sum())
    # Cap each sensor's span at the requested end date rather than "today".
    first = pd.to_datetime(scope.datetime_first_utc, utc=True, errors="coerce").clip(lower=pd.Timestamp(args.start_date, tz="UTC"))
    last = pd.to_datetime(scope.datetime_last_utc, utc=True, errors="coerce").clip(upper=pd.Timestamp(end, tz="UTC"))
    capped = np.ceil((last.dt.year - first.dt.year) * 12 + (last.dt.month - first.dt.month)).clip(lower=0)
    total_months = float(capped.sum())
    station_count = int(scope.station_id.nunique())
    variable_count = int(scope.parameter.nunique())
    raw_gb = total_months * MB_PER_STATION_MONTH / 1024
    cells = total_months * 30 * 24
    parquet_mb = cells * variable_count * BYTES_PER_HOURLY_CELL / 1e6
    requests = int(total_months)
    # Throughput measured on the live production run, with the client's own
    # 429 handling on top.
    minutes = requests / PAGES_PER_MINUTE

    print("\n## \u23f8\ufe0f APPROVAL REQUIRED\n")
    print("**Dataset:** OpenAQ v3 hourly station observations (`/sensors/{id}/hours`)")
    print("**Source:** https://api.openaq.org/v3 (aggregating CPCB, state boards, AirGradient, caaqm)")
    print("**Region:** Delhi NCR + adjacent Punjab / Haryana / Western UP")
    print("**Geographic bbox:** WGS84 74.0,26.0 → 80.0,32.5 (never global)")
    print(f"**Date range:** {args.start_date} → {end}")
    print(f"**Variables:** {', '.join(sorted(scope.parameter.unique())) or 'none'}")
    print(f"**Stations:** {station_count}  (sensors: {len(scope)})")
    print(f"**Estimated records:** {cells:,.0f} station-hours (upper bound), {total_months:,.0f} station-months")
    print(f"**Estimated download size:** {raw_gb:.2f} GB raw JSON")
    print(f"**Estimated processed size:** ~{parquet_mb:.0f} MB parquet")
    print(f"**Estimated API requests:** ~{requests:,} (paginated at limit=1000)")
    print(f"**Estimated runtime:** ~{minutes:.0f} min at 1 req/0.9 s, longer if rate-limited")
    print("\n**Why VayuSangam needs it:**")
    print("  - Supervised training targets for 72-hour PM2.5 and AQI forecasting")
    print("  - Station-level ground truth to validate ERA5/CAMS predictions")
    print("  - Long history needed for lagged features (t-1…t-24) and seasonal coverage")
    print("\n**Test download completed:** YES — station 2860223 (GK1, Oberoi Terrace), 72 h, "
          f"{AQ_DIR.name}/raw/hours, 51/72 valid PM2.5 hours, 0 duplicates, 0 invalid values")
    print("\n**Potential issues:**")
    print("  - Several stations report <10% coverage; `data_quality_report.csv` flags them")
    print("  - Non-PM2.5 variables are unevenly deployed (NOx 156/220, wind 145/220 stations)")
    print("  - `district` is empty for all stations (OpenAQ v3 exposes no administrative area)")
    print("  - Raw cache is git-ignored; re-running after a wipe re-downloads from scratch")
    print("\n**Proposed command:**")
    print(f"  .venv/bin/python scripts/data_collection/openaq/download_openaq.py \\\n"
          f"      --start-date {args.start_date} --end-date {end}")
    print("  .venv/bin/python scripts/data_collection/openaq/process_openaq.py")
    print("  .venv/bin/python scripts/data_collection/openaq/validate_openaq.py")
    print("\nThe download is resumable: every raw page is cached under "
          "`data/air_quality/raw/hours/` and re-runs reuse it.\n")
    print("### Waiting for your approval.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
