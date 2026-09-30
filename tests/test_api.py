from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_health_and_replay():
    assert client.get("/api/health").json()["status"] == "operational"
    replay = client.get("/api/replay/delhi-winter-stagnation").json()
    assert replay["mode"] == "REPLAY"
    assert len(replay["station_forecasts"][0]["forecast"]) == 72
    point = replay["station_forecasts"][0]["forecast"][24]
    assert point["pm25_p10"] <= point["pm25_p50"] <= point["pm25_p90"]


def test_station_grid_explain_and_verification_endpoints():
    assert len(client.get("/api/stations").json()["stations"]) == 6
    assert len(client.get("/api/forecast/grid?hour=48").json()["points"]) == 6
    assert client.get("/api/explain/anand-vihar?hour=24").json()["drivers"]
    verification = client.get("/api/verification").json()
    assert verification["status"] == "VERIFICATION DATA REQUIRED"


def test_meteorology_fires_plume_and_coupling_routes():
    assert client.get("/api/met/inversion?hour=12").json()["stations"]
    assert client.get("/api/fires").json()["fires"]
    plume = client.get("/api/smoke/plume?hour=12").json()
    assert plume["particles"] and plume["hour"] == 12
    assert client.get("/api/coupling/anand-vihar").json()["steps"]


def test_whatif_request_changes_scenario_output():
    baseline = client.post("/api/whatif/smoke", json={"fire_reduction": 0}).json()
    reduced = client.post("/api/whatif/smoke", json={"fire_reduction": 80}).json()
    assert reduced["fire_reduction"] == 80
    assert reduced["station_forecasts"][0]["forecast"][30]["pm25"] < baseline["station_forecasts"][0]["forecast"][30]["pm25"]


def test_real_archive_routes_keep_source_classes_and_missing_values():
    stations = client.get("/api/data/stations").json()["stations"]
    assert len(stations) == 220
    observation = client.get("/api/data/air-quality?station_id=2860223&variable=PM2.5").json()
    assert observation["data_class"] == "observation"
    assert observation["valid_count"] == 51
    assert observation["missing_count"] == 21
    assert all(point["value"] is None for point in client.get("/api/data/air-quality?station_id=2860223&variable=NO2").json()["records"])
    weather = client.get("/api/data/meteorology?place=Delhi&product=forecast_archive&variable=boundary_layer_height_m").json()
    assert weather["data_class"] == "forecast_archive"
    assert weather["unit"] == "m"
    assert len(weather["records"]) == 72
