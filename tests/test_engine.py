from backend.app.engine import (SurrogateModelProvider, aqi_from_pm25, derive_inversion_duration,
                                derive_inversion_metrics, derive_stagnation_flag, smoke_simulation)
from ml.models.pm25 import PM25Forecaster, FEATURES


def test_aqi_proxy_categories_have_expected_order():
    assert aqi_from_pm25(5) < aqi_from_pm25(25) < aqi_from_pm25(80)
    assert aqi_from_pm25(30) == 50
    assert aqi_from_pm25(60) == 100


def test_inversion_and_ventilation_calculations():
    result = derive_inversion_metrics(t925=8.0, t2m=3.2, pblh=280, wind=1.5, t850=11)
    assert result["isi"] == 4.8
    assert result["isi850"] == 7.8
    assert result["vc"] == 420
    assert result["stagnant"] is True
    assert result["inversion_active"] is True


def test_stagnation_threshold_and_inversion_duration():
    assert derive_stagnation_flag(649)
    assert not derive_stagnation_flag(650)
    assert derive_inversion_duration([1.0, 3.0, 4.0, 4.5]) == 3
    assert derive_inversion_duration([3.0, 2.0, 4.0]) == 1


def test_plume_advects_eastward_and_decays():
    smoke = smoke_simulation()
    assert smoke["particles"]
    assert smoke["label"].startswith("Smoke Influence Index")
    assert smoke["sii_grid"][3]["sii"] > smoke["sii_grid"][70]["sii"]
    # Source particles begin west; later advected particles sit farther east.
    particles = smoke["particles"]
    assert sum(p["lon"] for p in particles) / len(particles) > 77


def test_coupled_rollout_has_72_steps_and_two_way_response():
    provider = SurrogateModelProvider()
    base = provider.rollout(0)
    reduced = provider.rollout(70)
    assert base["coupled_steps"] == 72
    assert all(len(s["forecast"]) == 72 for s in base["station_forecasts"])
    assert base["station_forecasts"][0]["forecast"][20]["pblh"] < base["station_forecasts"][0]["forecast"][20]["raw_pblh"]
    base_pm = base["station_forecasts"][0]["forecast"][30]["pm25"]
    reduced_pm = reduced["station_forecasts"][0]["forecast"][30]["pm25"]
    assert reduced_pm < base_pm


def test_pm25_model_exposes_ordered_quantiles():
    row = [120, 12, 65, 1.2, 270, 280, 4.2, 420, .7, 2, 15, 1, 30, 38]
    X = [row, [x + 1 for x in row]]
    model = PM25Forecaster().fit(X, [130, 132])
    pred = model.predict_quantiles(row)
    assert len(FEATURES) == 14
    assert pred[.1][0] <= pred[.5][0] <= pred[.9][0]
