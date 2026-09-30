"""Tests for the shared collector helpers and the Open-Meteo collector.

No network access: the Open-Meteo fetch is exercised against a recorded,
real API response shape (units block and hourly arrays).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.data_collection import common  # noqa: E402
from scripts.data_collection.meteorology import download_open_meteo as om  # noqa: E402

# Shape captured from a live api.open-meteo.com response on 2026-09-30.
REAL_RESPONSE = {
    "latitude": 28.576448, "longitude": 77.18678, "elevation": 217.0,
    "utc_offset_seconds": 0, "timezone": "GMT",
    "hourly_units": {"time": "iso8601", "temperature_2m": "°C", "relative_humidity_2m": "%",
                     "surface_pressure": "hPa", "wind_speed_10m": "km/h", "wind_direction_10m": "°",
                     "cloud_cover": "%", "precipitation": "mm"},
    "hourly": {"time": ["2024-01-01T00:00", "2024-01-01T01:00"],
               "temperature_2m": [6.4, 10.1], "relative_humidity_2m": [100, 88],
               "surface_pressure": [992.5, 993.9], "wind_speed_10m": [3.8, 4.0],
               "wind_direction_10m": [287, 355], "cloud_cover": [100, 100],
               "precipitation": [0.0, 0.0]},
}


def test_project_root_is_the_repository_not_scripts():
    assert common.PROJECT_ROOT == ROOT
    assert (common.PROJECT_ROOT / "data").is_dir()
    assert not (common.PROJECT_ROOT / "scripts" / "data").exists(), \
        "a stray scripts/data directory means PROJECT_ROOT resolved one level too high"


def test_redact_strips_api_keys():
    url = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/VIIRS_SNPP_NRT/74,26,80,32/1/DEADBEEF1234567890"
    assert "DEADBEEF1234567890" not in common.redact(url)
    query = "https://api.openaq.org/v3/locations?api_key=SUPERSECRETVALUE&limit=1"
    assert "SUPERSECRETVALUE" not in common.redact(query)


def test_redact_keeps_non_secret_url_parts():
    out = common.redact("https://api.openaq.org/v3/sensors/1234/hours?limit=1000")
    assert "api.openaq.org" in out and "1234" in out and "1000" in out


def test_log_event_never_writes_a_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "LOG_DIR", tmp_path / "logs")
    common.log_event("firms", "fetch", "OK", 5, 1.0, "https://x/api?MAP_KEY=LEAKEDKEY123", "")
    text = (tmp_path / "logs" / "data_collection.log").read_text()
    assert "LEAKEDKEY123" not in text
    row = json.loads(text.strip())
    assert set(row) == {"timestamp", "source", "operation", "request", "status",
                        "records", "duration_s", "error"}


def test_cache_path_is_deterministic_and_query_sensitive(tmp_path):
    a = common.cache_path(tmp_path, "x", {"b": 2, "a": 1})
    b = common.cache_path(tmp_path, "x", {"a": 1, "b": 2})
    c = common.cache_path(tmp_path, "x", {"a": 2, "b": 1})
    assert a == b, "key order must not change the cache filename"
    assert a != c


def test_atomic_write_leaves_no_partial_file(tmp_path):
    target = tmp_path / "out.json"
    common.atomic_write(target, '{"ok": true}')
    assert json.loads(target.read_text())["ok"] is True
    assert list(tmp_path.glob(".*tmp")) == [], "temp file must be cleaned up"


def test_units_match_the_live_api_declaration():
    assert om.check_units(REAL_RESPONSE) == []


def test_unit_mismatch_is_detected_not_silently_converted():
    bad = json.loads(json.dumps(REAL_RESPONSE))
    bad["hourly_units"]["wind_speed_10m"] = "m/s"
    mismatches = om.check_units(bad)
    assert len(mismatches) == 1 and "wind_speed_10m" in mismatches[0]


def test_missing_unit_block_is_a_mismatch():
    assert len(om.check_units({"hourly_units": {}})) == len(om.VARIABLES)


def test_timestamps_are_utc():
    frame = om.to_frame(REAL_RESPONSE, "Delhi")
    assert str(frame.timestamp.dt.tz) == "UTC"


def test_wind_speed_converted_to_ms_and_source_kept():
    frame = om.to_frame(REAL_RESPONSE, "Delhi")
    assert frame.wind_speed_10m_ms.iloc[0] == pytest.approx(3.8 / 3.6)
    assert frame.wind_speed_10m.iloc[0] == 3.8, "the source km/h column must be retained"


def test_ncr_points_are_inside_the_target_region():
    for place, (lat, lon) in om.NCR_POINTS.items():
        assert 26 <= lat <= 33, f"{place} latitude out of NCR range"
        assert 73 <= lon <= 81, f"{place} longitude out of NCR range"


def test_ten_points_cover_the_ncr_core_and_outer_belt():
    """5 core + 5 outer points. The outer ring was chosen by greedy
    max-coverage over the real station coordinates."""
    assert len(om.NCR_POINTS) == 10
    for outer in ("Sonipat", "Hapur", "Ballabgarh", "Manesar", "AnandVihar_NCR"):
        assert outer in om.NCR_POINTS, f"{outer} outer-ring point missing"


def test_grid_cell_is_recorded_for_station_matching():
    """Stations must be matched to the ERA5 cell the request resolved to, not the
    nominal requested coordinate — the two differ by up to ~10 km."""
    frame = om.to_frame(REAL_RESPONSE, "Delhi")
    assert "grid_lat" in frame and "grid_lon" in frame
    assert frame.grid_lat.iloc[0] == pytest.approx(28.576448)
    assert frame.grid_lon.iloc[0] == pytest.approx(77.18678)
    assert "elevation" in frame


def test_missing_measurements_stay_null_not_zero():
    payload = json.loads(json.dumps(REAL_RESPONSE))
    payload["hourly"]["precipitation"] = [None, 0.0]
    frame = om.to_frame(payload, "Delhi")
    assert frame.precipitation.isna().iloc[0], "a null observation must not become 0"
