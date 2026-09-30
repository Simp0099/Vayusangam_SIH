from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

from .engine import STATIONS, SurrogateModelProvider, derive_inversion_metrics, get_replay, smoke_simulation
from . import data as source_data

app = FastAPI(title="VayuSangam API", version="0.3.0", description="Replay-first coupled air-weather prototype")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
_cache = get_replay()


class WhatIfRequest(BaseModel):
    fire_reduction: float = Field(ge=0, le=100)


@app.get("/api/health")
def health():
    return {"status": "operational", "mode": "REPLAY", "provider": "SurrogateModelProvider", "steps": 72}


@app.get("/api/stations")
def stations():
    return {"stations": STATIONS, "data_status": "DEMO / REPLAY DATA"}


@app.get("/api/replay/{episode}")
def replay(episode: str):
    return _cache


@app.get("/api/forecast/station/{station_id}")
def station_forecast(station_id: str):
    match = next((s for s in _cache["station_forecasts"] if s["id"] == station_id), None)
    if not match:
        raise HTTPException(404, "Station not found")
    return match


@app.get("/api/forecast/grid")
def forecast_grid(hour: int = 0):
    hour = max(0, min(71, hour))
    return {"hour": hour, "points": [{"id": s["id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], **s["forecast"][hour]} for s in _cache["station_forecasts"]], "data_status": "DEMO / REPLAY DATA"}


@app.get("/api/met/inversion")
def inversion(hour: int = 0):
    hour = max(0, min(71, hour))
    return {"hour": hour, "stations": [{"id": s["id"], "name": s["name"], **{k: s["forecast"][hour][k] for k in ("isi", "isi850", "pblh", "vc")}} for s in _cache["station_forecasts"]], "status": "PROTOTYPE"}


@app.get("/api/fires")
def fires():
    return {"fires": _cache["smoke"]["fires"], "status": "DEMO / REPLAY DATA"}


@app.get("/api/smoke/plume")
def plume(hour: int = 24):
    smoke = _cache["smoke"]
    idx = max(0, min(71, hour))
    return {"fires": smoke["fires"], "particles": smoke["particle_frames"][idx], "sii_grid": smoke["sii_grid"], "eta": smoke["eta"], "hour": idx, "label": smoke["label"]}


@app.get("/api/coupling/{station_id}")
def coupling(station_id: str):
    station = next((s for s in _cache["station_forecasts"] if s["id"] == station_id), None)
    if not station:
        raise HTTPException(404, "Station not found")
    return {"station_id": station_id, "steps": station["forecast"], "feedback_path": "previous PM2.5 → aerosol feedback → corrected meteorology → next pollution step", "status": "PROTOTYPE SURROGATE"}


@app.get("/api/explain/{station_id}")
def explain(station_id: str, hour: int = 24):
    station = next((s for s in _cache["station_forecasts"] if s["id"] == station_id), None)
    if not station:
        raise HTTPException(404, "Station not found")
    point = station["forecast"][max(0, min(71, hour))]
    return {"station_id": station_id, "hour": hour, "label": "Model-derived drivers — deterministic demo logic", "drivers": point["drivers"], "briefing": "AQI is expected to change as inversion strength and ventilation evolve. Relative smoke transport contributes to projected PM2.5 in this replay scenario."}


@app.post("/api/whatif/smoke")
def whatif(payload: WhatIfRequest):
    return SurrogateModelProvider().rollout(payload.fire_reduction)


@app.get("/api/verification")
def verification():
    return {"status": "VERIFICATION DATA REQUIRED", "message": "Connect verified historical data to populate scientific skill metrics. Demo mode does not generate scientific accuracy claims.", "models": ["Coupled", "Uncoupled", "Persistence", "CAMS"], "horizons": [24, 48, 72], "metrics": ["MAE", "RMSE", "Bias", "F1 high-AQI", "Interval coverage"]}


@app.get("/api/admin/health")
def admin_health():
    return {"status": "operational", "providers": {"demo": "implemented", "CPCB": "planned", "FIRMS": "planned", "CAMS": "planned", "WRF-Chem": "planned", "NCUM": "planned"}}


@app.get("/api/data/stations")
def source_stations():
    return {"source": "OpenAQ station metadata", "stations": source_data.stations()}


@app.get("/api/data/air-quality")
def source_air_quality(
    station_id: str = Query(min_length=1, max_length=32),
    variable: str = Query(default="PM2.5"),
    hours: int = Query(default=72, ge=1, le=2160),
):
    try:
        return source_data.air_quality(station_id, variable, hours)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/data/meteorology")
def source_meteorology(
    place: str = Query(min_length=1, max_length=64),
    product: str = Query(default="forecast_archive"),
    variable: str = Query(default="boundary_layer_height_m"),
    hours: int = Query(default=72, ge=1, le=2160),
):
    try:
        return source_data.meteorology(place, product, variable, hours)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/data/status")
def source_status():
    return source_data.data_status()


if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
