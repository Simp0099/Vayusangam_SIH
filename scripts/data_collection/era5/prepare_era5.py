#!/usr/bin/env python3
"""Prepare ERA5 requests for the Delhi NCR region and verify credentials.

This script does NOT download ERA5. ERA5 is a large NetCDF/GRIB download and
requires explicit approval plus a configured ~/.cdsapirc. What this script does
is: validate that the credential file exists and points at the new CDS engine,
assert that the requested variable names really exist in the live dataset schema,
and print a size estimate for the approval report.

    .venv/bin/python scripts/data_collection/era5/prepare_era5.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CDS_CONFIG = Path(os.path.expanduser(os.getenv("CDSAPI_CONFIG", "~/.cdsapirc")))
CDSBASE = "https://cds.climate.copernicus.eu/api/retrieve/v1/processes"

# Region requested for VayuSangam. NOTE the ERA5 `area` order is [N, W, S, E],
# which differs from our internal west,south,east,north convention.
REGION = {"north": 31, "west": 73, "south": 27, "east": 80}
ERA5_AREA = [REGION["north"], REGION["west"], REGION["south"], REGION["east"]]

SINGLE_LEVELS = ["2m_temperature", "2m_dewpoint_temperature", "10m_u_component_of_wind",
                 "10m_v_component_of_wind", "surface_pressure", "mean_sea_level_pressure",
                 "boundary_layer_height"]
PRESSURE_LEVELS = ["temperature"]
PRESSURES = ["925", "850"]  # inversion diagnostics; see docs/INVERSION_FEATURES.md


def check_config() -> tuple[bool, str]:
    if not CDS_CONFIG.exists():
        return False, (f"{CDS_CONFIG} not found. Register at https://cds.climate.copernicus.eu/ "
                       "(ECMWF single sign-on), copy the API block to ~/.cdsapirc containing "
                       "url: and key: only (no uid: since the 2025 migration), then accept the "
                       "ERA5 licence on the dataset download page.")
    text = CDS_CONFIG.read_text(encoding="utf-8")
    host = next((l.split(":", 1)[1].strip() for l in text.splitlines()
                 if l.strip().lower().startswith("url:")), "unknown")
    notes = [f"~/.cdsapirc present, url={host}"]
    if "uid:" in text.lower():
        notes.append("WARNING: contains a legacy 'uid:' field; the new CDS rejects it — remove it")
    if "cds.climate.copernicus.eu" not in host and "ads.atmosphere.copernicus.eu" not in host:
        notes.append("WARNING: url does not point at the new CDS/ADS engine")
    return True, "; ".join(notes)


def verify_schema() -> tuple[list[str], list[str]]:
    """Confirm the variable names exist in the live dataset schema."""
    problems: list[str] = []
    confirmed: list[str] = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for process, wanted in (("reanalysis-era5-single-levels", SINGLE_LEVELS),
                                ("reanalysis-era5-pressure-levels", PRESSURE_LEVELS)):
            r = client.get(f"{CDSBASE}/{process}")
            if r.status_code != 200:
                problems.append(f"{process}: HTTP {r.status_code}")
                continue
            enum = r.json()["inputs"]["variable"]["schema"]["items"]["enum"]
            for v in wanted:
                if v in enum:
                    confirmed.append(f"{process}:{v}")
                else:
                    problems.append(f"{v} is NOT in {process} — do not request it")
    return confirmed, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="")
    args = parser.parse_args()

    print("ERA5 preparation — no download performed.\n")
    ok, message = check_config()
    print(f"Credentials: {'OK' if ok else 'MISSING'} — {message}\n")

    confirmed, problems = verify_schema()
    print(f"Schema check against the live CDS API: {len(confirmed)} variable(s) confirmed")
    for c in confirmed:
        print(f"  ✓ {c}")
    for p in problems:
        print(f"  ✗ {p}")
    if problems:
        print("\nRefusing to estimate a download from unconfirmed variable names.", file=sys.stderr)
        return 3

    import pandas as pd
    start = pd.Timestamp(args.start_date)
    end = pd.Timestamp(args.end_date or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d"))
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    lat_n = int((REGION["north"] - REGION["south"]) / 0.25) + 1
    lon_n = int((REGION["east"] - REGION["west"]) / 0.25) + 1
    hours = months * 30 * 24
    n_vars = len(SINGLE_LEVELS) + len(PRESSURE_LEVELS) * len(PRESSURES)
    # ERA5 single-level fields are float32: ~4 bytes per grid cell per hour.
    raw_gb = hours * n_vars * lat_n * lon_n * 4 / 1e9
    print(f"\nProposed scope (for approval, not yet requested):")
    print(f"  Period      {args.start_date} → {end.date()}  ({months} months, {hours:,} hours)")
    print(f"  Area        N{REGION['north']} W{REGION['west']} S{REGION['south']} E{REGION['east']}"
          f"  -> ERA5 area={ERA5_AREA}  ({lat_n} x {lon_n} cells at 0.25°)")
    print(f"  Variables   {n_vars} ({', '.join(SINGLE_LEVELS)}; temperature @ {', '.join(PRESSURES)} hPa)")
    print(f"  Estimate    ~{raw_gb:.2f} GB raw (uncompressed float32 grid arithmetic)")
    print("\nThis exceeds the approval threshold. Run the request only after approval:")
    print("  .venv/bin/python scripts/data_collection/era5/download_era5.py --start-date "
          f"{args.start_date} --end-date {end.date()}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
