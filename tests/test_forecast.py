"""Tests for the forecast (previous-model-run) collector and its validator.

The key case is the silent all-null variable: the API returns HTTP 200 and
declares a unit for a field it has no data for. PBLH is exactly this — it exists
only from 2024-09-01 in the historical-forecast archive.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.data_collection.meteorology import download_forecast as fc  # noqa: E402

FORECAST_RESPONSE = {
    "latitude": 28.576448, "longitude": 77.18678, "elevation": 214.0,
    "hourly_units": {"time": "iso8601", "temperature_2m": "°C", "dew_point_2m": "°C",
                     "relative_humidity_2m": "%", "surface_pressure": "hPa",
                     "wind_speed_10m": "km/h", "wind_direction_10m": "°", "cloud_cover": "%",
                     "precipitation": "mm", "boundary_layer_height": "m",
                     "shortwave_radiation": "W/m²"},
    "hourly": {"time": ["2024-09-01T00:00", "2024-09-01T01:00"],
               "temperature_2m": [27.0, 26.5], "dew_point_2m": [24.0, 23.8],
               "relative_humidity_2m": [85, 88], "surface_pressure": [1000.0, 999.8],
               "wind_speed_10m": [7.2, 6.4], "wind_direction_10m": [200, 210],
               "cloud_cover": [40, 45], "precipitation": [0.0, 0.0],
               "boundary_layer_height": [85.0, 95.0], "shortwave_radiation": [0.0, 0.0]},
}


def test_units_match_the_declared_block():
    assert fc.check_units(FORECAST_RESPONSE) == []


def test_unit_mismatch_is_detected():
    bad = {**FORECAST_RESPONSE, "hourly_units": {**FORECAST_RESPONSE["hourly_units"],
                                                 "boundary_layer_height": "km"}}
    assert any("boundary_layer_height" in m for m in fc.check_units(bad))


def test_pblh_is_present_in_the_forecast_feed():
    """PBLH is the reason this collector exists; confirm it is parsed and named."""
    frame = fc.to_frame(FORECAST_RESPONSE, "Delhi")
    assert frame.boundary_layer_height_m.iloc[0] == pytest.approx(85.0)
    assert frame.boundary_layer_height_m.notna().all()


def test_absent_pblh_stays_nan_not_zero():
    """The API declares a unit and returns 200 even when the field is empty.
    Those nulls must survive as NaN, never become 0 m (which would read as a
    collapsed boundary layer and look like a strong inversion signal)."""
    payload = {**FORECAST_RESPONSE,
               "hourly": {**FORECAST_RESPONSE["hourly"], "boundary_layer_height": [None, None]}}
    frame = fc.to_frame(payload, "Delhi")
    assert frame.boundary_layer_height_m.isna().all(), "absent PBLH must be NaN, not 0"
    # A 0 m PBLH would read as a collapsed boundary layer — a strong inversion
    # signal — so assert the literal 0 never appears in the column.
    assert not (frame.boundary_layer_height_m == 0).any()


def test_grid_cell_is_recorded():
    frame = fc.to_frame(FORECAST_RESPONSE, "Delhi")
    assert frame.grid_lat.iloc[0] == pytest.approx(28.576448)
    assert frame.elevation.iloc[0] == pytest.approx(214.0)


def test_wind_speed_converted_to_ms():
    frame = fc.to_frame(FORECAST_RESPONSE, "Delhi")
    assert frame.wind_speed_10m_ms.iloc[0] == pytest.approx(7.2 / 3.6)


def test_forecast_covers_the_same_ten_points():
    from scripts.data_collection.meteorology.download_open_meteo import NCR_POINTS
    assert set(fc.NCR_POINTS) == set(NCR_POINTS)
    assert len(fc.NCR_POINTS) == 10


# --- validator: the silent all-null case ------------------------------------

def test_validator_flags_entirely_null_pblh(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "validate_all", ROOT / "scripts" / "data_collection" / "validate_all.py")
    va = importlib.util.module_from_spec(spec)
    sys.modules["validate_all"] = va
    spec.loader.exec_module(va)
    monkeypatch.setattr(va, "DATA", tmp_path / "data")
    folder = tmp_path / "data" / "meteorology" / "processed"
    folder.mkdir(parents=True)
    pd.DataFrame({"timestamp": ["2024-01-01T00:00:00+00:00"], "place": ["Delhi"],
                  "temperature_2m": [25.0], "boundary_layer_height_m": [None],
                  "shortwave_radiation": [0.0]}).to_csv(folder / "forecast_hourly.csv", index=False)
    _, problems, _ = va.validate_forecast()
    assert any("entirely null" in p for p in problems), \
        "an all-null variable must fail, not pass as a successful download"


def test_validator_accepts_deep_but_plausible_daytime_pblh(tmp_path, monkeypatch):
    """5525 m during morning boundary-layer growth is real, not a unit error."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "validate_all2", ROOT / "scripts" / "data_collection" / "validate_all.py")
    va = importlib.util.module_from_spec(spec)
    sys.modules["validate_all2"] = va
    spec.loader.exec_module(va)
    monkeypatch.setattr(va, "DATA", tmp_path / "data")
    folder = tmp_path / "data" / "meteorology" / "processed"
    folder.mkdir(parents=True)
    pd.DataFrame({"timestamp": ["2024-09-01T09:00:00+00:00", "2024-09-01T21:00:00+00:00"],
                  "place": ["Delhi", "Delhi"], "temperature_2m": [30.0, 28.0],
                  "boundary_layer_height_m": [5525.0, 85.0],
                  "shortwave_radiation": [600.0, 0.0]}).to_csv(
        folder / "forecast_hourly.csv", index=False)
    _, problems, _ = va.validate_forecast()
    assert not any("PBLH" in p for p in problems), problems
