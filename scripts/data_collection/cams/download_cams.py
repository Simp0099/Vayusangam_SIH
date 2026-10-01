#!/usr/bin/env python3
"""Download CAMS global reanalysis (EAC4) for the Delhi NCR region.

EAC4's request schema differs from ERA5's and this was learned from the live
API, not from assumption:

  * There is NO year/month/day input. The date is one `date` string, either a
    single day or a `start/end` range. Passing year/month/day yields
    "Invalid key names".
  * `time` must be the COMPLETE 3-hourly set (00,03,...,21). Supplying a subset
    such as ['00:00'] is accepted by the client but rejected server-side with
    "Request has not produced a valid combination of values" — a confusing
    failure that reads like a variable problem.
  * `area` is snapped outward to the 0.75 degree grid.

    .venv/bin/python scripts/data_collection/cams/download_cams.py \
        --start-date 2025-02-01 --end-date 2026-10-01
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "cams" / "raw"
ADS_URL = "https://ads.atmosphere.copernicus.eu/api"
DATASET = "cams-global-reanalysis-eac4"

# Confirmed present in the live EAC4 schema (62 variables).
VARIABLES = ["particulate_matter_2.5um", "particulate_matter_10um",
             "nitrogen_dioxide", "ozone", "carbon_monoxide", "sulphur_dioxide",
             "total_aerosol_optical_depth_550nm", "dust_aerosol_optical_depth_550nm"]

# EAC4 is 3-hourly and requires the full set present in every request.
TIMES = [f"{h:02d}:00" for h in range(0, 24, 3)]


def month_chunks(start: date, end: date) -> list[tuple[str, str]]:
    out, cur = [], start
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1)
        out.append((cur.isoformat(), (min(end, nxt) - timedelta(days=1)).isoformat()))
        cur = nxt
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2025-02-01")
    parser.add_argument("--end-date", default="2026-10-01")
    parser.add_argument("--variables", default=",".join(VARIABLES))
    args = parser.parse_args()

    cfg = Path(os.path.expanduser("~/.cdsapirc"))
    if not cfg.exists():
        print("~/.cdsapirc missing", file=sys.stderr)
        return 2
    key = next((l.split(":", 1)[1].strip() for l in cfg.read_text().splitlines()
                if l.strip().lower().startswith("key:")), "")
    if not key:
        print("no key: line in ~/.cdsapirc", file=sys.stderr)
        return 2

    try:
        import cdsapi
    except ImportError:
        print("cdsapi not installed", file=sys.stderr)
        return 2

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    wanted = [v.strip() for v in args.variables.split(",") if v.strip()]
    chunks = month_chunks(date.fromisoformat(args.start_date),
                          date.fromisoformat(args.end_date))

    # EAC4 has NOT yet published 2026. Verified: 2026-01 and 2026-09 both return
    # HTTP 400 using the exact request shape that succeeds for every 2025 month,
    # and each variable fails independently. Retrying them burns quota and can
    # never succeed, so a chunk that fails this way is recorded, not retried.
    # The project keeps CAMS as a genuinely partial source: 11 of 20 months.
    NO_DATA_RE = re.compile(r"valid combination of values|None of the data", re.I)

    unavailable: list[str] = []
    print(f"CAMS EAC4: {len(chunks)} chunk(s), {len(wanted)} variables, {args.start_date} -> {args.end_date}")

    client = cdsapi.Client(url=ADS_URL, key=key, quiet=False)
    done = failed = skipped = 0
    for c_start, c_end in chunks:
        label = c_start[:7]
        target = RAW_DIR / f"cams_{label}.nc"
        if target.exists():
            print(f"  {label}: exists, skipping")
            skipped += 1
            continue
        req = {
            "variable": wanted,
            "date": f"{c_start}/{c_end}",
            "time": TIMES,
            "data_format": "netcdf",
            "area": [31.0, 73.0, 27.0, 80.0],
        }
        ok = False
        no_data = False
        for attempt in range(1, 4):
            try:
                tmp = target.with_suffix(".nc.part")
                client.retrieve(DATASET, req, str(tmp))
                tmp.replace(target)
                print(f"  {label}: OK ({target.stat().st_size/1e6:.1f} MB)")
                ok = True
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if NO_DATA_RE.search(msg):
                    # Dataset coverage ends here. Retrying cannot help.
                    print(f"  {label}: NOT PUBLISHED by EAC4 — not retrying")
                    no_data = True
                    break
                print(f"  {label}: attempt {attempt}/3 failed — {msg[:170]}",
                      file=sys.stderr)
                if attempt < 3:
                    time.sleep(15 * attempt)
        if ok:
            done += 1
        elif no_data:
            unavailable.append(label)
        else:
            failed += 1

    print(f"\nchunks: {done} downloaded, {skipped} skipped, {failed} failed")
    if unavailable:
        print(f"NOT PUBLISHED by EAC4 (dataset coverage limit, not an error): "
              f"{', '.join(unavailable)}")
        print("CAMS is a PARTIAL source. Treat CAMS-derived features as absent "
              "outside the downloaded range rather than filling it.")
    if done == 0 and skipped == 0:
        print("NOTHING downloaded. If the error mentions licences or policies, "
              "accept them in a browser at "
              "https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4"
              "?tab=download#manage-licences", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())