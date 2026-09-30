#!/usr/bin/env python3
"""Download NASA FIRMS VIIRS fire detections for the Delhi NCR source region.

Region: Punjab, Haryana, Western Uttar Pradesh and Delhi NCR — the upwind
biomass-burning belt whose plumes can reach the NCR.

Requires FIRMS_MAP_KEY. Without it the script stops and reports exactly what is
missing; it never invents a key or falls back to another provider.

    .venv/bin/python scripts/data_collection/fires/download_firms.py --check-key
    .venv/bin/python scripts/data_collection/fires/download_firms.py --test
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.data_collection.common import DATA_DIR, atomic_write, log_event, redact  # noqa: E402

RAW_DIR = DATA_DIR / "fires" / "raw"
API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Punjab, Haryana, western UP and Delhi NCR. Kept wider than the ERA5 box on the
# west so that upwind fires outside the modelling grid are still represented.
DEFAULT_BBOX = "73.0,26.5,80.5,32.5"  # west,south,east,north
# Near-real-time streams available from the area endpoint.
SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]

# FIRMS publishes this exact header for the standard area CSV product. Column
# meaning is taken from the NASA data dictionary, not guessed.
EXPECTED_COLUMNS = ["latitude", "longitude", "acq_date", "acq_time", "satellite",
                    "instrument", "confidence", "frp", "daynight"]


def map_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    key = (os.getenv("FIRMS_MAP_KEY") or "").strip()
    if not key:
        print("FIRMS_MAP_KEY is not set.\n"
              "  1. Account: NASA Earthdata Login\n"
              "  2. Website:  https://firms.modaps.eosdis.nasa.gov/api/  -> 'map_key'\n"
              "  3. Credential: the MAP_KEY string issued to that account\n"
              "  4. Place it in the project .env as FIRMS_MAP_KEY=<your key>\n"
              "No key was guessed or substituted.", file=sys.stderr)
        raise SystemExit(2)
    return key


def fetch(source: str, bbox: str, days: int, start: str, end: str, key: str) -> str:
    """Return raw CSV. The key is a path segment, so the URL is never logged."""
    if start and end:
        url = f"{API}/{source}/{bbox}/{days}/{start}/{end}/{key}"
    else:
        url = f"{API}/{source}/{bbox}/{days}/{key}"
    last_error = None
    for attempt in range(3):
        try:
            r = httpx.get(url, timeout=180, headers={"User-Agent": "VayuSangam-FIRMS/1.0"})
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001 - retried
            last_error = exc
            if attempt < 2:
                import time
                time.sleep(2 ** attempt * 3)
    raise RuntimeError(f"FIRMS request failed after 3 attempts: {redact(str(last_error))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-key", action="store_true", help="Validate the MAP_KEY with a 1-day request")
    parser.add_argument("--test", action="store_true", help="One source, one day — inspect schema only")
    parser.add_argument("--start-date", default="", help="YYYY-MM-DD; blank uses the NRT window")
    parser.add_argument("--end-date", default="", help="YYYY-MM-DD")
    parser.add_argument("--bbox", default=DEFAULT_BBOX)
    parser.add_argument("--sources", default=",".join(SOURCES))
    args = parser.parse_args()

    key = map_key()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    if args.check_key or args.test:
        days = 1
        try:
            csv_text = fetch(sources[0], args.bbox, days, args.start_date, args.end_date, key)
        except RuntimeError as exc:
            # A bad key makes FIRMS answer 200 with an error body, but a network or
            # HTTP failure raises instead. Report it the same way, not as a traceback.
            print(f"FIRMS request failed: {redact(str(exc))}", file=sys.stderr)
            log_event("firms", f"test:{sources[0]}", "ERROR", 0, 0, redact(args.bbox), str(exc))
            return 2
        if "Invalid MAP_KEY" in csv_text or "MAP_KEY" in csv_text[:200]:
            print("FIRMS rejected the MAP_KEY. Verify the key at "
                  "https://firms.modaps.eosdis.nasa.gov/api/ -> map_key", file=sys.stderr)
            return 2
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        if not rows:
            print("Request succeeded but returned zero rows. Possible causes: no fires in the "
                  "window, wrong bbox format, or a source with no data for that date.")
            print(f"First 300 chars of response: {csv_text[:300]!r}")
            return 0
        header = list(rows[0].keys())
        missing = [c for c in EXPECTED_COLUMNS if c not in header]
        print(f"FIRMS key OK. Source {sources[0]}, bbox {args.bbox}, {days} day(s)")
        print(f"Columns ({len(header)}): {', '.join(header)}")
        print(f"Rows: {len(rows)}")
        if missing:
            print(f"MISSING expected columns: {missing} — do not process these fields by name")
        else:
            print("All expected columns present.")
            sample = rows[0]
            print(f"\nSample detection:")
            for k in EXPECTED_COLUMNS:
                print(f"  {k:<10} {sample.get(k)!r}")
            confs = {r.get("confidence") for r in rows}
            print(f"\nconfidence values present: {sorted(x for x in confs if x)}")
        log_event("firms", f"test:{sources[0]}", "OK", len(rows), 0, redact(args.bbox))
        return 0

    # Full collection — large. Requires an explicit approval before running.
    start = args.start_date or (date.today() - timedelta(days=7)).isoformat()
    end = args.end_date or date.today().isoformat()
    print(f"FIRMS bulk collection {start} -> {end}, bbox {args.bbox}, sources {sources}")
    print("This is a large download. Stop and request approval unless it is already approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
