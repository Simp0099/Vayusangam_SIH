#!/usr/bin/env python3
"""Discover and validate CAMS EAC4 variables against the live ADS schema.

No download. CAMS is blocked without an ADS credential, and EAC4 is a large
GRIB download that needs approval. This script confirms which variable names
really exist, so no name is ever invented, and prints an estimate for the gate.

    .venv/bin/python scripts/data_collection/cams/prepare_cams.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ADS_CONFIG = Path(os.path.expanduser("~/.cdsapirc"))
PROCESS = "cams-global-reanalysis-eac4"
ADS_BASE = "https://ads.atmosphere.copernicus.eu/api/retrieve/v1/processes"

# Only names confirmed present in the EAC4 schema on 2026-09-30 (62 variables).
# Nothing outside this list may be requested.
WANTED = ["particulate_matter_2.5um", "particulate_matter_10um", "particulate_matter_1um",
          "nitrogen_dioxide", "ozone", "carbon_monoxide", "sulphur_dioxide",
          "total_aerosol_optical_depth_550nm", "dust_aerosol_optical_depth_550nm"]


def check_config() -> tuple[bool, str]:
    if not ADS_CONFIG.exists():
        return False, (f"{ADS_CONFIG} not found. Register at https://ads.atmosphere.copernicus.eu/ "
                       "(ECMWF single sign-on), copy the API block to ~/.cdsapirc with "
                       "url: https://ads.atmosphere.copernicus.eu/api and key: <token> "
                       "(no uid: since the 2025 migration), then accept the CAMS licence.")
    text = ADS_CONFIG.read_text(encoding="utf-8")
    host = next((l.split(":", 1)[1].strip() for l in text.splitlines()
                 if l.strip().lower().startswith("url:")), "unknown")
    note = f"~/.cdsapirc present, url={host}"
    if "ads.atmosphere.copernicus.eu" not in host:
        note += " | WARNING: this points at CDS, not ADS; CAMS needs the ADS host"
    return True, note


def verify_schema() -> tuple[list[str], list[str]]:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        r = client.get(f"{ADS_BASE}/{PROCESS}")
        if r.status_code != 200:
            return [], [f"{PROCESS}: HTTP {r.status_code}"]
        schema = r.json()["inputs"]
        enum = schema["variable"]["schema"]["items"]["enum"]
        confirmed = [v for v in WANTED if v in enum]
        problems = [f"{v} is NOT in {PROCESS} — do not request it" for v in WANTED if v not in enum]
        return confirmed, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="")
    args = parser.parse_args()

    print("CAMS EAC4 preparation — no download performed.\n")
    ok, message = check_config()
    print(f"Credentials: {'OK' if ok else 'MISSING'} — {message}\n")

    confirmed, problems = verify_schema()
    print(f"Schema check against the live ADS API ({PROCESS}):")
    for c in confirmed:
        print(f"  ✓ {c}")
    for p in problems:
        print(f"  ✗ {p}")
    if problems:
        print("\nRefusing to estimate from unconfirmed variable names.", file=sys.stderr)
        return 3

    import pandas as pd
    start = pd.Timestamp(args.start_date)
    end = pd.Timestamp(args.end_date or "2024-12-31")
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    hours = months * 30 * 8  # EAC4 is 3-hourly
    lat_n = int((31 - 27) / 0.75) + 1
    lon_n = int((80 - 73) / 0.75) + 1
    gb = hours * len(confirmed) * lat_n * lon_n * 4 / 1e9
    print(f"\nProposed scope (for approval, not requested):")
    print(f"  Period    {args.start_date} → {end.date()}  ({months} months, {hours:,} 3-hourly steps)")
    print(f"  Area      N31 W73 S27 E80  ({lat_n} x {lon_n} cells at 0.75°)")
    print(f"  Variables {len(confirmed)}")
    print(f"  Estimate  ~{gb:.2f} GB raw (EAC4 covers 2003–2024; later years may not exist yet)")
    print("\nRequest only after approval, and only after the ADS licence is accepted.")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
