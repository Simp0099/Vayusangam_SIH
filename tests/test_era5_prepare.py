"""Tests for the ERA5 preparation script (schema + credential checks).

The live CDS schema is probed through a stubbed transport, so these tests never
touch the network. They assert that the script refuses to proceed when a
requested variable is not in the dataset, rather than requesting a name that
does not exist.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "prepare_era5", ROOT / "scripts" / "data_collection" / "era5" / "prepare_era5.py")
prepare_era5 = importlib.util.module_from_spec(spec)
sys.modules["prepare_era5"] = prepare_era5
spec.loader.exec_module(prepare_era5)


def _process_response(variables: list[str]) -> dict:
    return {"inputs": {"variable": {"schema": {"items": {"enum": variables}}}}}


@pytest.fixture
def stub_cds(monkeypatch):
    def handler(request):
        if "single-levels" in str(request.url):
            return httpx.Response(200, json=_process_response(
                ["2m_temperature", "2m_dewpoint_temperature", "10m_u_component_of_wind",
                 "10m_v_component_of_wind", "surface_pressure", "mean_sea_level_pressure",
                 "boundary_layer_height"]))
        return httpx.Response(200, json=_process_response(["temperature", "geopotential"]))

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(prepare_era5.httpx, "Client", fake_client)


def test_all_requested_variables_exist_in_the_schema(stub_cds):
    confirmed, problems = prepare_era5.verify_schema()
    assert problems == []
    assert len(confirmed) == len(prepare_era5.SINGLE_LEVELS) + len(prepare_era5.PRESSURE_LEVELS)


def test_invented_variable_name_is_rejected(monkeypatch):
    """A name not in the real enum must be reported, never requested."""
    def handler(request):
        if "single-levels" in str(request.url):
            return httpx.Response(200, json=_process_response(["2m_temperature"]))
        return httpx.Response(200, json=_process_response(["temperature"]))

    real_client = httpx.Client
    monkeypatch.setattr(prepare_era5.httpx, "Client",
                        lambda *a, **k: real_client(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    _, problems = prepare_era5.verify_schema()
    assert problems, "missing variables must be reported"
    assert any("boundary_layer_height" in p for p in problems)


def test_era5_area_order_is_north_west_south_east():
    """ERA5 `area` is [N,W,S,E] — the reverse-reading trap that would silently
    request the wrong hemisphere if the order were assumed."""
    assert prepare_era5.ERA5_AREA == [31, 73, 27, 80]
    assert prepare_era5.ERA5_AREA[0] > prepare_era5.ERA5_AREA[2]   # north > south
    assert prepare_era5.ERA5_AREA[1] < prepare_era5.ERA5_AREA[3]   # west < east


def test_region_covers_delhi_ncr():
    r = prepare_era5.REGION
    assert r["south"] < 28.6 < r["north"]
    assert r["west"] < 77.2 < r["east"]


def test_missing_cdsapirc_is_reported_with_instructions(monkeypatch, tmp_path):
    monkeypatch.setattr(prepare_era5, "CDS_CONFIG", tmp_path / "nope")
    ok, message = prepare_era5.check_config()
    assert not ok
    assert "cds.climate.copernicus.eu" in message
    assert "uid" in message, "must warn that the legacy uid: field is rejected"


def test_legacy_uid_field_is_flagged(monkeypatch, tmp_path):
    cfg = tmp_path / ".cdsapirc"
    cfg.write_text("url: https://cds.climate.copernicus.eu/api\nuid: 12345\nkey: abc\n")
    monkeypatch.setattr(prepare_era5, "CDS_CONFIG", cfg)
    ok, message = prepare_era5.check_config()
    assert ok
    assert "uid" in message and "WARNING" in message
