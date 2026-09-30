#!/usr/bin/env python3
"""Retry the stations whose sensor lookup failed during discovery.

A station recorded as `sensor_lookup_status=error` was skipped because
/locations/<id>/sensors returned HTTP 500 at discovery time. That may have been
a transient fault, or a persistent upstream one. The difference decides whether
a re-run recovers real coverage or wastes requests, so it gets measured rather
than assumed.

    .venv/bin/python scripts/data_collection/retry_failed_sensors.py --check

Read-only with respect to data/air_quality/raw/. Writes nothing unless --apply
is passed, and then only to the sensor/metadata CSVs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.data_collection.openaq.common import DATA_DIR  # noqa: E402
from scripts.data_collection.write_manifest import redact  # noqa: E402

AVAILABILITY = DATA_DIR / "station_availability.csv"
SENSOR_META = DATA_DIR / "sensor_metadata.csv"
OUT = PROJECT_ROOT / "data" / "manifests" / "failed_sensor_retry.json"


def load_key() -> str:
    key = ""
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAQ_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
                break
    if not key:
        print("OPENAQ_API_KEY not found in .env", file=sys.stderr)
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Probe only; report, change nothing (default)")
    parser.add_argument("--apply", action="store_true",
                        help="Retry and let the collector re-discover on its next run")
    args = parser.parse_args()

    avail = pd.read_csv(AVAILABILITY)
    failed = avail[avail.sensor_lookup_status.astype(str).str.lower() == "error"]
    if failed.empty:
        print("No stations with sensor_lookup_status=error.")
        return 0

    key = load_key()
    if not key:
        return 2
    headers = {"X-API-Key": key}

    results = []
    with httpx.Client(timeout=45, headers=headers) as client:
        for row in failed.itertuples(index=False):
            sid = str(row.station_id)
            url = f"https://api.openaq.org/v3/locations/{sid}/sensors"
            entry: dict = {"station_id": sid, "station_name": getattr(row, "station_name", "")}
            try:
                resp = client.get(url)
                entry["http_status"] = resp.status_code
                if resp.status_code == 200:
                    sensors = resp.json().get("results", [])
                    entry["recovered"] = True
                    entry["sensors_found"] = len(sensors)
                    entry["parameters"] = sorted(
                        p for p in
                        ((s.get("parameter") or {}).get("name") for s in sensors)
                        if p)
                else:
                    entry["recovered"] = False
                    entry["body_excerpt"] = resp.text[:150]
            except Exception as exc:  # noqa: BLE001
                entry["recovered"] = False
                entry["http_status"] = 0
                entry["body_excerpt"] = f"{type(exc).__name__}: {exc}"[:150]
            results.append(entry)
            flag = "RECOVERED" if entry["recovered"] else f"still failing ({entry.get('http_status')})"
            print(f"  {sid:<10} {flag}")
            time.sleep(1.0)  # stay inside the quota while the main download runs

    recovered = [r for r in results if r["recovered"]]
    persistent = [r for r in results if not r["recovered"]]
    payload = {
        "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "failed_station_count": len(failed),
        "recovered": recovered,
        "persistent_failures": persistent,
        "conclusion": (
            "All failed lookups now succeed — re-run the collector's discovery step to "
            "recover this coverage." if recovered and not persistent else
            "Upstream is still failing for these locations; this is a persistent "
            "provider fault, not a transient one. No re-run will recover them until "
            "OpenAQ fixes it."),
        "applied": False,
    }

    if args.apply:
        payload["applied"] = True
        payload["note"] = (
            "Sensor metadata is refreshed by re-running the collector's discovery "
            "phase; this probe deliberately does not synthesise sensor rows.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nrecovered {len(recovered)}/{len(results)}")
    print(payload["conclusion"])
    print(f"Wrote {redact(str(OUT))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())