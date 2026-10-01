#!/usr/bin/env python3
"""Enrich station_availability.csv with the required history columns.

`historical_start` / `historical_end` are the earliest and latest timestamps
declared by the station's *sensors* in `sensor_metadata.csv` — that is real
source data, so it is used directly.

`observation_count_if_available` is filled only when a count genuinely exists in
the source. OpenAQ v3 exposes no per-station observation count, so it is written
as `UNKNOWN` rather than estimated from the date span. An estimate would be a
fabricated number presented as a source value.

Read-only with respect to data/air_quality/raw/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AQ_DIR = PROJECT_ROOT / "data" / "air_quality"
COLUMNS = ["historical_start", "historical_end", "observation_count_if_available"]


def main() -> int:
    avail_path = AQ_DIR / "station_availability.csv"
    sensors_path = AQ_DIR / "sensor_metadata.csv"
    if not avail_path.exists():
        print("station_availability.csv missing; run download_openaq.py first.", file=sys.stderr)
        return 2
    availability = pd.read_csv(avail_path)
    if not sensors_path.exists():
        print("sensor_metadata.csv missing; run download_openaq.py first.", file=sys.stderr)
        return 2
    sensors = pd.read_csv(sensors_path)

    # Station history spans every sensor at that station, not just PM2.5.
    first = pd.to_datetime(sensors.datetime_first_utc, utc=True, errors="coerce")
    last = pd.to_datetime(sensors.datetime_last_utc, utc=True, errors="coerce")
    sensors = sensors.assign(_first=first, _last=last)
    grouped = sensors.groupby(sensors.station_id.astype(str)).agg(
        historical_start=("_first", "min"), historical_end=("_last", "max"))

    availability["station_id"] = availability.station_id.astype(str)
    # Re-running must be safe: a previous run already wrote these columns, and
    # merging onto them produces historical_start_x/_y, so the KeyError below
    # fired on every re-run after the first.
    for col in ("historical_start", "historical_end"):
        if col in availability.columns:
            availability = availability.drop(columns=[col])
    availability = availability.merge(grouped, left_on="station_id", right_index=True, how="left")
    for col in ("historical_start", "historical_end"):
        availability[col] = pd.to_datetime(availability[col], utc=True, errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # v3 provides no per-station record count. Do not derive one from the span.
    availability["observation_count_if_available"] = "UNKNOWN (not exposed by OpenAQ v3)"

    for col in COLUMNS:
        if col not in availability.columns:
            availability[col] = ""
    ordered = list(pd.read_csv(avail_path, nrows=0).columns) + [c for c in COLUMNS if c not in pd.read_csv(avail_path, nrows=0).columns]
    availability = availability[ordered]

    temp = avail_path.with_name(f".{avail_path.name}.tmp")
    availability.to_csv(temp, index=False)
    temp.replace(avail_path)

    filled = int(availability.historical_start.notna().sum())
    print(f"Updated {avail_path.name}: {len(availability)} stations, "
          f"history populated for {filled} ({filled / max(len(availability), 1):.1%})")
    print("observation_count_if_available set to an explicit UNKNOWN marker, not an estimate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
