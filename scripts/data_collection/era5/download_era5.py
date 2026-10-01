#!/usr/bin/env python3
"""Download ERA5 pressure-level + single-level fields for the Delhi NCR region.

Written because scripts/data_collection/era5/prepare_era5.py validates and
sizes the request but deliberately performs no download. Requests are chunked by
month so a failure resumes rather than restarting, and each chunk is written
atomically.

    .venv/bin/python scripts/data_collection/era5/download_era5.py \
        --start-date 2025-02-01 --end-date 2026-10-01

Requires ~/.cdsapirc. Raw output is immutable once written.
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

RAW_DIR = PROJECT_ROOT / "data" / "era5" / "raw"

# ERA5 `area` order is [N, W, S, E] — the reverse of our internal convention.
ERA5_AREA = [31.0, 73.0, 27.0, 80.0]

PRESSURE_LEVELS = ["925", "850"]


def chunk_months(start: date, end: date) -> list[tuple[str, str]]:
    out, cur = [], start.replace(day=1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1)
        last = min(end, nxt)
        out.append((cur.isoformat(), last.isoformat()))
        cur = nxt
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2025-02-01")
    parser.add_argument("--end-date", default="2026-10-01")
    parser.add_argument("--force", action="store_true", help="re-download existing chunks")
    args = parser.parse_args()

    if not Path(os.path.expanduser("~/.cdsapirc")).exists():
        print("~/.cdsapirc missing", file=sys.stderr)
        return 2
    try:
        import cdsapi
    except ImportError:
        print("cdsapi not installed: .venv/bin/pip install cdsapi", file=sys.stderr)
        return 2

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    months = chunk_months(start, end)
    # ERA5 runs roughly a 5-day lag, so the current month legitimately has no
    # data yet and CDS answers "None of the data you have requested is
    # available". Requesting it is not a failure -- it is an incomplete month.
    today = date.today()
    partial = [label for label, _ in months
               if date(int(label[:4]), int(label[5:7]), 1) >= today.replace(day=1)]
    if partial:
        print(f"note: {', '.join(partial)} not requested -- ERA5 lags ~5 days, "
              f"so the current month has no data yet (today is {today}).")
        months = [(s, e) for s, e in months
                  if date(int(s[:4]), int(s[5:7]), 1) < today.replace(day=1)]
    print(f"ERA5 download: {len(months)} monthly chunk(s), {args.start_date} -> {args.end_date}")

    client = cdsapi.Client(quiet=False)
    done = failed = skipped = 0
    for m_start, m_end in months:
        label = m_start[:7]
        target = RAW_DIR / f"era5_{label}.nc"
        if target.exists() and not args.force:
            print(f"  {label}: exists, skipping")
            skipped += 1
            continue
        days = list(range(1, calendar.monthrange(int(m_start[:4]), int(m_start[5:7]))[1] + 1))
        req = {
            "product_type": "reanalysis",
            "variable": ["temperature"],
            "pressure_level": PRESSURE_LEVELS,
            "year": m_start[:4],
            "month": m_start[5:7],
            # ERA5 rejects a request that gives `month` without `day`; the earlier
            # version omitted it and the client silently retried a malformed job.
            "day": [f"{d:02d}" for d in days],
            "time": "00:00",
            "format": "netcdf",
            "area": ERA5_AREA,
        }
        ok = False
        for attempt in range(1, 4):
            try:
                tmp = target.with_suffix(".nc.part")
                # day spans the month for the single-level request
                client.retrieve("reanalysis-era5-pressure-levels", req, str(tmp))
                tmp.replace(target)
                print(f"  {label}: OK ({target.stat().st_size/1e6:.1f} MB)")
                ok = True
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)[:180]
                print(f"  {label}: attempt {attempt}/3 failed — {msg}", file=sys.stderr)
                if attempt < 3:
                    time.sleep(20 * attempt)
        if ok:
            done += 1
        else:
            failed += 1

    print(f"\nchunks: {done} downloaded, {skipped} skipped, {failed} failed")
    print(f"raw dir: {RAW_DIR}")
    if failed:
        # Surface the dominant failure reason. "None of the data you have
        # requested is available" is CDS's generic response when the licence
        # gate rejects the request, so do not let it read as an empty archive.
        print("\nMost chunks failed. Common causes, in order of likelihood:\n"
              "  1. Licence not accepted for the dataset (most common). CDS answers\n"
              "     with 'None of the data you have requested is available', which does\n"
              "     NOT mean the archive lacks the dates.\n"
              "       https://cds.climate.copernicus.eu/datasets/"
              "reanalysis-era5-pressure-levels?tab=download#manage-licences\n"
              "  2. Account email not yet activated.\n"
              "  3. A genuinely invalid variable/level/date combination.",
              file=sys.stderr)
    if done == 0 and skipped == 0:
        print("\nNOTHING was downloaded and nothing pre-existed. This is a total "
              "failure, not a completed run.", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())