#!/usr/bin/env python3
"""Fetch static geospatial context for Delhi NCR from OpenStreetMap (Overpass).

Only features VayuSangam actually uses: administrative boundaries, the road
network, and land-use polygons. No global extracts.

Overpass has no key but is aggressively rate-limited, so the bbox and the
per-feature limits are explicit and the request is bounded. Test first:
    .venv/bin/python scripts/data_collection/geospatial/download_osm.py --test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.data_collection.common import DATA_DIR, atomic_write, log_event  # noqa: E402

RAW_DIR = DATA_DIR / "geospatial" / "raw"
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]

# Delhi NCR core (Delhi, Gurugram, Noida, Ghaziabad, Faridabad). The upwind
# source belt is deliberately excluded: a full-extent road extract is ~84k ways.
BBOX = {"south": 27.9, "west": 76.7, "north": 29.0, "east": 77.6}

# `out geom` inflates a response enormously (the boundary extract was 41.5 MB for
# 781 relations). Roads and land use are fetched with `out tags` because VayuSangam
# needs the network's *existence and classification* for station siting and
# transport features, not a renderable basemap. If true road geometry is ever
# needed (e.g. distance-to-highway computation), re-fetch those few features for a
# station-scale bbox rather than the whole region.

# Deliberately small and targeted. Each is a separate request so a failure in one
# does not lose the others.
QUERIES = {
    "boundaries": """
[out:json][timeout:180];
rel["boundary"="administrative"]["admin_level"~"4|6"]({bbox});
out geom;
""",
    "roads": """
[out:json][timeout:300];
way["highway"~"motorway|trunk|primary"]({bbox});
out tags;
""",
    "landuse": """
[out:json][timeout:300];
way["landuse"]({bbox});
out tags;
rel["landuse"]({bbox});
out tags;
""",
}


def run(query: str, timeout: float = 300) -> dict:
    body = query.format(bbox=f"{BBOX['south']},{BBOX['west']},{BBOX['north']},{BBOX['east']}")
    last = None
    for endpoint in ENDPOINTS:
        for attempt in range(2):
            try:
                r = httpx.post(endpoint, data={"data": body},
                               headers={"User-Agent": "VayuSangam-OSM/1.0"}, timeout=timeout)
                if r.status_code == 429:
                    print(f"  {endpoint} rate-limited; backing off", file=sys.stderr)
                    time.sleep(30)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as exc:  # noqa: BLE001 - retried / next endpoint
                last = exc
                time.sleep(5)
    raise RuntimeError(f"Overpass failed on all endpoints: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Boundaries only — checks scale")
    parser.add_argument("--only", default="", help="Comma-separated subset of features")
    args = parser.parse_args()

    names = [n.strip() for n in args.only.split(",")] if args.only else list(QUERIES)
    if args.test:
        names = ["boundaries"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for name in names:
        if name not in QUERIES:
            print(f"Unknown feature {name!r}; known: {', '.join(QUERIES)}", file=sys.stderr)
            return 2
        try:
            payload = run(QUERIES[name])
        except RuntimeError as exc:
            print(f"  {name}: FAILED — {exc}", file=sys.stderr)
            log_event("osm", f"fetch:{name}", "ERROR", 0, 0, "", str(exc))
            continue
        elements = payload.get("elements", [])
        out = RAW_DIR / f"osm_{name}.json"
        atomic_write(out, json.dumps(payload))
        size = out.stat().st_size
        total += size
        kinds: dict[str, int] = {}
        for e in elements:
            kinds[e.get("type", "?")] = kinds.get(e.get("type", "?"), 0) + 1
        print(f"  {name:<12} {len(elements):>6} elements  {size/1e6:6.1f} MB  {kinds}")
        log_event("osm", f"fetch:{name}", "OK", len(elements), 0, "")

    print(f"\nTotal {total/1e6:.1f} MB in {RAW_DIR}")
    print("Licence: Open Database License (ODbL) — attribution to OpenStreetMap contributors required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
