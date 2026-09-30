#!/usr/bin/env python3
"""Capability probe: which datasets are genuinely credential-blocked?

A "blocked on a credential" conclusion is only trustworthy if a keyless route
was actually checked. This probe tests each blocked domain against its live
endpoint and records WHAT the endpoint said, so the answer can be re-verified
later instead of re-argued.

    .venv/bin/python scripts/data_collection/probe_blocked_domains.py

A credential error proves the endpoint is LIVE. It is evidence about that one
route only — never evidence that the data is unobtainable.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT = PROJECT_ROOT / "data" / "manifests" / "blocked_domains_probe.json"
TIMEOUT = 30

# The venv's certifi bundle, not the system one. Python's default trust store on
# macOS is missing the issuer for some of these hosts, which surfaces as a TLS
# error — indistinguishable from "blocked" unless the cause is named explicitly.
try:
    import certifi
    import ssl
    _OPENER = urllib.request.build_opener(
        urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=certifi.where())))
except Exception:  # noqa: BLE001 - fall back to the default opener
    _OPENER = None


def get(url: str) -> tuple[int, str]:
    """Return (http_status, body_prefix).

    A TLS or DNS failure is reported distinctly from an HTTP status so a network
    problem is never read as a data-availability answer.
    """
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "VayuSangam-capability-probe/1.0"})
        opener = _OPENER or urllib.request.build_opener()
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - the failure mode is the datum here
        return 0, f"TRANSPORT_FAILURE {type(exc).__name__}: {exc}"


def probe_fires() -> dict:
    # A 400 carrying "Invalid MAP_KEY" is the server confirming the route is live
    # and that the credential is what's absent. A keyless 200 would be a real find.
    code, body = get("https://firms.modaps.eosdis.nasa.gov/api/area/csv")
    keyless = code == 200
    return {
        "domain": "fires (NASA FIRMS VIIRS)",
        "endpoint": "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
        "http_status": code,
        "endpoint_live": code in (200, 400),
        "keyless_access_works": keyless,
        "response_excerpt": body.strip()[:200],
        "verdict": "KEY REQUIRED" if code == 400 and "MAP_KEY" in body else
                   ("KEYLESS ACCESS AVAILABLE — revisit" if keyless else "INCONCLUSIVE"),
        "blocker": "FIRMS_MAP_KEY in .env (issue at https://firms.modaps.eosdis.nasa.gov/api/)",
    }


def probe_pressure_levels() -> dict:
    """The ERA5 substitute: does Open-Meteo serve 925/850 hPa temperatures?

    Returns HTTP 200 with the variable listed in the units block and 100% nulls
    in the data. A declared unit is the schema, not the data.
    """
    results = {}
    for endpoint, model in (("historical-forecast-api", "era5"),
                            ("historical-forecast-api", "era5_land"),
                            ("archive-api", "era5")):
        url = (f"https://{endpoint}.open-meteo.com/v1/forecast?latitude=28.61&longitude=77.21"
               f"&start_date=2024-09-01&end_date=2024-09-01"
               f"&hourly=temperature_925hPa&models={model}")
        code, body = get(url)
        try:
            hourly = json.loads(body).get("hourly", {}).get("temperature_925hPa")
        except json.JSONDecodeError:
            hourly = None
        if hourly is None:
            results[f"{endpoint}/{model}"] = "variable not served"
        else:
            filled = sum(1 for v in hourly if v is not None)
            results[f"{endpoint}/{model}"] = f"{filled}/{len(hourly)} non-null"
    any_data = any(v.split(" non-null")[0].split("/")[0].isdigit() and
                   int(v.split("/")[0]) > 0 for v in results.values() if "non-null" in v)
    return {
        "domain": "era5 pressure levels (T925/T850 for inversion detection)",
        "endpoint": "Open-Meteo (probed as the keyless alternative to Copernicus)",
        "attempts": results,
        "keyless_access_works": any_data,
        "verdict": "KEYLESS ACCESS AVAILABLE — revisit" if any_data else
                   "NO KEYLESS DATA — genuinely requires a Copernicus CDS token",
        "note": ("HTTP 200 with the variable declared but 100% null is a schema "
                 "entry, not data. Do not report this as available."),
        "blocker": "~/.cdsapirc with a Copernicus CDS API token",
    }


def probe_cams() -> dict:
    code, _ = get("https://cds.climate.copernicus.eu/api/catalogue/v1/collections")
    return {
        "domain": "cams (Copernicus Atmosphere Monitoring)",
        "endpoint": "https://cds.climate.copernicus.eu/api/catalogue/v1/collections",
        "http_status": code,
        "endpoint_live": code in (200, 401, 403),
        "catalogue_reachable": code == 200,
        "verdict": "CATALOGUE REACHABLE — dataset retrieval still needs a CDS token",
        "note": "A reachable catalogue does not mean the GRIB data is retrievable.",
        "blocker": "~/.cdsapirc with a Copernicus CDS API token",
    }


def main() -> int:
    results = [probe_fires(), probe_pressure_levels(), probe_cams()]
    payload = {
        "probed_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": ("Establish which blocked domains are genuinely credential-blocked "
                    "rather than assumed to be. Re-run to re-verify."),
        "domains": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for r in results:
        print(f"  {r['domain'][:52]:<52} {r['verdict']}")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
