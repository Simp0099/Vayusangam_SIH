#!/usr/bin/env python3
"""Download Open-Meteo HISTORICAL FORECAST (previous model runs) for Delhi NCR.

Why this exists: the historical-weather archive is ERA5 *reanalysis* — hindsight,
not a forecast. A 72-hour forecasting system cannot be evaluated on reanalysis
fields, and the audit of 2026-09-30 correctly flagged "forecast NWP archive" as
MISSING. This endpoint returns what the forecast model actually issued at the
time, which is the input an operational forecast would have had.

It also supplies `boundary_layer_height` (PBLH) and radiation, which the archive
endpoint does not serve and which inversion features need.

No API key. Units are asserted against the API's own `hourly_units` block.

    .venv/bin/python scripts/data_collection/meteorology/download_forecast.py --test
    .venv/bin/python scripts/data_collection/meteorology/download_forecast.py \
        --start-date 2024-01-01 --end-date 2026-09-30
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.data_collection.common import atomic_write, cache_path, log_event  # noqa: E402
from scripts.data_collection.meteorology.download_open_meteo import NCR_POINTS  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "meteorology" / "raw"
OUT_DIR = PROJECT_ROOT / "data" / "meteorology" / "processed"
BASE = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Previous-model-run fields. PBLH and radiation are the reason this collector
# exists: the archive endpoint does not serve them.
VARIABLES = ["temperature_2m", "dew_point_2m", "relative_humidity_2m", "surface_pressure",
             "wind_speed_10m", "wind_direction_10m", "cloud_cover", "precipitation",
             "boundary_layer_height", "shortwave_radiation"]

EXPECTED_UNITS = {"temperature_2m": "°C", "dew_point_2m": "°C", "relative_humidity_2m": "%",
                  "surface_pressure": "hPa", "wind_speed_10m": "km/h", "wind_direction_10m": "°",
                  "cloud_cover": "%", "precipitation": "mm", "boundary_layer_height": "m",
                  "shortwave_radiation": "W/m²"}


def fetch(lat: float, lon: float, start: str, end: str, refresh: bool = False) -> dict:
    query = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
             "hourly": ",".join(VARIABLES), "timezone": "UTC"}
    path = cache_path(RAW_DIR, f"forecast_{lat:.4f}_{lon:.4f}_{start}_{end}", query)
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    last = None
    for attempt in range(4):
        try:
            r = httpx.get(BASE, params=query, timeout=180,
                          headers={"User-Agent": "VayuSangam-Forecast/1.0"})
            r.raise_for_status()
            payload = r.json()
            atomic_write(path, json.dumps(payload, indent=1))
            return payload
        except Exception as exc:  # noqa: BLE001 - retried
            last = exc
            if attempt < 3:
                import time
                time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"historical-forecast request failed after 4 attempts: {last}")


def check_units(payload: dict) -> list[str]:
    units = payload.get("hourly_units", {})
    return [f"{v}: expected {EXPECTED_UNITS[v]}, API declared {units.get(v)!r}"
            for v in VARIABLES if units.get(v) != EXPECTED_UNITS[v]]


def to_frame(payload: dict, place: str) -> pd.DataFrame:
    hourly = payload.get("hourly", {})
    frame = pd.DataFrame({k: hourly.get(k) for k in ["time", *VARIABLES]})
    frame["timestamp"] = pd.to_datetime(frame.pop("time"), utc=True)
    frame["place"] = place
    frame["grid_lat"] = payload.get("latitude")
    frame["grid_lon"] = payload.get("longitude")
    frame["elevation"] = payload.get("elevation")
    frame["wind_speed_10m_ms"] = frame["wind_speed_10m"] / 3.6
    # PBLH is a boundary-layer diagnostic, not a surface value: name it plainly
    # so it is never confused with a 2 m or 10 m quantity.
    frame["boundary_layer_height_m"] = frame["boundary_layer_height"]
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--points", default="all")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    end = args.end_date or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    start, places = args.start_date, list(NCR_POINTS)
    if args.test:
        places, start, end = ["Delhi"], "2024-01-01", "2024-01-02"
    elif args.points != "all":
        places = [p.strip() for p in args.points.split(",") if p.strip()]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames, problems = [], []
    for place in places:
        if place not in NCR_POINTS:
            print(f"Unknown place {place!r}", file=sys.stderr)
            return 2
        lat, lon = NCR_POINTS[place]
        payload = fetch(lat, lon, start, end, args.refresh)
        mismatches = check_units(payload)
        if mismatches:
            problems += [f"{place}: {m}" for m in mismatches]
            log_event("open-meteo-forecast", f"fetch:{place}", "UNIT_MISMATCH", 0, 0, "", "; ".join(mismatches))
            continue
        frame = to_frame(payload, place)
        frames.append(frame)
        log_event("open-meteo-forecast", f"fetch:{place}", "OK", len(frame), 0, f"{lat},{lon} {start}->{end}")
        print(f"{place:<16} {len(frame):>6} hourly rows  PBLH/forecast archive")

    if problems:
        print("\nUNIT MISMATCH — refusing to convert on an unverified unit:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 3
    if not frames:
        print("No data fetched.", file=sys.stderr)
        return 2

    out = pd.concat(frames, ignore_index=True).sort_values(["timestamp", "place"])
    path = OUT_DIR / "forecast_hourly.csv"
    atomic_write(path, out.to_csv(index=False))

    # --- completeness guard -------------------------------------------------
    # The API DECLARES a unit for every requested variable and returns HTTP 200
    # even when the value is entirely absent. Verified: boundary_layer_height is
    # 0/744 non-null for every month before 2024-09-01 and complete from
    # 2024-09-01 onward. Without this check an all-null column looks like a
    # successful download and silently produces an empty feature.
    report = []
    for v in VARIABLES:
        col = "boundary_layer_height_m" if v == "boundary_layer_height" else v
        series = pd.to_numeric(out[col], errors="coerce")
        n, total = int(series.notna().sum()), len(series)
        frac = n / total if total else 0.0
        report.append((v, n, total, frac))
    print(f"\nWrote {path} — {len(out):,} rows, {out.place.nunique()} points, "
          f"{out.timestamp.min()} → {out.timestamp.max()}")
    print("\nPer-variable completeness (a declared unit is NOT a guarantee of data):")
    empty = []
    for v, n, total, frac in report:
        flag = "" if frac > 0 else "   <-- ENTIRELY ABSENT"
        if frac == 0:
            empty.append(v)
        print(f"  {v:<24} {n:>8,}/{total:<8,} ({frac:6.1%}){flag}")
    if empty:
        print(f"\nWARNING: entirely absent for the requested window: {', '.join(empty)}")
        print("PBLH (boundary_layer_height) only exists from 2024-09-01 onward in this")
        print("archive. Request a start date of 2024-09-01 or later to obtain it, or")
        print("source PBLH from ERA5 instead. The nulls are preserved, never filled.")
    pblh = pd.to_numeric(out["boundary_layer_height_m"], errors="coerce")
    if pblh.notna().any():
        print(f"\nPBLH present: min {pblh.min():.0f} m, median {pblh.median():.0f} m, max {pblh.max():.0f} m")
    print("This is PREVIOUS MODEL RUN output (what was forecast at the time), "
          "not reanalysis. Do not merge it with ERA5 archive data as if independent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
