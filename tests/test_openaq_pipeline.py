from datetime import date

import httpx
import json
import pandas as pd
import pytest

from scripts.data_collection.openaq import common
from scripts.data_collection.openaq import process_openaq, validate_openaq


@pytest.mark.parametrize(
    ("name", "expected"),
    [("pm25", "PM2.5"), ("PM2.5", "PM2.5"), ("nitrogen dioxide", "NO2"),
     ("NOx", "NOx"), ("wind speed", "wind_speed"), ("relativeHumidity", "relative_humidity")],
)
def test_parameter_names_are_canonical_without_conflating_nox(name, expected):
    assert common.normalize_parameter(name) == expected


def test_no2_and_nox_are_separate_parameters():
    assert common.normalize_parameter("NO2") == "NO2"
    assert common.normalize_parameter("NOx") == "NOx"


@pytest.mark.parametrize(
    ("variable", "unit", "value", "expected"),
    [("PM2.5", "mg/m³", 0.025, 25.0), ("O3", "ppm", 0.04, 40.0),
     ("temperature", "°F", 68, 20.0), ("relative_humidity", "fraction", 0.5, 50.0),
     ("wind_speed", "km/h", 36, 10.0), ("wind_direction", "degrees", 359, 359.0)],
)
def test_known_units_are_normalized(variable, unit, value, expected):
    normalized, _unit, issue = common.normalize_value(variable, unit, value)
    assert normalized == pytest.approx(expected)
    assert issue is None


def test_unsupported_units_and_invalid_values_stay_missing():
    assert common.normalize_value("NO2", "µg/m³", 30)[2] == "unsupported_unit"
    assert common.normalize_value("PM10", "µg/m³", -1)[2] == "negative_value"
    assert common.normalize_value("PM10", "µg/m³", None) == (None, "µg/m³", None)


def test_month_chunks_cover_inclusive_dates_without_gaps():
    assert list(common.month_chunks(date(2024, 1, 31), date(2024, 3, 1))) == [
        (date(2024, 1, 31), date(2024, 2, 1)),
        (date(2024, 2, 1), date(2024, 3, 1)),
        (date(2024, 3, 1), date(2024, 3, 2)),
    ]


def test_openaq_hourly_period_timestamp_is_read_from_nested_period():
    row = {"period": {"datetimeFrom": {"utc": "2026-09-28T00:30:00Z"}}, "value": 12.0}
    assert common.timestamp_utc(row) == "2026-09-28T00:00:00Z"


def test_district_mapping_only_uses_explicit_fields_or_documented_aliases():
    assert common.district_from_location({"locality": "Noida"}) == ("Gautam Buddha Nagar", "explicit locality-to-district alias")
    assert common.district_from_location({"locality": "Delhi"}) == (None, None)
    assert common.district_from_location({"district": {"name": "South Delhi"}}) == ("South Delhi", "openaq:district")


def test_pagination_and_raw_response_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "PAGE_LIMIT", 2)
    requested_pages = []

    def handler(request):
        assert request.headers.get("X-API-Key") == "test-key"
        page = int(request.url.params["page"])
        requested_pages.append(page)
        rows = [{"id": page * 2 - 1}, {"id": page * 2}] if page == 1 else [{"id": 3}]
        return httpx.Response(200, json={"meta": {"found": 3}, "results": rows})

    client = common.OpenAQClient(key="test-key")
    client.client.close()
    client.client = httpx.Client(base_url=common.API_BASE, headers={"X-API-Key": "test-key"}, transport=httpx.MockTransport(handler))
    try:
        result = list(common.paged_get(client, "/locations", {"iso": "IN"}, tmp_path, "locations"))
        assert [row["id"] for row in result] == [1, 2, 3]
        assert requested_pages == [1, 2]
        assert len(list(tmp_path.glob("*.json"))) == 2
        # Second pass reads both immutable raw snapshots without making another request.
        assert len(list(common.paged_get(client, "/locations", {"iso": "IN"}, tmp_path, "locations"))) == 3
        assert requested_pages == [1, 2]
    finally:
        client.close()


def test_rate_limit_retry_uses_openaq_reset_header(tmp_path, monkeypatch):
    calls = []
    sleeps = []

    def handler(_request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"x-ratelimit-reset": "1", "x-ratelimit-remaining": "0"}, json={})
        return httpx.Response(200, headers={"x-ratelimit-remaining": "10", "x-ratelimit-reset": "60"}, json={"results": []})

    monkeypatch.setattr(common.time, "sleep", sleeps.append)
    client = common.OpenAQClient(key="test-key")
    client.client.close()
    client.client = httpx.Client(base_url=common.API_BASE, transport=httpx.MockTransport(handler))
    try:
        payload, cached = client.get("/parameters", {"limit": 1}, tmp_path, "parameters")
        assert payload == {"results": []}
        assert not cached
        assert len(calls) == 2
        assert sleeps == [1.0]
    finally:
        client.close()


def test_processor_and_validator_on_temporary_fixture(tmp_path, monkeypatch, capsys):
    """Exercise the raw→wide→quality→validation path without creating project data."""
    data_dir = tmp_path / "air_quality"
    raw_dir = data_dir / "raw"
    (raw_dir / "hours").mkdir(parents=True)
    metadata = pd.DataFrame([{
        "station_id": 77, "station_name": "Fixture station", "latitude": 28.6,
        "longitude": 77.2, "district": None, "provider": "Fixture provider",
    }])
    metadata.to_csv(data_dir / "station_metadata.csv", index=False)
    pd.DataFrame([{
        "sensor_id": 501, "station_id": 77, "parameter": "PM2.5", "original_unit": "µg/m³",
        "selected_for_variable": True,
    }]).to_csv(data_dir / "sensor_metadata.csv", index=False)
    pd.DataFrame([{
        "station_id": 77, "station_name": "Fixture station", "latitude": 28.6,
        "longitude": 77.2, "provider": "Fixture provider", "has_pm25": True,
    }]).to_csv(data_dir / "station_availability.csv", index=False)
    (data_dir / "collection_manifest.json").write_text(json.dumps({
        "requested_start_date": "2024-01-01", "requested_end_date": "2024-01-01",
        "downloaded_station_ids": [77],
    }))
    (raw_dir / "hours" / "sensor-501-202401_fixture.json").write_text(json.dumps({"results": [
        {"datetimeFrom": {"utc": "2024-01-01T00:00:00Z"}, "value": 12.5},
        {"datetimeFrom": {"utc": "2024-01-01T01:00:00Z"}, "value": 15.0},
    ]}))
    monkeypatch.setattr(process_openaq, "DATA_DIR", data_dir)
    monkeypatch.setattr(process_openaq, "RAW_DIR", raw_dir)
    assert process_openaq.main() == 0
    hourly = pd.read_csv(data_dir / "air_quality_hourly.csv")
    assert len(hourly) == 24
    assert hourly.loc[0, "PM2.5"] == pytest.approx(12.5)
    assert hourly.loc[1, "PM2.5"] == pytest.approx(15.0)
    assert pd.isna(hourly.loc[2, "PM2.5"])
    assert hourly.loc[0, "source_provider"] == "Fixture provider"
    assert hourly["timestamp"].str.endswith("Z").all()
    quality = pd.read_csv(data_dir / "data_quality_report.csv")
    pm_row = quality[(quality.record_type == "station_variable") & (quality.variable == "PM2.5")].iloc[0]
    assert pm_row.observation_count == 2
    assert pm_row.missing_percentage == pytest.approx(91.667)

    monkeypatch.setattr(validate_openaq, "DATA_DIR", data_dir)
    assert validate_openaq.main() == 0
    assert "Validation: PASSED" in capsys.readouterr().out
