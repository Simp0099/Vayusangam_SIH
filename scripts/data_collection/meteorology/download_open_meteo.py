#!/usr/bin/env python3
"""Download Open-Meteo historical (ERA5/ERA5-Land) meteorology for Delhi NCR.

No API key required. Raw responses are cached per (location, variable-set, window)
so an interrupted run resumes instead of re-fetching.

Test the API and inspect units before any large run:
    .venv/bin/python scripts/data_collection/meteorology/download_open_meteo.py --test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

# parents[3] is the project root (meteorology -> data_collection -> scripts -> repo).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.data_collection.common import DATA_DIR, atomic_write, cache_path, log_event, redact  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = DATA_DIR / "meteorology" / "raw"
PROCESSED_DIR = DATA_DIR / "meteorology" / "processed"
BASE_URL = os.getenv("OPEN_METEO_BASE_URL", "https://archive-api.open-meteo.com/v1/archive")

VARIABLES = ["temperature_2m", "relative_humidity_2m", "surface_pressure",
             "wind_speed_10m", "wind_direction_10m", "cloud_cover", "precipitation"]

# Units declared by the API in its own `hourly_units` block (verified live 2026-09-30).
# These are ASSERTED against the response, not assumed. A mismatch is a hard stop,
# because silently converting on a wrong assumption is worse than not converting.
EXPECTED_UNITS = {"temperature_2m": "°C", "relative_humidity_2m": "%", "surface_pressure": "hPa",
                  "wind_speed_10m": "km/h", "wind_direction_10m": "°", "cloud_cover": "%",
                  "precipitation": "mm"}

# Delhi NCR core, plus an outer ring covering the Haryana / western-UP belt that
# the OpenAQ bbox also returns stations from. The five outer points were chosen by
# greedy max-coverage over the real 220 station coordinates on 2026-09-30 (each
# added only where it covered stations the previous points did not). They lift
# coverage within 35 km from 51.4% to 59.5% of all stations.
NCR_POINTS = {
    "Delhi": (28.6139, 77.2090),
    "Gurugram": (28.4595, 77.0266),
    "Noida": (28.5355, 77.3910),
    "Ghaziabad": (28.6692, 77.4538),
    "Faridabad": (28.4089, 77.3178),
    # Outer ring: Haryana / western UP edge of the same airshed.
    "Sonipat": (29.0272, 77.0621),
    "Hapur": (28.7256, 77.7497),
    "Ballabgarh": (28.3419, 77.3197),
    "Manesar": (28.3607, 76.9361),
    "AnandVihar_NCR": (28.6787, 77.2262),
}


def fetch(lat: float, lon: float, start: str, end: str, refresh: bool = False) -> dict:
    query = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
             "hourly": ",".join(VARIABLES), "timezone": "UTC"}
    path = cache_path(RAW_DIR, f"open-meteo_{lat:.4f}_{lon:.4f}_{start}_{end}", query)
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    atomic = path.with_suffix(".json.tmp")
    last_error = None
    for attempt in range(4):
        try:
            r = httpx.get(BASE_URL, params=query, timeout=120,
                          headers={"User-Agent": "VayuSangam-OpenMeteo/1.0"})
            r.raise_for_status()
            payload = r.json()
            atomic_write(path, json.dumps(payload, indent=1))
            return payload
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < 3:
                import time
                time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"Open-Meteo request failed after 4 attempts: {last_error}")


def check_units(payload: dict) -> list[str]:
    """Verify the API's declared units. Returns a list of mismatches (empty = OK)."""
    units = payload.get("hourly_units", {})
    return [f"{v}: expected {EXPECTED_UNITS[v]}, API declared {units.get(v)!r}"
            for v in VARIABLES if units.get(v) != EXPECTED_UNITS[v]]


def to_frame(payload: dict, place: str) -> pd.DataFrame:
    hourly = payload.get("hourly", {})
    frame = pd.DataFrame({k: hourly.get(k) for k in ["time", *VARIABLES]})
    # API returns naive local-to-request ISO strings; timezone=UTC makes them UTC.
    frame["timestamp"] = pd.to_datetime(frame.pop("time"), utc=True)
    frame["place"] = place
    # Record the ERA5 grid cell the request actually resolved to. Downstream
    # station matching must use this cell, not the nominal requested coordinate.
    frame["grid_lat"] = payload.get("latitude")
    frame["grid_lon"] = payload.get("longitude")
    frame["elevation"] = payload.get("elevation")
    # Open-Meteo declares wind_speed_10m in km/h; convert to m/s and record it.
    if "wind_speed_10m" in frame:
        frame["wind_speed_10m_ms"] = frame["wind_speed_10m"] / 3.6
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Fetch 2 days for Delhi only")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--points", default="all", help="'all', 'test', or comma-separated place names")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    end = args.end_date or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    start = args.start_date
    if args.test:
        places = ["Delhi"]
        start, end = "2024-01-01", "2024-01-02"
    elif args.points == "test":
        places = list(NCR_POINTS)
    else:
        places = ([p.strip() for p in args.points.split(",")] if args.points != "all" else list(NCR_POINTS))

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    frames, problems = [], []
    for place in places:
        if place not in NCR_POINTS:
            print(f"Unknown place {place!r}; known: {', '.join(NCR_POINTS)}", file=sys.stderr)
            return 2
        lat, lon = NCR_POINTS[place]
        payload = fetch(lat, lon, start, end, args.refresh)
        mismatches = check_units(payload)
        if mismatches:
            problems += [f"{place}: {m}" for m in mismatches]
            log_event("open-meteo", f"fetch:{place}", "UNIT_MISMATCH", 0, 0, redact(str(payload.get("latitude"))), "; ".join(mismatches))
            continue
        frame = to_frame(payload, place)
        frames.append(frame)
        log_event("open-meteo", f"fetch:{place}", "OK", len(frame), 0, f"{lat},{lon} {start}->{end}")
        print(f"{place:<10} {len(frame):>6} hourly rows  elevation={payload.get('elevation')} m  "
              f"grid=({payload.get('latitude'):.3f},{payload.get('longitude'):.3f})")

    if problems:
        print("\nUNIT MISMATCH — refusing to convert on an unverified unit:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 3
    if not frames:
        print("No data fetched.", file=sys.stderr)
        return 2

    out = pd.concat(frames, ignore_index=True).sort_values(["timestamp", "place"])
    csv_path = PROCESSED_DIR / "meteorology_hourly.csv"
    atomic_write(csv_path, out.to_csv(index=False))
    print(f"\nWrote {csv_path} — {len(out):,} rows, {out.place.nunique()} points, "
          f"{out.timestamp.min()} → {out.timestamp.max()}")
    print("Units: temperature °C, RH %, pressure hPa, wind_speed_10m km/h AND wind_speed_10m_ms, "
          "cloud_cover %, precipitation mm. All timestamps UTC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
