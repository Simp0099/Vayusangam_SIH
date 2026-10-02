"""Small, bounded API reads over checked-in normalized source tables."""
from __future__ import annotations

import csv
import json
from collections import deque
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
MASTER_COLUMNS = json.loads((DATA / "master/master_manifest.json").read_text())["columns"]
AQ_FIELDS = {
    "PM2.5": "µg/m³", "PM10": "µg/m³", "NO2": "ppb", "NOx": "ppb",
    "O3": "ppb", "CO": "ppb", "SO2": "ppb", "temperature": "°C",
    "relative_humidity": "%", "wind_speed": "m/s", "wind_direction": "°",
}
MET_FIELDS = {
    "temperature_2m": "°C", "dew_point_2m": "°C", "relative_humidity_2m": "%",
    "surface_pressure": "hPa", "wind_speed_10m": "km/h", "wind_speed_10m_ms": "m/s",
    "wind_direction_10m": "°", "cloud_cover": "%", "precipitation": "mm",
    "boundary_layer_height_m": "m", "shortwave_radiation": "W/m²",
}


def _rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        yield from csv.DictReader(file)


def _number(value: str | None):
    if not value or value.strip().lower() in {"nan", "null", "none"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _utc(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@lru_cache(maxsize=1)
def _air_quality_offsets():
    path = DATA / "master/master_training_dataset.csv"
    offsets = {}
    with path.open("rb") as file:
        file.readline()
        current_id = None
        start = file.tell()
        while line := file.readline():
            line_start = file.tell() - len(line)
            station_id = line.split(b",", 1)[0].decode("ascii")
            if station_id != current_id:
                if current_id is not None:
                    offsets.setdefault(current_id, []).append((start, line_start))
                current_id, start = station_id, line_start
        if current_id is not None:
            offsets.setdefault(current_id, []).append((start, file.tell()))
    return offsets


@lru_cache(maxsize=8)
def _station_rows(station_id: str):
    path = DATA / "master/master_training_dataset.csv"
    rows = deque(maxlen=2160)
    for start, _ in _air_quality_offsets().get(str(station_id), ()):
        with path.open(encoding="utf-8-sig", newline="") as file:
            file.seek(start)
            for row in csv.DictReader(file, fieldnames=MASTER_COLUMNS):
                if row["station_id"] != str(station_id):
                    break
                rows.append(row)
    return list(rows)


@lru_cache(maxsize=1)
def _forecast_by_place():
    result = {}
    for row in _rows(DATA / "meteorology/processed/forecast_hourly.csv"):
        result.setdefault(row["place"], {})[row["timestamp"]] = {
            "boundary_layer_height_m": _number(row.get("boundary_layer_height_m")),
            "wind_speed_10m_ms": _number(row.get("wind_speed_10m_ms")),
        }
    return result


def stations():
    availability = {row["station_id"]: row for row in _rows(DATA / "air_quality/station_availability.csv")}
    observed = {row["station_id"] for row in _rows(DATA / "air_quality/data_quality_report.csv") if row["record_type"] == "station_variable" and row["observation_count"] not in {"", "0"}}
    results = []
    for row in _rows(DATA / "air_quality/station_metadata.csv"):
        available = availability.get(row["station_id"], {})
        results.append({
            "id": row["station_id"], "name": row["station_name"],
            "latitude": _number(row["latitude"]), "longitude": _number(row["longitude"]),
            "district": row["district"] or None, "provider": row["provider"] or None,
            "owner": row["owner"] or None, "timezone": row["timezone"] or None,
            "availability": {key.removeprefix("has_"): value.lower() == "true"
                             for key, value in available.items() if key.startswith("has_")},
            "has_normalized_observations": row["station_id"] in observed,
        })
    return results


def air_quality(station_id: str, variable: str, hours: int):
    if variable not in AQ_FIELDS:
        raise ValueError("Unsupported air-quality variable")
    rows = _station_rows(station_id)
    if not rows:
        return {"status": "empty", "source": "OpenAQ v3 hourly station observations", "data_class": "observation", "unit": AQ_FIELDS[variable], "coverage": {"start_utc": None, "end_utc": None}, "records": [], "limitations": ["No normalized observations are available for this station."]}
    cutoff = _utc(max(row["timestamp"] for row in rows)) - timedelta(hours=max(1, min(hours, 2160)) - 1)
    filtered = [row for row in rows if _utc(row["timestamp"]) >= cutoff]
    values = [{"timestamp_utc": row["timestamp"], "value": _number(row.get(variable))} for row in filtered]
    valid = [row["timestamp_utc"] for row in values if row["value"] is not None]
    return {"status": "ready" if valid else "empty", "source": "OpenAQ v3 hourly station observations", "data_class": "observation", "station_id": station_id, "variable": variable, "unit": AQ_FIELDS[variable], "coverage": {"start_utc": min(valid) if valid else None, "end_utc": max(valid) if valid else None}, "records": values, "valid_count": len(valid), "missing_count": len(values) - len(valid), "limitations": ["Station coverage and completeness vary; hourly nulls are not imputed."]}


def station_observations(station_id: str, hours: int):
    rows = _station_rows(station_id)
    if not rows:
        return {"status": "empty", "station_id": station_id, "records": [], "coverage": {"start_utc": None, "end_utc": None}, "limitations": ["No normalized observations are available for this station."]}
    latest = max(row["timestamp"] for row in rows)
    cutoff = _utc(latest) - timedelta(hours=max(1, min(hours, 2160)) - 1)
    selected = [row for row in rows if _utc(row["timestamp"]) >= cutoff]
    forecast = _forecast_by_place()
    records = []
    for row in selected:
        met = forecast.get(row.get("met_place", ""), {}).get(row["timestamp"], {})
        wind = met.get("wind_speed_10m_ms")
        pblh = met.get("boundary_layer_height_m")
        records.append({
            "timestamp_utc": row["timestamp"],
            **{key: _number(row.get(key)) for key in AQ_FIELDS},
            "temperature_2m": _number(row.get("temperature_2m")),
            "relative_humidity_2m": _number(row.get("relative_humidity_2m")),
            "wind_speed_10m_ms": _number(row.get("wind_speed_10m_ms")) if row.get("wind_speed_10m_ms") else wind,
            "boundary_layer_height_m": pblh,
            "ventilation_coefficient": pblh * wind if pblh is not None and wind is not None else None,
            "t925_c": _number(row.get("t925_c")), "t850_c": _number(row.get("t850_c")),
            "t925_minus_t850_c": _number(row.get("t925_minus_t850_c")),
            "pm25_cams_ugm3": _number(row.get("pm25_cams_ugm3")),
            "aod550_cams": _number(row.get("aod550_cams")),
            "met_place": row.get("met_place") or None,
            "met_distance_km": _number(row.get("met_distance_km")),
        })
    valid_pm = [row["timestamp_utc"] for row in records if row["PM2.5"] is not None]
    return {
        "status": "ready" if valid_pm else "empty", "station_id": station_id,
        "source": "Canonical station-hour master table with exact-time joins", "data_class": "observation",
        "records": records, "coverage": {"start_utc": min(valid_pm) if valid_pm else None, "end_utc": max(valid_pm) if valid_pm else None},
        "valid_count": len(valid_pm), "missing_count": len(records) - len(valid_pm),
        "limitations": ["Hourly interval means; missing values remain null and are not imputed."],
    }


def meteorology(place: str, product: str, variable: str, hours: int):
    if product not in {"reanalysis", "forecast_archive"}:
        raise ValueError("Product must be reanalysis or forecast_archive")
    if variable not in MET_FIELDS:
        raise ValueError("Unsupported meteorology variable")
    filename = "meteorology_hourly.csv" if product == "reanalysis" else "forecast_hourly.csv"
    path = DATA / "meteorology/processed" / filename
    matches = [row for row in _rows(path) if row["place"] == place]
    if not matches:
        return {"status": "empty", "source": "Open-Meteo", "data_class": product, "records": [], "limitations": ["No matching place exists in this archive."]}
    latest = max(matches, key=lambda row: row["timestamp"])["timestamp"]
    cutoff = _utc(latest) - timedelta(hours=max(1, min(hours, 2160)) - 1)
    rows = [row for row in matches if _utc(row["timestamp"]) >= cutoff]
    values = [{"timestamp_utc": row["timestamp"], "value": _number(row.get(variable))} for row in rows]
    valid = [row["timestamp_utc"] for row in values if row["value"] is not None]
    label = "Open-Meteo ERA5 reanalysis" if product == "reanalysis" else "Open-Meteo Historical Forecast API archive"
    limitations = ["Historical valid-time archive; not current conditions or an operational forecast."]
    if product == "forecast_archive":
        limitations.append("Forecast run time and lead are not present in this table.")
    return {"status": "ready" if valid else "empty", "source": label, "data_class": product, "place": place, "variable": variable, "unit": MET_FIELDS[variable], "coverage": {"start_utc": min(valid) if valid else None, "end_utc": max(valid) if valid else None}, "records": values, "limitations": limitations}


def data_status():
    master = json.loads((DATA / "master/master_manifest.json").read_text())
    collection = json.loads((DATA / "air_quality/collection_manifest.json").read_text())
    cams_path = DATA / "cams/processed/cams_station_hourly.csv"
    era5_path = DATA / "era5/processed/era5_station_hourly.csv"
    geo_files = [DATA / "geospatial/raw/osm_boundaries.json", DATA / "geospatial/raw/osm_roads.json", DATA / "geospatial/raw/osm_landuse.json"]
    return {
        "sources": [
            {"id": "openaq", "label": "OpenAQ hourly observations", "data_class": "observation", "status": collection.get("status", "unknown"), "station_count": master.get("stations"), "row_count": master.get("rows"), "coverage": {"start_utc": collection.get("source_start_date"), "end_utc": collection.get("source_end_date")}, "limitations": ["Observation coverage is uneven; see the quality report for station and pollutant completeness."]},
            {"id": "meteorology", "label": "Open-Meteo historical forecast archive", "data_class": "forecast_archive", "status": "archive", "path": "data/meteorology/processed/forecast_hourly.csv", "coverage": {"start": "2024-09-01", "end": "2026-09-30"}, "limitations": ["Historical model runs, not an operational forecast or reanalysis."]},
            {"id": "era5", "label": "ERA5 pressure-level archive", "data_class": "reanalysis", "status": "archive" if era5_path.exists() else "unavailable", "path": str(era5_path.relative_to(DATA.parent)), "limitations": ["Pressure-level samples are kept separate from station observations."]},
            {"id": "cams", "label": "CAMS EAC4 atmospheric composition", "data_class": "reanalysis", "status": "partial" if cams_path.exists() else "unavailable", "path": str(cams_path.relative_to(DATA.parent)), "coverage": {"start": "2025-02", "end": "2025-12"}, "limitations": ["No 2026 CAMS data is available in this repository."]},
            {"id": "fires", "label": "NASA FIRMS fire detections", "data_class": "observation", "status": "blocked", "limitations": ["No FIRMS detections are present; the provider request is blocked. No points are simulated."]},
            {"id": "geospatial", "label": "OpenStreetMap NCR context", "data_class": "geospatial", "status": "available" if all(path.exists() for path in geo_files) else "partial", "files": [str(path.relative_to(DATA.parent)) for path in geo_files if path.exists()], "limitations": ["Raw boundary and road files are available; no simplified map layer is connected to the dashboard."]},
            {"id": "master", "label": "Master station-hour table", "data_class": "processed", "status": "available", "path": "data/master/master_training_dataset.csv", "row_count": master.get("rows"), "station_count": master.get("stations"), "limitations": ["Missing source values remain null; this file is not a forecast output."]},
            {"id": "features", "label": "Model-ready feature tables", "data_class": "feature", "status": "available", "path": "data/features/air_quality_features.csv", "limitations": ["Derived temporal features are for training; they are not displayed as observed measurements."]},
        ]
    }
