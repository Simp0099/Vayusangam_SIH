#!/usr/bin/env python3
"""Feature engineering for the VayuSangam coupled model.

Builds features from whatever processed datasets actually exist. Datasets that
are blocked or not yet collected produce NO columns and NO synthetic stand-ins —
they are reported as absent.

    .venv/bin/python scripts/data_collection/build_features.py

All features are PREDICTIVE, not causal. Nothing here asserts a physical cause.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DATA = PROJECT_ROOT / "data"
AIRQ = DATA / "air_quality"
METEO = DATA / "meteorology" / "processed"

# PM2.5 lags in hours. 1/3/6/12/24 h give the model persistence, diurnal and
# day-ahead signal; 72 h is the forecast horizon itself and is built separately
# as the target, never as a lag of the current hour.
PM25_LAGS = [1, 3, 6, 12, 24]

# Floors below which the air-quality feature build is refused. A 72-hour test
# download produces a frame that merges and writes without error while almost
# every lag is null — it reads as a finished feature set and is not one. The
# floor is deliberately well under the real 2-year span so an unusually thin
# but genuine download still builds.
MIN_SPAN_DAYS = 180
MIN_AIRQ_ROWS = 50_000
FORECAST_HORIZON_HOURS = 72


def load_air_quality() -> tuple[pd.DataFrame | None, str]:
    path = AIRQ / "air_quality_hourly.csv"
    if not path.exists():
        return None, "air_quality_hourly.csv not found"
    frame = pd.read_csv(path)
    if frame.empty or "PM2.5" not in frame:
        return None, "air_quality_hourly.csv is empty or has no PM2.5 column"
    return frame, f"{len(frame):,} rows, {frame.station_id.nunique()} station(s)"


def load_meteorology() -> tuple[pd.DataFrame | None, str]:
    path = METEO / "meteorology_hourly.csv"
    if not path.exists():
        return None, "meteorology_hourly.csv not found (run the Open-Meteo collector)"
    frame = pd.read_csv(path)
    if frame.empty:
        return None, "meteorology_hourly.csv is empty"
    return frame, f"{len(frame):,} rows, {frame.place.nunique()} point(s)"


def time_features(timestamp: pd.Series) -> pd.DataFrame:
    """UTC calendar features. hour/month are cyclic-encoded to avoid a hard
    boundary between 23:00 and 00:00 being read as a large jump."""
    ts = pd.to_datetime(timestamp, utc=True)
    hour = ts.dt.hour
    day_of_year = ts.dt.dayofyear
    return pd.DataFrame({
        "hour": hour.astype("float32"),
        "hour_sin": np.sin(2 * np.pi * hour / 24).astype("float32"),
        "hour_cos": np.cos(2 * np.pi * hour / 24).astype("float32"),
        "day_of_week": ts.dt.dayofweek.astype("float32"),
        "month": ts.dt.month.astype("float32"),
        "month_sin": np.sin(2 * np.pi * ts.dt.month / 12).astype("float32"),
        "month_cos": np.cos(2 * np.pi * ts.dt.month / 12).astype("float32"),
        "day_of_year": day_of_year.astype("float32"),
        "doy_sin": np.sin(2 * np.pi * day_of_year / 365.25).astype("float32"),
        "doy_cos": np.cos(2 * np.pi * day_of_year / 365.25).astype("float32"),
    }, index=timestamp.index)


def wind_components(frame: pd.DataFrame) -> pd.DataFrame:
    """u/v from speed + meteorological direction.

    Meteorological convention: wind_direction is the direction the wind blows
    FROM. u (eastward) = -speed * sin(dir), v (northward) = -speed * cos(dir).
    The minus signs are the classic silent bug, so they are asserted in tests.
    """
    speed = pd.to_numeric(frame.get("wind_speed_10m_ms"), errors="coerce")
    direction = pd.to_numeric(frame.get("wind_direction_10m"), errors="coerce") % 360
    if speed is None or direction is None:
        return pd.DataFrame(index=frame.index)
    rad = np.deg2rad(direction)
    return pd.DataFrame({
        "wind_speed_mps": speed.astype("float32"),
        "u_wind": (-speed * np.sin(rad)).astype("float32"),
        "v_wind": (-speed * np.cos(rad)).astype("float32"),
    }, index=frame.index)


def add_pm25_lags(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Per-station PM2.5 lags. NaN propagates: a lag of a missing hour is missing,
    never back-filled from a neighbouring station or a previous day."""
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out = out.sort_values(["station_id", "timestamp"])
    added = 0
    for lag in PM25_LAGS:
        col = f"PM2.5_t-{lag}h"
        out[col] = out.groupby("station_id")["PM2.5"].shift(lag).astype("float32")
        if col not in frame.columns:
            added += 1
    out["target_PM2.5_t+72h"] = out.groupby("station_id")["PM2.5"].shift(-FORECAST_HORIZON_HOURS).astype("float32")
    return out, added


def main() -> int:
    out_dir = DATA / "features"
    out_dir.mkdir(parents=True, exist_ok=True)
    status: dict[str, str] = {}

    airq, aq_note = load_air_quality()
    met, met_note = load_meteorology()
    status["air_quality"] = aq_note
    status["meteorology"] = met_note

    if airq is not None:
        # Guard against sample-sized inputs. A leftover 72-hour test download
        # merges happily into a plausible-looking feature set whose lags are
        # almost entirely null — the output looks finished and is not.
        airq = airq.copy()
        airq["timestamp"] = pd.to_datetime(airq["timestamp"], utc=True)
        span_days = (airq.timestamp.max() - airq.timestamp.min()).days
        if span_days < MIN_SPAN_DAYS or len(airq) < MIN_AIRQ_ROWS:
            print(f"  air_quality_features  SKIPPED — input spans {span_days} day(s) "
                  f"({len(airq):,} rows), below the {MIN_SPAN_DAYS}-day / "
                  f"{MIN_AIRQ_ROWS:,}-row floor for a real training set.")
            print("                      Run the full OpenAQ download and "
                  "process_openaq.py before building features.")
            status["air_quality_features"] = "SKIPPED: sample-sized air quality input"
            write_stale_marker(out_dir, f"input spans {span_days} day(s) / "
                                        f"{len(airq):,} rows, under the "
                                        f"{MIN_SPAN_DAYS}-day / {MIN_AIRQ_ROWS:,}-row floor")
        else:
            featured, added = add_pm25_lags(airq)
            featured = pd.concat([featured, time_features(featured["timestamp"])], axis=1)
            path = out_dir / "air_quality_features.parquet" if _has_parquet() else out_dir / "air_quality_features.csv"
            _write(featured, path)
            status["air_quality_features"] = (
                f"{len(featured):,} rows -> {path.name} ({added} PM2.5 lag columns + {FORECAST_HORIZON_HOURS}h target)")

    if met is not None:
        met = met.copy()
        met["timestamp"] = pd.to_datetime(met["timestamp"], utc=True)
        met = pd.concat([met, time_features(met["timestamp"]), wind_components(met)], axis=1)
        path = out_dir / "meteorology_features.parquet" if _has_parquet() else out_dir / "meteorology_features.csv"
        _write(met, path)
        status["meteorology_features"] = f"{len(met):,} rows -> {path.name}"

    # Datasets that are blocked are named explicitly, never silently omitted.
    for name, reason in [
        ("fire_features", "BLOCKED: no FIRMS_MAP_KEY — no fire data collected"),
        ("cams_features", "BLOCKED: no ~/.cdsapirc — no CAMS data collected"),
        ("inversion_features", "BLOCKED: needs ERA5 T925/T850/PBLH — no ~/.cdsapirc"),
        ("geospatial_features", "available: static; see data/geospatial/DATA_DICTIONARY.md"),
    ]:
        status.setdefault(name, reason)

    for key, value in status.items():
        print(f"  {key:<22} {value}")
    print(f"\nFeatures are predictive, not causal. No blocked dataset was substituted "
          f"or simulated.")
    return 0


def write_stale_marker(out_dir: Path, reason: str) -> None:
    """Leave an on-disk marker naming any skipped artifact, so a consumer that
    finds an older build knows it is superseded rather than current."""
    skipped = out_dir / "air_quality_features.csv"
    if not skipped.exists():
        return
    (out_dir / "STALE_air_quality_features.json").write_text(json.dumps({
        "artifact": "data/features/air_quality_features.csv",
        "status": "STALE_SAMPLE",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "why": [reason],
        "do_not": ["Do not load this into a training set or the frontend."],
        "remedy": ["run process_openaq.py, then build_features.py again"],
    }, indent=2), encoding="utf-8")


def _has_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def _write(frame: pd.DataFrame, path: Path) -> None:
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


if __name__ == "__main__":
    raise SystemExit(main())
