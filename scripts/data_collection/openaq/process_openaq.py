#!/usr/bin/env python3
"""Transform immutable OpenAQ v3 raw snapshots into station-hour tables."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

try:  # Support both direct script execution and imports from tests/tools.
    from .common import DATA_DIR, EXPECTED_COLUMNS, FINAL_UNITS, RAW_DIR, VARIABLES, normalize_value, timestamp_utc
except ImportError:
    from common import DATA_DIR, EXPECTED_COLUMNS, FINAL_UNITS, RAW_DIR, VARIABLES, normalize_value, timestamp_utc


def boolish(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def atomic_csv(frame: pd.DataFrame, path) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temp, index=False, na_rep="NaN")
    temp.replace(path)


def main() -> int:
    metadata_path = DATA_DIR / "station_metadata.csv"
    sensors_path = DATA_DIR / "sensor_metadata.csv"
    manifest_path = DATA_DIR / "collection_manifest.json"
    if not all(x.exists() for x in (metadata_path, sensors_path, manifest_path)):
        print("Missing discovery outputs. Run download_openaq.py after setting OPENAQ_API_KEY.", file=sys.stderr)
        return 2
    metadata = pd.read_csv(metadata_path)
    sensors = pd.read_csv(sensors_path).fillna({"original_unit": ""})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    start = date.fromisoformat(manifest["requested_start_date"])
    end = date.fromisoformat(manifest["requested_end_date"])
    downloaded_ids = {str(x) for x in manifest.get("downloaded_station_ids", [])}
    # An in-progress run has no completed station list yet — the manifest only gets
    # one on success. Derive coverage from the raw cache instead, which is the
    # authoritative record of what is actually on disk. Without this the sensor
    # filter below matches nothing and the script writes an EMPTY dataset over the
    # existing CSV, reporting success while destroying the only processed output.
    if not downloaded_ids:
        if manifest.get("status") == "complete":
            print("Manifest says complete but lists no downloaded stations — refusing to "
                  "process. Re-run the collector.", file=sys.stderr)
            return 2
        present = set()
        for path in (RAW_DIR / "hours").glob("*.json"):
            match = re.search(r"sensor-(\d+)-", path.name)
            if match:
                present.add(match.group(1))
        selected = sensors[sensors["selected_for_variable"].map(boolish)]
        derived = {
            str(row.station_id) for row in selected.itertuples(index=False)
            if str(row.sensor_id) in present
        }
        print(f"Manifest lists 0 downloaded stations (status={manifest.get('status')}); "
              f"derived {len(derived)} station(s) from {len(present)} sensor(s) in the raw cache.")
        downloaded_ids = derived
    sensors["station_id"] = sensors["station_id"].astype(str)
    sensors["sensor_id"] = sensors["sensor_id"].astype(str)
    sensors["selected_for_variable"] = sensors["selected_for_variable"].map(boolish)
    sensor_map = {row.sensor_id: row for row in sensors.itertuples(index=False) if row.selected_for_variable and row.station_id in downloaded_ids}
    station_map = metadata.assign(station_id=metadata.station_id.astype(str)).set_index("station_id")
    raw_rows: list[dict] = []
    duplicate_counts: Counter = Counter()
    invalid_counts: Counter = Counter()
    for path in sorted((RAW_DIR / "hours").glob("*.json")):
        match = re.search(r"sensor-(\d+)-", path.name)
        if not match or match.group(1) not in sensor_map:
            continue
        sensor = sensor_map[match.group(1)]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"Skipping unreadable raw response: {path}", file=sys.stderr)
            continue
        for item in payload.get("results") or []:
            timestamp = timestamp_utc(item)
            if not timestamp:
                invalid_counts[(sensor.station_id, sensor.parameter)] += 1
                continue
            ts = pd.Timestamp(timestamp)
            if ts < pd.Timestamp(start, tz="UTC") or ts >= pd.Timestamp(end + timedelta(days=1), tz="UTC"):
                continue
            value, final_unit, issue = normalize_value(sensor.parameter, sensor.original_unit, item.get("value"))
            if issue:
                invalid_counts[(sensor.station_id, sensor.parameter)] += 1
            raw_rows.append({"station_id": sensor.station_id, "timestamp": timestamp,
                             "variable": sensor.parameter, "sensor_id": sensor.sensor_id,
                             "value": value, "unit": final_unit})
    long = pd.DataFrame(raw_rows, columns=["station_id", "timestamp", "variable", "sensor_id", "value", "unit"])
    if not long.empty:
        duplicate_counts.update(long.groupby(["station_id", "timestamp", "variable"]).size().sub(1).clip(lower=0).to_dict())
        # Duplicate query-boundary hours and repeated page rows are counted, then removed.
        long = long.drop_duplicates(["station_id", "timestamp", "variable", "sensor_id"], keep="first")
        long = long.groupby(["station_id", "timestamp", "variable"], as_index=False, dropna=False).agg(value=("value", "mean"))
        wide = long.pivot(index=["station_id", "timestamp"], columns="variable", values="value").reset_index()
        wide.columns.name = None
    else:
        wide = pd.DataFrame(columns=["station_id", "timestamp", *VARIABLES])
    wide["station_id"] = wide.get("station_id", pd.Series(dtype=str)).astype(str)
    # Include explicit hourly nulls between the requested bounds for each sampled/downloaded station.
    grids = []
    for station_id in sorted(downloaded_ids):
        hours = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end + timedelta(days=1), tz="UTC"), freq="h", inclusive="left")
        grids.append(pd.DataFrame({"station_id": station_id, "timestamp": hours.strftime("%Y-%m-%dT%H:%M:%SZ")}))
    grid = pd.concat(grids, ignore_index=True) if grids else pd.DataFrame(columns=["station_id", "timestamp"])
    if not wide.empty:
        grid = grid.merge(wide, on=["station_id", "timestamp"], how="left", validate="one_to_one")
    for variable in VARIABLES:
        if variable not in grid:
            grid[variable] = np.nan
    grid = grid.merge(metadata.assign(station_id=metadata.station_id.astype(str)), on="station_id", how="left", suffixes=("", "_meta"), validate="many_to_one")
    # Keep only the stable, user-facing output schema.
    grid = grid.rename(columns={"provider": "source_provider"})
    for col in EXPECTED_COLUMNS:
        if col not in grid:
            grid[col] = np.nan
    output = grid[EXPECTED_COLUMNS].sort_values(["station_id", "timestamp"]).reset_index(drop=True)
    # Never overwrite a populated dataset with an empty one. A filter that matches
    # nothing is a bug, and it is unrecoverable if it has already written.
    existing = DATA_DIR / "air_quality_hourly.csv"
    if output.empty and existing.exists() and existing.stat().st_size > 0:
        print(f"Refusing to write an EMPTY air_quality_hourly.csv over the existing "
              f"{existing.stat().st_size:,}-byte file. Check the sensor filter and the "
              f"raw cache.", file=sys.stderr)
        return 2
    atomic_csv(output, DATA_DIR / "air_quality_hourly.csv")
    hours_expected = max(1, len(pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end + timedelta(days=1), tz="UTC"), freq="h", inclusive="left")))
    quality = []
    min_observations = min(int(__import__("os").getenv("OPENAQ_MIN_PM25_HOURS", "720")), hours_expected)
    min_fraction = float(__import__("os").getenv("OPENAQ_MIN_PM25_COVERAGE", "0.10"))
    for station_id in sorted(downloaded_ids):
        station = station_map.loc[station_id] if station_id in station_map.index else pd.Series(dtype=object)
        station_rows = output[output.station_id.astype(str) == station_id]
        station_pm = int(station_rows["PM2.5"].notna().sum())
        station_fraction = station_pm / max(len(station_rows), 1)
        insufficient = station_pm < min_observations or station_fraction < min_fraction
        for variable in VARIABLES:
            observed = int(station_rows[variable].notna().sum())
            invalid = int(invalid_counts[(station_id, variable)])
            dups = sum(v for (sid, _ts, var), v in duplicate_counts.items() if sid == station_id and var == variable)
            values = station_rows.loc[station_rows[variable].notna(), ["timestamp"]]
            quality.append({"record_type": "station_variable", "station_id": station_id,
                            "station_name": station.get("station_name"), "variable": variable,
                            "missing_percentage": round(100 * (1 - observed / max(len(station_rows), 1)), 3),
                            "observation_count": observed, "expected_observations": len(station_rows),
                            "date_coverage_start_utc": values.timestamp.min() if not values.empty else "",
                            "date_coverage_end_utc": values.timestamp.max() if not values.empty else "",
                            "duplicate_timestamps": dups, "invalid_values": invalid,
                            "insufficient_coverage": insufficient if variable == "PM2.5" else ""})
        overall_observed = int(station_rows[VARIABLES].notna().any(axis=1).sum())
        quality.append({"record_type": "station", "station_id": station_id, "station_name": station.get("station_name"),
                        "variable": "ALL", "missing_percentage": round(100 * (1-overall_observed/max(len(station_rows),1)), 3),
                        "observation_count": overall_observed, "expected_observations": len(station_rows),
                        "date_coverage_start_utc": station_rows.loc[station_rows[VARIABLES].notna().any(axis=1), "timestamp"].min() if overall_observed else "",
                        "date_coverage_end_utc": station_rows.loc[station_rows[VARIABLES].notna().any(axis=1), "timestamp"].max() if overall_observed else "",
                        "duplicate_timestamps": sum(v for (sid, _ts, _var), v in duplicate_counts.items() if sid == station_id),
                        "invalid_values": sum(v for (sid, _var), v in invalid_counts.items() if sid == station_id),
                        "insufficient_coverage": insufficient})
    for variable in VARIABLES:
        series = output[variable] if variable in output else pd.Series(dtype=float)
        obs = int(series.notna().sum())
        expected = len(series)
        quality.append({"record_type": "variable", "station_id": "", "station_name": "", "variable": variable,
                        "missing_percentage": round(100 * (1-obs/max(expected,1)), 3),
                        "observation_count": obs, "expected_observations": expected,
                        "date_coverage_start_utc": output.loc[output[variable].notna(), "timestamp"].min() if obs else "",
                        "date_coverage_end_utc": output.loc[output[variable].notna(), "timestamp"].max() if obs else "",
                        "duplicate_timestamps": sum(v for (_sid, _ts, var), v in duplicate_counts.items() if var == variable),
                        "invalid_values": sum(v for (_sid, var), v in invalid_counts.items() if var == variable),
                        "insufficient_coverage": ""})
    atomic_csv(pd.DataFrame(quality), DATA_DIR / "data_quality_report.csv")

    completeness = []
    for station_id, rows in output.groupby(output.station_id.astype(str), sort=False):
        station_name = rows.station_name.iloc[0]
        fraction = rows["PM2.5"].notna().mean() if len(rows) else 0
        completeness.append((station_name, int(rows["PM2.5"].notna().sum()), round(100*fraction, 1)))
    completeness.sort(key=lambda x: (-x[2], -x[1], str(x[0])))
    availability = pd.read_csv(DATA_DIR / "station_availability.csv") if (DATA_DIR / "station_availability.csv").exists() else pd.DataFrame()
    print(f"Stations discovered: {len(metadata)}")
    print(f"Stations selected: {len(downloaded_ids)}")
    print(f"Date range: {start} → {end}")
    print(f"Total hourly rows: {len(output)}")
    print("Variables by stations with normalized observations:")
    for variable in VARIABLES:
        station_count = output.loc[output[variable].notna(), "station_id"].nunique() if len(output) else 0
        print(f"  {variable}: {station_count}")
    print("Top stations by PM2.5 completeness (station, observed hours, percent):")
    for row in completeness[:10]: print(f"  {row[0]} | {row[1]} | {row[2]}%")
    if not availability.empty:
        missing_var = [v for v in VARIABLES if not output[v].notna().any()]
        if missing_var: print("No normalized observations for: " + ", ".join(missing_var))
    print(f"Final units: {json.dumps(FINAL_UNITS, ensure_ascii=False)}")
    print("Missing values are written as NaN; unsupported units remain missing and are counted as invalid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
