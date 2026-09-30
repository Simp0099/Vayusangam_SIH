#!/usr/bin/env python3
"""Cross-dataset validation for VayuSangam.

Runs entirely on files already on disk. Makes no network requests and reads no
credentials. Every dataset that has not been downloaded yet is reported as
SKIPPED (never as passing).

    .venv/bin/python scripts/data_collection/validate_all.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA = PROJECT_ROOT / "data"
REPORTS = PROJECT_ROOT / "reports"
LOGS = PROJECT_ROOT / "logs" / "data_collection"

# Physically impossible or definitionally out-of-range values.
LIMITS = {
    "PM2.5": (0, 2000), "PM10": (0, 3000), "NO2": (0, 2000), "NOx": (0, 3000),
    "O3": (0, 2000), "CO": (0, 20000), "SO2": (0, 2000),
    "relative_humidity": (0, 100), "wind_speed": (0, 130), "wind_direction": (0, 360),
    "temperature": (-60, 65),
}


def log_event(source: str, operation: str, status: str, records: int, duration_s: float, error: str = "") -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source, "operation": operation, "status": status,
        "records": records, "duration_s": round(duration_s, 3), "error": error[:500],
    }
    with (LOGS / "data_collection.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def check(name: str, fn) -> dict:
    import time
    started = time.time()
    try:
        detail, problems, warnings = fn()
        status = "FAIL" if problems else ("WARN" if warnings else "PASS")
        result = {"name": name, "status": status, "detail": detail,
                  "problems": problems, "warnings": warnings}
    except Exception as exc:  # a crashed check is a failure, never a silent pass
        result = {"name": name, "status": "FAIL", "detail": {},
                  "problems": [f"{type(exc).__name__}: {exc}"], "warnings": []}
    log_event("local", f"validate:{name}", result["status"],
              int(result["detail"].get("rows", 0) or 0), time.time() - started,
              "; ".join(result["problems"]))
    return result


def validate_air_quality() -> tuple[dict, list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    hourly = DATA / "air_quality" / "air_quality_hourly.csv"
    meta = DATA / "air_quality" / "station_metadata.csv"
    if not hourly.exists():
        return {"rows": 0}, ["air_quality_hourly.csv missing"], []
    frame = pd.read_csv(hourly)
    problems += [f"missing column: {c}" for c in ("station_id", "timestamp") if c not in frame]
    if problems:
        return {"rows": len(frame)}, problems, warnings

    ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if ts.isna().any():
        problems.append(f"{int(ts.isna().sum())} unparseable timestamps")
    if frame.duplicated(["station_id", "timestamp"]).any():
        problems.append(f"{int(frame.duplicated(['station_id', 'timestamp']).sum())} duplicate station_id+timestamp rows")
    if (ts.dt.minute != 0).any():
        problems.append("timestamps are not aligned to the hour")
    # The pipeline materialises explicit null rows up to the requested window end,
    # so grid padding legitimately extends past "now". Only rows that actually carry
    # an observation are checked for clock skew.
    observed_rows = frame.dropna(subset=[c for c in LIMITS if c in frame], how="all") if any(c in frame for c in LIMITS) else frame
    obs_ts = pd.to_datetime(observed_rows["timestamp"], utc=True, errors="coerce")
    if len(obs_ts) and obs_ts.max() > pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=6):
        warnings.append("observed timestamps in the future beyond a 6 h clock skew allowance")

    if meta.exists():
        ids = set(pd.read_csv(meta).station_id.astype(str))
        orphan = set(frame.station_id.astype(str)) - ids
        if orphan:
            problems.append(f"{len(orphan)} station_ids absent from station_metadata.csv")
    else:
        warnings.append("station_metadata.csv missing — referential integrity unchecked")

    for col, (lo, hi) in LIMITS.items():
        if col not in frame:
            continue
        values = pd.to_numeric(frame[col], errors="coerce")
        n = int(((values < lo) | (values > hi)).sum())
        if n:
            problems.append(f"{col}: {n} values outside [{lo}, {hi}]")
    # A station reporting a flat zero concentration for a whole week is a classic
    # silent data-failure signature, distinct from a legitimately clean hour.
    if "PM2.5" in frame:
        zero_runs = frame.assign(z=pd.to_numeric(frame["PM2.5"], errors="coerce").eq(0))
        flat = zero_runs.groupby("station_id")["z"].apply(lambda s: s.rolling(168).sum().max())
        if (flat.fillna(0) >= 168).any():
            warnings.append("at least one station has a >=168 h run of PM2.5 == 0 (suspect feed)")

    if "PM2.5" in frame and frame["PM2.5"].notna().sum() == 0 and len(frame):
        problems.append("no PM2.5 observations at all")
    for col, (lo, hi) in (("latitude", (-90, 90)), ("longitude", (-180, 180))):
        if col in frame:
            v = pd.to_numeric(frame[col], errors="coerce")
            if v.notna().any() and not v.between(lo, hi).all():
                problems.append(f"{col} out of WGS84 bounds [{lo}, {hi}]")
    return {"rows": len(frame), "stations": int(frame.station_id.nunique()),
            "span": [str(ts.min()), str(ts.max())]}, problems, warnings


def validate_quality_report() -> tuple[dict, list[str], list[str]]:
    path = DATA / "air_quality" / "data_quality_report.csv"
    if not path.exists():
        return {"rows": 0}, ["data_quality_report.csv missing"], []
    frame = pd.read_csv(path)
    problems = []
    pct = pd.to_numeric(frame.get("missing_percentage"), errors="coerce").dropna()
    if not pct.between(0, 100).all():
        problems.append("missing_percentage outside 0..100")
    if (pd.to_numeric(frame.get("observation_count"), errors="coerce").fillna(0) < 0).any():
        problems.append("negative observation_count")
    return {"rows": len(frame)}, problems, []


def validate_station_availability() -> tuple[dict, list[str], list[str]]:
    path = DATA / "air_quality" / "station_availability.csv"
    if not path.exists():
        return {"rows": 0}, ["station_availability.csv missing"], []
    frame = pd.read_csv(path)
    problems = []
    for col in ("station_id", "latitude", "longitude"):
        if col not in frame:
            problems.append(f"missing column: {col}")
    if problems:
        return {"rows": len(frame)}, problems, []
    lat, lon = pd.to_numeric(frame.latitude, errors="coerce"), pd.to_numeric(frame.longitude, errors="coerce")
    # The query bbox is 74-80E / 26-32.5N; a wider tolerance still catches a bad
    # CRS or a swapped lat/lon column without failing on the bbox edge itself.
    if lat.notna().any() and not lat.between(25, 34).all():
        problems.append(f"{int((~lat.between(25, 34)).sum())} latitudes outside the Delhi NCR region")
    if lon.notna().any() and not lon.between(72, 82).all():
        problems.append(f"{int((~lon.between(72, 82)).sum())} longitudes outside the Delhi NCR region")
    has = [c for c in frame.columns if c.startswith("has_")]
    if not has:
        problems.append("no has_* availability columns")
    empty_district = 0
    meta = DATA / "air_quality" / "station_metadata.csv"
    if meta.exists() and "district" in pd.read_csv(meta, nrows=0).columns:
        m = pd.read_csv(meta)
        empty_district = int(m.district.isna().sum()) if "district" in m else 0
    warnings = ["district is empty for all stations (OpenAQ v3 exposes no administrative area)"] if empty_district else []
    return {"rows": len(frame), "availability_columns": len(has), "stations_without_district": empty_district}, problems, warnings


def validate_manifests() -> tuple[dict, list[str], list[str]]:
    folder = DATA / "manifests"
    if not folder.exists():
        return {"files": 0}, [], ["data/manifests/ is empty — provenance not yet recorded"]
    files = list(folder.rglob("*.json"))
    # Only dataset manifests live here. Probe results, capability reports and
    # retry records are written into the same directory for discoverability but
    # carry no `source`/`files` schema — validating them as manifests produces
    # failures for files that are working exactly as intended.
    dataset_manifests = []
    skipped = []
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            dataset_manifests.append(f)  # invalid JSON is itself a finding
            continue
        if isinstance(payload, dict) and ("source" in payload or "files" in payload):
            dataset_manifests.append(f)
        else:
            skipped.append(f.name)
    if skipped and not dataset_manifests:
        return {"files": 0, "auxiliary": len(skipped)}, [], [
            f"data/manifests/ has no dataset manifest — only auxiliary record(s): "
            f"{', '.join(skipped)}"]
    problems, warnings = [], []
    for f in dataset_manifests:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{f.name}: invalid JSON ({exc})")
            continue
        for field in ("source", "download_timestamp_utc", "files", "lifecycle"):
            if field not in payload:
                problems.append(f"{f.name}: missing '{field}'")
        if payload.get("lifecycle") == "in_progress":
            # A manifest mid-download must not read as a finished inventory.
            warnings.append(f"{f.name}: lifecycle=in_progress — this dataset is still "
                            f"downloading; {payload.get('files_omitted', 0)} file(s) omitted "
                            f"from the listing. Provenance is NOT final.")
        if payload.get("files_omitted"):
            problems.append(f"{f.name}: {payload['files_omitted']} file(s) omitted from the "
                            f"listing — the inventory is incomplete")
    return {"files": len(files)}, problems, warnings


def validate_meteorology() -> tuple[dict, list[str], list[str]]:
    path = DATA / "meteorology" / "processed" / "meteorology_hourly.csv"
    if not path.exists():
        return {"rows": 0}, [], ["meteorology: not collected yet"]
    frame = pd.read_csv(path)
    problems, warnings = [], []
    for col in ("timestamp", "place", "temperature_2m", "surface_pressure"):
        if col not in frame:
            problems.append(f"missing column: {col}")
    if problems:
        return {"rows": len(frame)}, problems, warnings

    ts = pd.to_datetime(frame.timestamp, utc=True, errors="coerce")
    if ts.isna().any():
        problems.append(f"{int(ts.isna().sum())} unparseable timestamps")
    if frame.duplicated(["place", "timestamp"]).any():
        problems.append(f"{int(frame.duplicated(['place', 'timestamp']).sum())} duplicate place+timestamp rows")
    if (ts.dt.minute != 0).any():
        problems.append("timestamps are not aligned to the hour")
    if str(ts.dt.tz) != "UTC":
        problems.append(f"timestamps are {ts.dt.tz}, not UTC")

    # Open-Meteo serves ERA5; a direct ERA5 pull is the same reanalysis.
    warnings.append("source is ERA5/ERA5-Land reanalysis — not independent of a direct ERA5 download")

    for col, (lo, hi) in (("temperature_2m", (-60, 65)), ("surface_pressure", (850, 1100)),
                          ("wind_speed_10m_ms", (0, 200)), ("relative_humidity_2m", (0, 100))):
        if col not in frame:
            continue
        v = pd.to_numeric(frame[col], errors="coerce")
        n = int(((v < lo) | (v > hi)).sum())
        if n:
            problems.append(f"{col}: {n} values outside [{lo}, {hi}]")

    # The km/h -> m/s conversion must actually hold, or the m/s column is wrong.
    if {"wind_speed_10m", "wind_speed_10m_ms"} <= set(frame.columns):
        ratio = pd.to_numeric(frame.wind_speed_10m_ms, errors="coerce") / pd.to_numeric(frame.wind_speed_10m, errors="coerce").replace(0, pd.NA)
        if ratio.notna().any() and not ratio.dropna().sub(1 / 3.6).abs().lt(1e-6).all():
            problems.append("wind_speed_10m_ms is not wind_speed_10m / 3.6")
    return {"rows": len(frame), "places": int(frame.place.nunique()),
            "span": [str(ts.min()), str(ts.max())]}, problems, warnings


def validate_geospatial() -> tuple[dict, list[str], list[str]]:
    folder = DATA / "geospatial" / "raw"
    if not folder.exists() or not any(folder.glob("*.json")):
        return {"files": 0}, [], ["geospatial: not collected yet"]
    problems, warnings, counts = [], [], {}
    for f in sorted(folder.glob("osm_*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{f.name}: invalid JSON ({exc})")
            continue
        counts[f.stem] = len(payload.get("elements", []))
        if "boundaries" in f.stem:
            # Overpass returns relation geometry nested under members[].geometry,
            # not at the element top level, so check both shapes before claiming
            # the extract has no usable geometry.
            has_geom = any(
                e.get("geometry") or any(m.get("geometry") for m in e.get("members", []))
                for e in payload.get("elements", []))
            if not has_geom:
                problems.append("boundaries carry no geometry (neither element-level nor "
                                "members[].geometry) — a point-in-polygon district join is impossible")
    warnings.append("roads/landuse are tags-only (no geometry): usable for classification, "
                    "not for distance or point-in-polygon work")
    return {"files": len(counts), "elements": counts}, problems, warnings


def validate_forecast() -> tuple[dict, list[str], list[str]]:
    path = DATA / "meteorology" / "processed" / "forecast_hourly.csv"
    if not path.exists():
        return {"rows": 0}, [], ["forecast archive: not collected yet"]
    frame = pd.read_csv(path)
    problems, warnings = [], []
    for col in ("timestamp", "place", "boundary_layer_height_m"):
        if col not in frame:
            problems.append(f"missing column: {col}")
    if problems:
        return {"rows": len(frame)}, problems, warnings

    ts = pd.to_datetime(frame.timestamp, utc=True, errors="coerce")
    if ts.isna().any():
        problems.append(f"{int(ts.isna().sum())} unparseable timestamps")
    if str(ts.dt.tz) != "UTC":
        problems.append(f"timestamps are {ts.dt.tz}, not UTC")
    if frame.duplicated(["place", "timestamp"]).any():
        problems.append(f"{int(frame.duplicated(['place', 'timestamp']).sum())} duplicate place+timestamp rows")

    detail = {"rows": len(frame), "places": int(frame.place.nunique()),
              "span": [str(ts.min()), str(ts.max())]}

    # An all-null variable is a silent failure: the API returns HTTP 200 and
    # declares a unit even when the field has no data. Verified for PBLH, which
    # only exists from 2024-09-01 in the historical-forecast archive.
    for col in ("boundary_layer_height_m", "temperature_2m", "shortwave_radiation"):
        if col not in frame:
            continue
        s = pd.to_numeric(frame[col], errors="coerce")
        frac = s.notna().mean() if len(s) else 0.0
        detail[f"{col}_complete"] = round(float(frac), 4)
        if frac == 0:
            problems.append(f"{col} is entirely null — the source has no data for this window")
        elif frac < 0.5:
            warnings.append(f"{col} only {frac:.1%} populated; check its start date")

    if "boundary_layer_height_m" in frame:
        p = pd.to_numeric(frame.boundary_layer_height_m, errors="coerce").dropna()
        if len(p):
            detail["pblh_m"] = {"min": round(float(p.min())), "median": round(float(p.median())),
                                "max": round(float(p.max()))}
            # A deep daytime boundary layer legitimately reaches 2-5 km over the
            # Delhi basin in summer, so 5000 m is not by itself an error: the
            # observed max (5525 m) occurs in the 07-11 UTC morning-growth window.
            # Flag only values beyond the physically plausible ceiling, or a
            # median implying a permanently unlayered atmosphere.
            if p.max() > 8000:
                problems.append(f"PBLH max {p.max():.0f} m exceeds any plausible boundary layer — check units")
            if p.median() > 3000:
                warnings.append(f"PBLH median {p.median():.0f} m is implausibly deep; check units")

    warnings.append("previous-model-run forecast fields, NOT reanalysis — do not merge with "
                    "the ERA5 archive as if independent")
    return detail, problems, warnings


def validate_untouched_domains() -> tuple[dict, list[str], list[str]]:
    """Report the not-yet-collected domains as SKIPPED, never as passing.

    Only the domains still blocked on credentials. meteorology and geospatial have
    their own checks and are excluded to avoid reporting them twice.
    """
    domains = {"fires": DATA / "fires" / "processed",
               "era5": DATA / "era5" / "processed",
               "cams": DATA / "cams" / "processed"}
    out, pending = {}, []
    for name, folder in domains.items():
        files = [f for f in folder.glob("*") if f.is_file()] if folder.exists() else []
        out[name] = "collected" if files else "SKIPPED (not collected yet)"
        if not files:
            pending.append(name)
    return out, [], ([f"{', '.join(pending)}: no processed data — validation skipped"] if pending else [])


def render_html(report: dict) -> str:
    rows = []
    for r in report["checks"]:
        rows.append(
            f"<tr class='{r['status']}'><td>{r['name']}</td><td>{r['status']}</td>"
            f"<td><pre>{json.dumps(r['detail'], indent=1, default=str)}</pre></td>"
            f"<td>{'<br>'.join(r['problems'])}</td><td>{'<br>'.join(r['warnings'])}</td></tr>")
    return f"""<!doctype html><meta charset="utf-8"><title>VayuSangam data validation</title>
<style>body{{font:14px/1.5 -apple-system,sans-serif;margin:2rem;color:#1a1a1a}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.5rem;vertical-align:top;text-align:left}}
tr.PASS{{background:#f0fbf0}}tr.WARN{{background:#fffbe6}}tr.FAIL{{background:#fdeaea}}
pre{{margin:0;font-size:12px}}h1{{margin-bottom:.2rem}}.meta{{color:#666;margin-bottom:1.5rem}}</style>
<h1>VayuSangam — Data Validation Report</h1>
<div class="meta">Generated {report['generated_utc']} · overall: <strong>{report['status']}</strong></div>
<table><tr><th>Check</th><th>Status</th><th>Detail</th><th>Problems</th><th>Warnings</th></tr>
{''.join(rows)}</table>"""


def main() -> int:
    checks = [
        check("air_quality_hourly", validate_air_quality),
        check("data_quality_report", validate_quality_report),
        check("station_availability", validate_station_availability),
        check("manifests", validate_manifests),
        check("meteorology", validate_meteorology),
        check("forecast_archive", validate_forecast),
        check("geospatial", validate_geospatial),
        check("other_domains", validate_untouched_domains),
    ]
    failed = [c["name"] for c in checks if c["status"] == "FAIL"]
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL" if failed else ("WARN" if any(c["status"] == "WARN" for c in checks) else "PASS"),
        "failed_checks": failed,
        "checks": checks,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "data_validation_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (REPORTS / "data_validation_report.html").write_text(render_html(report), encoding="utf-8")
    for c in checks:
        print(f"[{c['status']:<4}] {c['name']}")
        for p in c["problems"]:
            print(f"         ERROR: {p}")
        for w in c["warnings"]:
            print(f"         warn:  {w}")
    print(f"\nOverall: {report['status']}")
    print(f"Reports: {REPORTS / 'data_validation_report.html'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
