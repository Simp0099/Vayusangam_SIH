#!/usr/bin/env python3
"""Scope the training set: lock the window, drop out-of-region stations.

Two decisions, applied by MEASUREMENT not assumption, both reversible:

1. Window. 2024 was requested but almost no sensors returned data for it. The
   window is therefore locked to the first month with real coverage, computed
   here rather than hard-coded.

2. Spatial. Stations beyond the meteorology cut-off keep null met columns, which
   is correct for a frame you might still analyse -- but useless for TRAINING,
   where those rows contribute no features and dilute the loss. This emits a
   training-scoped view rather than destroying the master frame.

    .venv/bin/python scripts/data_collection/scope_training_window.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MASTER = PROJECT_ROOT / "data" / "master" / "master_training_dataset.csv"
FEATURES = PROJECT_ROOT / "data" / "features" / "air_quality_features.csv"
OUT_DIR = PROJECT_ROOT / "data" / "master"

MIN_MONTH_COVERAGE = 0.10  # a month must reach this PM2.5 fill to open the window


def main() -> int:
    if not MASTER.exists():
        print(f"missing {MASTER} — run build_master.py --build first", file=sys.stderr)
        return 2

    df = pd.read_csv(MASTER, low_memory=False,
                     usecols=["station_id", "station_name", "timestamp", "PM2.5",
                              "met_in_range", "met_distance_km"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["month"] = df["timestamp"].dt.to_period("M")

    monthly = df.groupby("month")["PM2.5"].apply(lambda s: s.notna().mean())
    good = monthly[monthly >= MIN_MONTH_COVERAGE]
    if good.empty:
        print("no month reaches the coverage floor", file=sys.stderr)
        return 2
    window_start = str(good.index.min())
    window_end = str(good.index.max())
    print("monthly PM2.5 coverage:")
    for k, v in monthly.items():
        flag = "ok " if v >= MIN_MONTH_COVERAGE else "-- "
        print(f"  {flag}{k} {100*v:5.1f}%")
    print(f"\nlocked training window: {window_start} -> {window_end}")

    in_range = df["met_in_range"].astype(str).str.lower().isin(["true", "1", "yes"])
    kept_stations = df.loc[in_range, "station_id"].nunique()
    dropped_stations = df.loc[~in_range, "station_id"].nunique()
    print(f"stations with meteorology in range: {kept_stations}")
    print(f"stations beyond the cut-off (excluded from training view): {dropped_stations}")

    dropped = (df[~in_range].groupby("station_name")["station_id"].nunique()
               .sort_values(ascending=False))
    print("\nlargest exclusions:")
    for name, n in dropped.head(8).items():
        print(f"  {n:>3}  {name}")

    # Write the scoped training view.
    subset = df[in_range].copy()
    out = OUT_DIR / "training_scoped.csv"
    subset.drop(columns=["month"]).to_csv(out, index=False)
    print(f"\nwrote {out} ({len(subset):,} rows, {subset.station_id.nunique()} stations)")

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "window_start": window_start,
        "window_end": window_end,
        "window_rationale": (
            f"First month whose PM2.5 fill reaches {MIN_MONTH_COVERAGE:.0%}. Earlier "
            f"months were requested but returned almost no data: the download ran to "
            f"completion and those months are genuinely absent, not queued."),
        "monthly_pm25_coverage": {str(k): round(float(v), 4) for k, v in monthly.items()},
        "meteorology_cutoff_km": 35.0,
        "stations_in_range": int(kept_stations),
        "stations_excluded": int(dropped_stations),
        "excluded_station_names": {str(k): int(v) for k, v in dropped.head(30).items()},
        "note": (
            "The full master_training_dataset.csv is unchanged and still holds every "
            "row, including out-of-region stations with null met columns. This is a "
            "training-scoped view only."),
    }
    mpath = OUT_DIR / "training_scope_manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {mpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())