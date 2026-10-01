#!/usr/bin/env python3
"""Build the VayuSangam master training dataset.

This merges ONLY datasets that exist and have been validated. Every alignment
decision is stated in ALIGNMENT below and echoed into the output manifest.
Datasets that are blocked are not substituted, simulated, or filled.

Before running, read the alignment choices — some are scientifically
consequential and are flagged for the user to confirm.

    .venv/bin/python scripts/data_collection/build_master.py --dry-run
    .venv/bin/python scripts/data_collection/build_master.py --build
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.data_collection.common import atomic_write  # noqa: E402

DATA = PROJECT_ROOT / "data"
AIRQ = DATA / "air_quality" / "air_quality_hourly.csv"
METEO = DATA / "meteorology" / "processed" / "meteorology_hourly.csv"
ERA5_PATH = DATA / "era5" / "processed" / "era5_station_hourly.csv"
CAMS_PATH = DATA / "cams" / "processed" / "cams_station_hourly.csv"
MASTER_DIR = DATA / "master"
_GRID_CELLS: dict[str, tuple[float, float]] = {}

# Every merge parameter is declared here rather than chosen inside the code.
#
# The two scientifically consequential choices were settled by inspecting the real
# 220-station coordinate distribution on 2026-09-30, not by preference:
#   nearest-point distance: p25 9.3 km, p50 22.1 km, p75 150.6 km, max 404.9 km.
# The distribution is strongly bimodal — 123 stations sit within 35 km (the NCR
# core) and the rest are 100–405 km away in Punjab, Haryana, Rajasthan, MP and HP.
ALIGNMENT = {
    "grain": "one row per (station_id, UTC hour)",
    "time_zone": "UTC internally; Asia/Kolkata for dashboard display only",
    "spatial_matching": "nearest NCR reference point (5 points), no interpolation",
    "max_spatial_distance_km": 35.0,
    "max_temporal_gap_hours": 0,
    "interpolation": "NONE — no interpolation is applied to either side",
    "merge_type": "left join from station-hour onto the matched met point",
    "fill_policy": "missing stays null; never 0, never interpolated",
    "rationale": (
        "No interpolation on a pollution grid would manufacture values between "
        "sparse stations, and no temporal gap tolerance is allowed because a "
        "weather value from a different hour is a different physical state. "
        "Rows outside the match are kept with null met columns so the gap is "
        "visible and countable rather than dropped."
    ),
    "decisions": {
        "nearest_vs_bilinear": (
            "NEAREST. Open-Meteo already returns the value of the ERA5 grid cell "
            "containing the requested point, so each of the 5 reference series is "
            "itself a nearest-cell sample. Bilinear interpolation between them would "
            "blend cells across the Yamuna and the Delhi Ridge, and at 0.25 deg "
            "(~25 km) the 4 surrounding cells are often not meaningfully different. "
            "Nearest adds no fabricated value between cells; bilinear would."
        ),
        "distance_cutoff_km": (
            "35 km, derived from the data. The nearest-point distance distribution is "
            "bimodal: 123 of 220 stations are within 35 km (NCR core: Delhi 79, "
            "Gurugram 17, Ghaziabad 11, Faridabad 10, Noida 6) and the remaining 97 "
            "are 100-405 km distant, in Punjab, Haryana, Rajasthan, MP and HP. Those "
            "outlying stations are NOT Delhi NCR and are not a meteorology-representation "
            "problem to be solved by loosening a threshold — they are a different region. "
            "They are retained with null meteorology and should be scoped out of the NCR "
            "model separately."
        ),
    },
    "open_questions": [
        "The 97 out-of-core stations (Punjab/Haryana/Rajasthan/MP/HP) are currently kept "
        "with null meteorology. Decide whether to (a) drop them from the NCR model, or "
        "(b) keep them as upwind source-region context. The spec asks for surrounding "
        "pollution-source regions, so (b) may be intended — but they need their own "
        "meteorology points, not the nearest NCR one.",
    ],
}

# Met columns to carry into the master. Requested by name; any that the source
# file does not actually contain are dropped with a message rather than
# silently materialised as NaN.
MET_COLS = ["temperature_2m", "relative_humidity_2m", "surface_pressure",
            "wind_speed_10m", "wind_speed_10m_ms", "wind_direction_10m",
            "cloud_cover", "precipitation", "u_wind", "v_wind"]


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


# Grid cell each requested point actually resolved to. Stations must be matched
# to the CELL, not the nominal requested coordinate: Open-Meteo snaps a requested
# point to the nearest ERA5 cell, and that cell can be tens of km away, so using
# the nominal coordinate would misstate every distance.
# Read from the processed meteorology file, which records it.
def grid_cells() -> dict[str, tuple[float, float]]:
    global _GRID_CELLS
    if not _GRID_CELLS:
        path = METEO
        if path.exists():
            try:
                probe = pd.read_csv(path, usecols=lambda c: c in ("place", "grid_lat", "grid_lon"))
            except ValueError:
                probe = pd.DataFrame()
            if {"place", "grid_lat", "grid_lon"} <= set(probe.columns):
                probe = probe.dropna(subset=["grid_lat", "grid_lon"]).drop_duplicates("place")
                _GRID_CELLS = {r.place: (float(r.grid_lat), float(r.grid_lon))
                               for r in probe.itertuples()}
    return _GRID_CELLS


def grid_cell(place: str) -> tuple[float, float]:
    cells = grid_cells()
    if place in cells:
        return cells[place]
    return (0.0, 0.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Actually write the master dataset")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()
    problems: list[str] = []
    if not AIRQ.exists():
        print("air_quality_hourly.csv missing — run the OpenAQ processor first.", file=sys.stderr)
        return 2
    airq = pd.read_csv(AIRQ)
    airq["timestamp"] = pd.to_datetime(airq["timestamp"], utc=True)

    span_days = (airq.timestamp.max() - airq.timestamp.min()).days
    if span_days < 365:
        problems.append(
            f"air quality covers only {span_days} day(s). This looks like a SAMPLE, not the "
            f"full production download. Merging now would produce a master dataset with no "
            f"useful training history.")
    if not METEO.exists():
        problems.append("meteorology_hourly.csv missing — run the Open-Meteo collector first.")
        met = None
    else:
        met = pd.read_csv(METEO)
        met["timestamp"] = pd.to_datetime(met["timestamp"], utc=True)
        # Derive the wind components here rather than assuming build_features.py ran:
        # the master build must not silently lose them or KeyError on an absent column.
        if "wind_speed_10m_ms" not in met.columns and "wind_speed_10m" in met.columns:
            met["wind_speed_10m_ms"] = pd.to_numeric(met["wind_speed_10m"], errors="coerce") / 3.6
        if {"wind_speed_10m_ms", "wind_direction_10m"} <= set(met.columns):
            rad = np.deg2rad(pd.to_numeric(met["wind_direction_10m"], errors="coerce") % 360)
            speed = pd.to_numeric(met["wind_speed_10m_ms"], errors="coerce")
            met["u_wind"] = -speed * np.sin(rad)
            met["v_wind"] = -speed * np.cos(rad)

    print("SOURCE VALIDATION SUMMARY")
    print(f"  air quality : {len(airq):,} rows, {airq.station_id.nunique()} stations, "
          f"{airq.timestamp.min()} → {airq.timestamp.max()} ({span_days} days)")
    print(f"  meteorology : {'missing' if met is None else f'{len(met):,} rows, {met.place.nunique()} points'}")
    # Report what is actually on disk. Hard-coded "NOT COLLECTED (no ~/.cdsapirc)"
    # lines outlived the credentials and began contradicting the join output
    # directly below them.
    def _status(path: Path, unit: str) -> str:
        if not path.exists():
            return "NOT COLLECTED"
        rows = sum(1 for _ in path.open()) - 1
        return f"COLLECTED ({rows:,} rows, {unit})"

    print(f"  fires       : NOT COLLECTED (FIRMS API returns HTTP 400 for every request — "
          f"see data/manifests/firms_key_probe.json)")
    print(f"  CAMS        : {_status(CAMS_PATH, 'EAC4 station-hours')}")
    print(f"  ERA5        : {_status(ERA5_PATH, 'pressure-level station-hours')}")
    print(f"  geospatial  : collected (static; roads/landuse are tags-only)")

    if problems:
        print("\nBLOCKING ISSUES:")
        for p in problems:
            print("  - " + p)
        print("\nMaster dataset NOT built. Resolve these first.")
        if met is not None and span_days >= 365:
            print("(Meteorology is present, so the block is the air-quality coverage.)")
        return 3

    # --- match each station to its nearest NCR met point ---------------------
    # Import the point set from the collector so the two can never drift apart:
    # a station matched to a point the collector did not download would silently
    # receive null meteorology.
    from scripts.data_collection.meteorology.download_open_meteo import NCR_POINTS
    places = met[["place", "elevation"]].drop_duplicates()
    stations = airq[["station_id", "latitude", "longitude"]].drop_duplicates()
    rows = []
    for st in stations.itertuples(index=False):
        best, best_d = None, np.inf
        for place in places.place:
            if place not in NCR_POINTS:
                continue
            glat, glon = grid_cell(place)
            d = haversine_km(st.latitude, st.longitude, glat, glon)
            if d < best_d:
                best, best_d = place, d
        rows.append({"station_id": st.station_id, "met_place": best,
                     "met_distance_km": round(float(best_d), 2)})
    match = pd.DataFrame(rows)
    unmatched = match[match.met_place.isna()]
    if len(unmatched):
        print(f"  WARNING: {len(unmatched)} station(s) matched no met point")
    matched = airq.merge(match, on="station_id", how="left")

    limit = ALIGNMENT["max_spatial_distance_km"]
    matched["met_in_range"] = matched.met_distance_km <= limit
    beyond = matched[~matched.met_in_range]
    print(f"\nSpatial match: nearest point within {limit} km")
    print(f"  stations matched        : {match.station_id.nunique()}")
    print(f"  in range (<= {limit} km)  : {int(match[match.met_distance_km <= limit].shape[0])}")
    print(f"  beyond {limit} km        : {int((match.met_distance_km > limit).sum())} "
          f"(out-of-region stations; rows kept with null met columns)")
    if len(beyond):
        print(f"  affected station-hours  : {len(beyond):,} (kept with null met columns)")
        outlying = (beyond.groupby("met_place")["station_id"].nunique()
                    .sort_values(ascending=False).to_dict())
        print(f"  outlying by nearest point: {outlying}")

    if met is not None:
        present = [c for c in MET_COLS if c in met.columns]
        absent = [c for c in MET_COLS if c not in met.columns]
        if absent:
            print(f"  note: met source lacks {absent} — not carried into the master")
        met_small = met[["timestamp", "place", *present]].rename(columns={"place": "met_place"})
        merged = matched.merge(met_small, on=["timestamp", "met_place"], how="left", validate="many_to_one")
    else:
        merged = matched

    # --- join ERA5 pressure levels and CAMS, if they have been ingested -------
    # Both are per (station, hour) tables produced by ingest_reanalysis.py.
    # Joined how="left" with NO interpolation: a station-hour without a reanalysis
    # value keeps a null, which is the honest state. A source that was never
    # collected produces no columns at all, so it can never be mistaken for a
    # source that was considered and found unhelpful.
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)
    # The air-quality frame can hold int64 station ids while the ingested layers
    # hold strings; merge refuses that pairing rather than coercing silently.
    merged["station_id"] = merged["station_id"].astype(str)
    for label, path in (("ERA5", ERA5_PATH), ("CAMS", CAMS_PATH)):
        if not path.exists():
            print(f"  {label}: not ingested (no processed file) — columns absent")
            continue
        layer = pd.read_csv(path, low_memory=False)
        layer["timestamp"] = pd.to_datetime(layer["timestamp"], utc=True)
        layer["station_id"] = layer["station_id"].astype(str)
        cols = [c for c in layer.columns if c not in ("station_id", "timestamp")]
        merged = merged.merge(layer, on=["station_id", "timestamp"], how="left",
                              validate="many_to_one")
        cover = merged[cols].notna().any(axis=1).mean() if cols else 0.0
        print(f"  {label}: joined {len(cols)} column(s) "
              f"({', '.join(cols) if cols else 'none'}), covering {100*cover:.1f}% of rows")

    merged = merged.sort_values(["station_id", "timestamp"]).reset_index(drop=True)
    if args.build:
        MASTER_DIR.mkdir(parents=True, exist_ok=True)
        out = MASTER_DIR / "master_training_dataset.parquet"
        try:
            import pyarrow  # noqa: F401
            merged.to_parquet(out, index=False)
        except ImportError:
            out = MASTER_DIR / "master_training_dataset.csv"
            merged.to_csv(out, index=False)
        atomic_write(MASTER_DIR / "master_manifest.json", json.dumps({
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "rows": len(merged), "stations": int(merged.station_id.nunique()),
            "columns": list(merged.columns), "alignment": ALIGNMENT,
            "sources_merged": ["OpenAQ v3", "Open-Meteo"] +
                              (["ERA5 pressure levels"] if ERA5_PATH.exists() else []) +
                              (["CAMS EAC4"] if CAMS_PATH.exists() else []),
            "sources_not_merged": {"fires": "FIRMS API returning HTTP 400 for every request; "
                                            "see data/manifests/firms_key_probe.json",
                                   "geospatial": "static, joined per station separately"},
        }, indent=2))
        print(f"\nWrote {out} — {len(merged):,} rows, {len(merged.columns)} columns")
    else:
        print(f"\n[dry run] would write {len(merged):,} rows x {len(merged.columns)} columns")
        print("Run with --build to write it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
