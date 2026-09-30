"""Tests for the cross-dataset validator. Offline only — no network, no credentials."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.data_collection.meteorology import download_open_meteo as om  # noqa: E402

spec = importlib.util.spec_from_file_location("validate_all", ROOT / "scripts" / "data_collection" / "validate_all.py")
validate_all = importlib.util.module_from_spec(spec)
sys.modules["validate_all"] = validate_all
spec.loader.exec_module(validate_all)


def _write_air_quality(tmp_path: Path, frame: pd.DataFrame) -> None:
    validate_all.DATA = tmp_path / "data"
    (validate_all.DATA / "air_quality").mkdir(parents=True, exist_ok=True)
    frame.to_csv(validate_all.DATA / "air_quality" / "air_quality_hourly.csv", index=False)


def good_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "station_id": ["1"] * 3, "timestamp": ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z", "2024-01-01T02:00:00Z"],
        "latitude": [28.6] * 3, "longitude": [77.2] * 3, "PM2.5": [50.0, 55.0, 60.0],
    })


def test_valid_frame_passes(tmp_path):
    _write_air_quality(tmp_path, good_frame())
    detail, problems, warnings = validate_all.validate_air_quality()
    assert problems == [] and detail["rows"] == 3


def test_duplicate_timestamps_are_problems(tmp_path):
    frame = pd.concat([good_frame(), good_frame().iloc[[0]]], ignore_index=True)
    _write_air_quality(tmp_path, frame)
    _, problems, _ = validate_all.validate_air_quality()
    assert any("duplicate" in p for p in problems)


def test_physically_impossible_value_is_problem(tmp_path):
    frame = good_frame()
    frame.loc[0, "PM2.5"] = -5.0
    _write_air_quality(tmp_path, frame)
    _, problems, _ = validate_all.validate_air_quality()
    assert any("PM2.5" in p and "outside" in p for p in problems)


def test_all_null_pm25_is_problem_not_pass(tmp_path):
    frame = good_frame().assign(**{"PM2.5": [None, None, None]})
    _write_air_quality(tmp_path, frame)
    _, problems, _ = validate_all.validate_air_quality()
    assert any("no PM2.5" in p for p in problems)


def test_missing_values_stay_null_never_zero(tmp_path):
    frame = good_frame()
    frame.loc[2, "PM2.5"] = None
    _write_air_quality(tmp_path, frame)
    out = pd.read_csv(validate_all.DATA / "air_quality" / "air_quality_hourly.csv")
    assert pd.isna(out["PM2.5"].iloc[2]), "missing PM2.5 must remain NaN, not 0"


def test_out_of_bounds_coordinates_are_problems(tmp_path):
    frame = good_frame().assign(latitude=[28.6, 28.6, 91.0])
    _write_air_quality(tmp_path, frame)
    _, problems, _ = validate_all.validate_air_quality()
    assert any("latitude" in p for p in problems)


def test_zero_grid_padding_is_not_a_future_timestamp(tmp_path):
    """Grid padding past 'now' is legitimate; only real observations are checked."""
    future = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=2)).floor("h")
    frame = good_frame()
    frame = pd.concat([frame, pd.DataFrame({
        "station_id": ["1"], "timestamp": [future.strftime("%Y-%m-%dT%H:%M:%SZ")],
        "latitude": [28.6], "longitude": [77.2], "PM2.5": [None]})], ignore_index=True)
    _write_air_quality(tmp_path, frame)
    _, problems, warnings = validate_all.validate_air_quality()
    assert not any("future" in w for w in warnings)
    assert problems == []


def test_flat_zero_pm25_is_flagged_not_hidden(tmp_path):
    hours = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    frame = pd.DataFrame({"station_id": "1", "timestamp": hours.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "latitude": 28.6, "longitude": 77.2, "PM2.5": 0.0})
    _write_air_quality(tmp_path, frame)
    _, _, warnings = validate_all.validate_air_quality()
    assert any("PM2.5 == 0" in w for w in warnings)


def test_untouched_domains_report_skipped_not_passed(tmp_path):
    validate_all.DATA = tmp_path / "data"
    for d in ("fires", "era5", "cams"):
        (validate_all.DATA / d / "processed").mkdir(parents=True, exist_ok=True)
    detail, problems, warnings = validate_all.validate_untouched_domains()
    assert problems == []
    assert set(detail) == {"fires", "era5", "cams"}
    assert all(v.startswith("SKIPPED") for v in detail.values())
    assert any("no processed data" in w for w in warnings)


# --- meteorology -----------------------------------------------------------

MET_RESPONSE = {
    "hourly_units": {"time": "iso8601", "temperature_2m": "°C", "relative_humidity_2m": "%",
                     "surface_pressure": "hPa", "wind_speed_10m": "km/h", "wind_direction_10m": "°",
                     "cloud_cover": "%", "precipitation": "mm"},
    "hourly": {"time": ["2024-01-01T00:00"], "temperature_2m": [6.4], "relative_humidity_2m": [100],
               "surface_pressure": [992.5], "wind_speed_10m": [3.6], "wind_direction_10m": [287],
               "cloud_cover": [100], "precipitation": [0.0]},
}


def _write_meteo(tmp_path, frame):
    validate_all.DATA = tmp_path / "data"
    (validate_all.DATA / "meteorology" / "processed").mkdir(parents=True, exist_ok=True)
    frame.to_csv(validate_all.DATA / "meteorology" / "processed" / "meteorology_hourly.csv", index=False)


def test_meteorology_valid_passes_with_era5_independence_warning(tmp_path):
    frame = om.to_frame(MET_RESPONSE, "Delhi")
    _write_meteo(tmp_path, frame)
    _, problems, warnings = validate_all.validate_meteorology()
    assert problems == []
    assert any("not independent" in w for w in warnings)


def test_meteorology_bad_wind_conversion_is_a_problem(tmp_path):
    frame = om.to_frame(MET_RESPONSE, "Delhi")
    frame["wind_speed_10m_ms"] = 99.0  # conversion silently wrong
    _write_meteo(tmp_path, frame)
    _, problems, _ = validate_all.validate_meteorology()
    assert any("3.6" in p for p in problems)


def test_meteorology_duplicate_place_timestamp_is_a_problem(tmp_path):
    frame = om.to_frame(MET_RESPONSE, "Delhi")
    _write_meteo(tmp_path, pd.concat([frame, frame], ignore_index=True))
    _, problems, _ = validate_all.validate_meteorology()
    assert any("duplicate" in p for p in problems)


def test_meteorology_impossible_pressure_is_a_problem(tmp_path):
    frame = om.to_frame(MET_RESPONSE, "Delhi")
    frame["surface_pressure"] = 120.0
    _write_meteo(tmp_path, frame)
    _, problems, _ = validate_all.validate_meteorology()
    assert any("surface_pressure" in p for p in problems)


# --- geospatial ------------------------------------------------------------

def test_geospatial_accepts_relation_nested_geometry(tmp_path):
    """Overpass nests relation geometry under members[].geometry. A validator that
    only looks at the element top level would wrongly report no geometry."""
    validate_all.DATA = tmp_path / "data"
    folder = validate_all.DATA / "geospatial" / "raw"
    folder.mkdir(parents=True)
    (folder / "osm_boundaries.json").write_text(json.dumps({"elements": [
        {"type": "relation", "id": 1, "tags": {"name": "Ghaziabad", "admin_level": "6"},
         "members": [{"type": "way", "ref": 2, "role": "outer",
                      "geometry": [{"lat": 28.6, "lon": 77.4}, {"lat": 28.7, "lon": 77.5}]}]}]}))
    _, problems, _ = validate_all.validate_geospatial()
    assert not any("geometry" in p for p in problems), problems


def test_geospatial_reports_truly_geometryless_boundaries(tmp_path):
    validate_all.DATA = tmp_path / "data"
    folder = validate_all.DATA / "geospatial" / "raw"
    folder.mkdir(parents=True)
    (folder / "osm_boundaries.json").write_text(json.dumps({"elements": [
        {"type": "relation", "id": 1, "tags": {"name": "X"}}]}))
    _, problems, _ = validate_all.validate_geospatial()
    assert any("geometry" in p for p in problems)


def test_manifest_missing_fields_is_problem(tmp_path):
    validate_all.DATA = tmp_path / "data"
    folder = validate_all.DATA / "manifests"
    folder.mkdir(parents=True)
    (folder / "bad.json").write_text(json.dumps({"source": "x"}))
    _, problems, _ = validate_all.validate_manifests()
    assert problems


def test_crashing_check_is_reported_as_failure(tmp_path):
    result = validate_all.check("boom", lambda: 1 / 0)
    assert result["status"] == "FAIL"
    assert "ZeroDivisionError" in result["problems"][0]


def test_secrets_never_appear_in_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(validate_all, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(validate_all, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(validate_all, "check", lambda name, fn: {"name": name, "status": "PASS",
                                                                 "detail": {"rows": 0}, "problems": [], "warnings": []})
    result = {"generated_utc": "now", "status": "PASS", "failed_checks": [], "checks": [
        {"name": "x", "status": "PASS", "detail": {}, "problems": [], "warnings": []}]}
    html = validate_all.render_html(result)
    (tmp_path / "reports").mkdir(parents=True)
    (tmp_path / "reports" / "r.html").write_text(html)
    text = (tmp_path / "reports" / "r.html").read_text()
    assert "API" not in text and "apikey" not in text.lower()
