#!/usr/bin/env python3
"""Convert downloaded ERA5 / CAMS NetCDF into station-joined CSV layers.

Raw NetCDF stays immutable; this reads it and writes tidy per-station CSVs that
build_master.py can join. Every value is taken at the station's NEAREST grid
cell -- never interpolated. Bilinear across this terrain would blend cells the
station does not experience, and a reanalysis is already a grid estimate.

Structure and units were read from the ACTUAL files, not assumed:

  ERA5   dims  valid_time x pressure_level x latitude x longitude
         var   `t` (K) at pressure_level 925 / 850, grid 0.25 deg
  CAMS   dims  valid_time x latitude x longitude (0.75 deg, 3-hourly)
         vars  pm2p5, pm10 (kg m**-3), aod550, duaod550 (dimensionless)

Conversions applied, and why:
  * ERA5 T: Kelvin -> Celsius (-273.15), matching the OpenAQ surface layer.
  * CAMS PM: kg/m**3 -> ug/m3 (x 1e9), matching the OpenAQ surface layer. Left in
    kg/m3 these would be ~1e-9 and silently useless beside a ug/m3 PM2.5 column.

    .venv/bin/python scripts/data_collection/ingest_reanalysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

ERA5_RAW = PROJECT_ROOT / "data" / "era5" / "raw"
CAMS_RAW = PROJECT_ROOT / "data" / "cams" / "raw"
ERA5_OUT = PROJECT_ROOT / "data" / "era5" / "processed"
CAMS_OUT = PROJECT_ROOT / "data" / "cams" / "processed"

# Source name -> output column, from the real files.
CAMS_VARS = {
    "pm2p5": "pm25_cams_ugm3",
    "pm10": "pm10_cams_ugm3",
    "aod550": "aod550_cams",
    "duaod550": "dust_aod550_cams",
}
# CAMS species absent from these files (ozone/NO2/CO/SO2 were not returned) are
# NOT silently dropped -- they are reported as missing below.


def station_points() -> pd.DataFrame:
    meta = pd.read_csv(PROJECT_ROOT / "data" / "air_quality" / "station_metadata.csv",
                       low_memory=False, usecols=["station_id", "latitude", "longitude"])
    meta["station_id"] = meta["station_id"].astype(str)
    return meta.drop_duplicates("station_id")


def nearest(lat: np.ndarray, lon: np.ndarray, la: float, lo: float) -> tuple[int, int]:
    return int(np.nanargmin(np.abs(lat - la))), int(np.nanargmin(np.abs(lon - lo)))


def ingest_era5(points: pd.DataFrame) -> str:
    import xarray as xr
    files = sorted(ERA5_RAW.glob("*.nc"))
    if not files:
        return "ERA5: no raw NetCDF found"
    ERA5_OUT.mkdir(parents=True, exist_ok=True)
    frames, read_ok = [], 0

    for f in files:
        try:
            ds = xr.open_dataset(f)
        except Exception as exc:  # noqa: BLE001
            print(f"  {f.name}: unreadable ({type(exc).__name__})", file=sys.stderr)
            continue
        read_ok += 1
        lats, lons = ds["latitude"].values, ds["longitude"].values
        times = pd.to_datetime(ds["valid_time"].values)
        levels = [int(float(v)) for v in ds["pressure_level"].values]
        cells = {(pt.station_id, pt.latitude, pt.longitude):
                 nearest(lats, lons, pt.latitude, pt.longitude) for pt in points.itertuples(index=False)}
        t = ds["t"]  # Kelvin
        ids = [c[0] for c in cells]
        # One row per (station, hour): repeat each station id across the time axis
        # rather than assigning a length-1 column beside a length-N array.
        n_t = len(times)
        base = pd.DataFrame({
            "station_id": np.repeat(ids, n_t),
            "timestamp": np.tile(times.values, len(ids)),
        })
        for lvl, col in ((925, "t925_c"), (850, "t850_c")):
            if lvl not in levels:
                continue
            arr = t.sel(pressure_level=lvl).values - 273.15
            base[col] = [arr[:, cells[(sid, la, lo)][0], cells[(sid, la, lo)][1]]
                         for (sid, la, lo) in cells for _ in range(n_t)]
        frames.append(base)
        ds.close()

    if not frames:
        return "ERA5: files found but none readable"
    out = pd.concat(frames, ignore_index=True)
    cols = [c for c in ("t925_c", "t850_c") if c in out.columns]
    out = out.groupby(["station_id", "timestamp"], as_index=False)[cols].mean()
    out["t925_minus_t850_c"] = out["t925_c"] - out["t850_c"]
    path = ERA5_OUT / "era5_station_hourly.csv"
    out.to_csv(path, index=False)
    return (f"ERA5: {len(out):,} station-hours -> {path.name} "
            f"({read_ok}/{len(files)} files, {out.station_id.nunique()} stations, "
            f"{out.timestamp.min()} -> {out.timestamp.max()})")


def ingest_cams(points: pd.DataFrame) -> str:
    import xarray as xr
    files = sorted(CAMS_RAW.glob("*.nc"))
    if not files:
        return "CAMS: no raw NetCDF found"
    CAMS_OUT.mkdir(parents=True, exist_ok=True)
    frames, seen = [], set()

    for f in files:
        try:
            ds = xr.open_dataset(f)
        except Exception as exc:  # noqa: BLE001
            print(f"  {f.name}: unreadable ({type(exc).__name__})", file=sys.stderr)
            continue
        lats, lons = ds["latitude"].values, ds["longitude"].values
        times = pd.to_datetime(ds["valid_time"].values)
        cells = {(pt.station_id, pt.latitude, pt.longitude):
                 nearest(lats, lons, pt.latitude, pt.longitude) for pt in points.itertuples(index=False)}
        ids = [c[0] for c in cells]
        n_t = len(times)
        base = pd.DataFrame({
            "station_id": np.repeat(ids, n_t),
            "timestamp": np.tile(times.values, len(ids)),
        })
        for src, col in CAMS_VARS.items():
            if src not in ds.data_vars:
                continue
            seen.add(src)
            arr = ds[src].values
            if src in ("pm2p5", "pm10"):
                arr = arr * 1e9  # kg/m3 -> ug/m3
            base[col] = [arr[:, cells[(sid, la, lo)][0], cells[(sid, la, lo)][1]]
                         for (sid, la, lo) in cells for _ in range(n_t)]
        frames.append(base)
        ds.close()

    if not frames:
        return "CAMS: files found but none readable"
    out = pd.concat(frames, ignore_index=True)
    cols = [c for c in CAMS_VARS.values() if c in out.columns]
    out = out.groupby(["station_id", "timestamp"], as_index=False)[cols].mean()
    path = CAMS_OUT / "cams_station_hourly.csv"
    out.to_csv(path, index=False)
    missing = sorted(set(CAMS_VARS) - seen)
    note = f"; NOT returned by the API: {', '.join(missing)}" if missing else ""
    return (f"CAMS: {len(out):,} station-hours -> {path.name} "
            f"({len(files)} files, {out.station_id.nunique()} stations, "
            f"{len(cols)} vars{note})")


def main() -> int:
    points = station_points()
    print(f"station reference points: {len(points)}")
    for msg in (ingest_era5(points), ingest_cams(points)):
        print(f"  {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())