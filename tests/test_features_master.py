"""Tests for feature engineering and the master-dataset build.

The master build is exercised on a synthetic FIXTURE in tmp_path, never on
project data, so no real observation is ever fabricated into a real output file.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "build_features", ROOT / "scripts" / "data_collection" / "build_features.py")
bf = importlib.util.module_from_spec(spec)
sys.modules["build_features"] = bf
spec.loader.exec_module(bf)

spec2 = importlib.util.spec_from_file_location(
    "build_master", ROOT / "scripts" / "data_collection" / "build_master.py")
bm = importlib.util.module_from_spec(spec2)
sys.modules["build_master"] = bm
spec2.loader.exec_module(bm)


def hourly(n, start="2024-01-01"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


# --- time features ---------------------------------------------------------

def test_hour_is_cyclic_so_midnight_is_not_a_discontinuity():
    ts = pd.Series(hourly(48))
    f = bf.time_features(ts)
    assert f.hour_sin.iloc[0] == pytest.approx(0.0, abs=1e-6)
    assert f.hour_cos.iloc[0] == pytest.approx(1.0, abs=1e-6)
    # 23:00 and 00:00 must be adjacent on the circle, not far apart.
    assert f.hour_sin.iloc[23] == pytest.approx(f.hour_sin.iloc[24], abs=0.27)


def test_time_features_are_utc():
    f = bf.time_features(pd.Series(hourly(24)))
    assert (f.hour == pd.Series(range(24), dtype="float32")).all()


# --- wind components -------------------------------------------------------

def test_wind_components_use_meteorological_from_convention():
    """Wind FROM the north (0 deg) at 10 m/s must blow toward the south:
    u (east) = 0, v (north) = -10. The minus signs are the classic silent bug."""
    frame = pd.DataFrame({"wind_speed_10m_ms": [10.0], "wind_direction_10m": [0.0]})
    out = bf.wind_components(frame)
    assert out.u_wind.iloc[0] == pytest.approx(0.0, abs=1e-6)
    assert out.v_wind.iloc[0] == pytest.approx(-10.0, abs=1e-6)


def test_wind_from_east_blows_westward():
    frame = pd.DataFrame({"wind_speed_10m_ms": [5.0], "wind_direction_10m": [90.0]})
    out = bf.wind_components(frame)
    assert out.u_wind.iloc[0] == pytest.approx(-5.0, abs=1e-6)
    assert out.v_wind.iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_wind_direction_360_wraps_to_zero():
    a = bf.wind_components(pd.DataFrame({"wind_speed_10m_ms": [3.0], "wind_direction_10m": [0.0]}))
    b = bf.wind_components(pd.DataFrame({"wind_speed_10m_ms": [3.0], "wind_direction_10m": [360.0]}))
    assert a.u_wind.iloc[0] == pytest.approx(b.u_wind.iloc[0])
    assert a.v_wind.iloc[0] == pytest.approx(b.v_wind.iloc[0])


# --- PM2.5 lags ------------------------------------------------------------

def _station_frame(values):
    return pd.DataFrame({"station_id": 1, "timestamp": hourly(len(values)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "PM2.5": values})


def test_lags_are_per_station_and_correctly_offset():
    out, _ = bf.add_pm25_lags(_station_frame(list(range(30, 60))))
    # Row i holds value 30+i, so t-1h at row 5 is row 4 (34) and t-3h is row 2 (32).
    assert out["PM2.5_t-1h"].iloc[5] == 34
    assert out["PM2.5_t-3h"].iloc[5] == 32
    # t-24h at row 25 is row 1, which holds 31.
    assert out["PM2.5_t-24h"].iloc[25] == 31
    assert out["PM2.5_t-24h"].iloc[24] == 30
    # The first 24 rows cannot have a 24h lag: they must be NaN, never wrapped.
    assert out["PM2.5_t-24h"].iloc[:24].isna().all()


def test_lag_of_missing_hour_stays_missing_not_filled():
    values = [10.0] * 10
    values[4] = np.nan
    out, _ = bf.add_pm25_lags(_station_frame(values))
    assert pd.isna(out["PM2.5_t-1h"].iloc[5]), "a lag of a missing hour must be NaN, not back-filled"


def test_72h_target_is_shifted_forward_and_is_not_a_lag():
    out, _ = bf.add_pm25_lags(_station_frame(list(range(200))))
    assert out["target_PM2.5_t+72h"].iloc[0] == 72
    assert out["target_PM2.5_t+72h"].iloc[-1] is np.nan or pd.isna(out["target_PM2.5_t+72h"].iloc[-1])
    assert "PM2.5_t-72h" not in out.columns


def test_lags_do_not_leak_across_stations():
    frame = pd.concat([_station_frame([1.0] * 5),
                       _station_frame([100.0] * 5).assign(station_id=2)], ignore_index=True)
    out, _ = bf.add_pm25_lags(frame)
    first = out[out.station_id == 1]
    assert first["PM2.5_t-1h"].iloc[1] == 1.0, "station 1's lag must not read station 2's value"


# --- master alignment ------------------------------------------------------

def test_master_refuses_a_sample_rather_than_merging_it(monkeypatch, tmp_path):
    """A 2-day sample must block the build, not silently become a master dataset."""
    (tmp_path / "air_quality").mkdir(parents=True)
    pd.DataFrame({"station_id": 1, "timestamp": hourly(48).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "latitude": 28.6, "longitude": 77.2, "PM2.5": 50.0}).to_csv(
        tmp_path / "air_quality" / "air_quality_hourly.csv", index=False)
    monkeypatch.setattr(bm, "AIRQ", tmp_path / "air_quality" / "air_quality_hourly.csv")
    monkeypatch.setattr(bm, "METEO", tmp_path / "missing_met.csv")
    monkeypatch.setattr(bm, "MASTER_DIR", tmp_path / "master")
    # main() parses argv; hand it an explicit empty list so it does not consume
    # pytest's own command-line arguments.
    monkeypatch.setattr(bm.argparse.ArgumentParser, "parse_args", lambda self, *a, **k: type("A", (), {"build": False})())
    assert bm.main() == 3, "must block on sample-sized air-quality coverage"


def test_alignment_is_documented_not_implicit():
    """Every merge parameter the brief requires must be stated as a named field."""
    for key in ("grain", "time_zone", "spatial_matching", "max_spatial_distance_km",
                "max_temporal_gap_hours", "interpolation", "merge_type", "fill_policy"):
        assert key in bm.ALIGNMENT, f"{key} must be stated explicitly"
    assert bm.ALIGNMENT["interpolation"].startswith("NONE")
    assert bm.ALIGNMENT["fill_policy"].startswith("missing stays null")
    assert bm.ALIGNMENT["max_temporal_gap_hours"] == 0
    assert bm.ALIGNMENT["open_questions"], "consequential open decisions must be surfaced"
    # Both settled choices must carry their reasoning, not just a value.
    for key in ("nearest_vs_bilinear", "distance_cutoff_km"):
        assert len(bm.ALIGNMENT["decisions"][key]) > 80, f"{key} needs a stated rationale"


def test_distance_cutoff_matches_the_observed_bimodal_distribution():
    """The 35 km cut-off came from the real station coordinates: 123 of 220 are
    inside it and the rest are 100+ km out. Guard against silent drift."""
    assert bm.ALIGNMENT["max_spatial_distance_km"] == 35.0
    assert bm.ALIGNMENT["spatial_matching"].startswith("nearest")


def test_haversine_is_correct_for_a_known_distance():
    # Delhi (28.6139, 77.2090) to Gurugram (28.4595, 77.0266) is roughly 26 km.
    d = bm.haversine_km(28.6139, 77.2090, 28.4595, 77.0266)
    assert 24 < float(d) < 29


def test_haversine_is_zero_for_identical_points():
    assert float(bm.haversine_km(28.6, 77.2, 28.6, 77.2)) == pytest.approx(0.0, abs=1e-9)
