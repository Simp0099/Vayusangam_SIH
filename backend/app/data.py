"""Small, bounded API reads over checked-in normalized source tables."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
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


def stations():
    availability = {row["station_id"]: row for row in _rows(DATA / "air_quality/station_availability.csv")}
    observed = {row["station_id"] for row in _rows(DATA / "air_quality/air_quality_hourly.csv")}
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
    rows = [row for row in _rows(DATA / "air_quality/air_quality_hourly.csv") if row["station_id"] == station_id]
    if not rows:
        return {"status": "empty", "source": "OpenAQ v3 hourly station observations", "data_class": "observation", "unit": AQ_FIELDS[variable], "coverage": {"start_utc": None, "end_utc": None}, "records": [], "limitations": ["No normalized observations are available for this station in the current sample."]}
    cutoff = _utc(max(row["timestamp"] for row in rows)) - timedelta(hours=max(1, min(hours, 2160)) - 1)
    filtered = [row for row in rows if _utc(row["timestamp"]) >= cutoff]
    values = [{"timestamp_utc": row["timestamp"], "value": _number(row.get(variable))} for row in filtered]
    valid = [row["timestamp_utc"] for row in values if row["value"] is not None]
    return {"status": "ready" if valid else "empty", "source": "OpenAQ v3 hourly station observations", "data_class": "observation", "station_id": station_id, "variable": variable, "unit": AQ_FIELDS[variable], "coverage": {"start_utc": min(valid) if valid else None, "end_utc": max(valid) if valid else None}, "records": values, "valid_count": len(valid), "missing_count": len(values) - len(valid), "limitations": ["The checked-in normalized OpenAQ export covers one station and 72 hours.", "Values are hourly interval means; null hours are not imputed."]}


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
    observations = list(_rows(DATA / "air_quality/air_quality_hourly.csv"))
    valid_pm = [row["timestamp"] for row in observations if _number(row.get("PM2.5")) is not None]
    return {
        "sources": [
            {"id": "openaq", "label": "OpenAQ hourly observations", "data_class": "observation", "status": "sample", "station_count": len({row["station_id"] for row in observations}), "row_count": len(observations), "last_valid_pm25_utc": max(valid_pm) if valid_pm else None, "limitations": ["Current normalized table is one station / 72 hours; raw collection manifest is marked in progress."]},
            {"id": "era5", "label": "ERA5 reanalysis via Open-Meteo", "data_class": "reanalysis", "status": "archive", "path": "data/meteorology/processed/meteorology_hourly.csv"},
            {"id": "forecast_archive", "label": "Historical Forecast API archive", "data_class": "forecast_archive", "status": "archive", "path": "data/meteorology/processed/forecast_hourly.csv"},
            {"id": "fires", "label": "Fire detections", "data_class": "observation", "status": "unavailable", "limitations": ["No FIRMS dataset is present."]},
            {"id": "cams", "label": "CAMS atmospheric composition", "data_class": "reanalysis", "status": "unavailable", "limitations": ["No CAMS dataset is present."]},
        ]
    }
