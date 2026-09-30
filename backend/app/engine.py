"""Deterministic science-inspired forecast surrogate. All outputs are replay data."""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin
from typing import Any

import numpy as np
from ml.providers.base import ModelProvider
from ml.models.pm25 import PM25Forecaster
from ml.models.ozone import OzoneForecaster
from .config import (INVERSION_ISI_THRESHOLD_C, MIXING_VC_THRESHOLD_M2S,
                     STAGNATION_VC_THRESHOLD_M2S)

HOURS = 72
SEED = 26082

STATIONS = [
    {"id": "anand-vihar", "name": "Anand Vihar", "district": "East Delhi", "lat": 28.6469, "lon": 77.3160},
    {"id": "rk-puram", "name": "R.K. Puram", "district": "South West Delhi", "lat": 28.5633, "lon": 77.1869},
    {"id": "punjabi-bagh", "name": "Punjabi Bagh", "district": "West Delhi", "lat": 28.6740, "lon": 77.1310},
    {"id": "noida-sector-62", "name": "Noida Sector 62", "district": "Gautam Buddha Nagar", "lat": 28.6270, "lon": 77.3649},
    {"id": "gurugram-sector-51", "name": "Gurugram Sector 51", "district": "Gurugram", "lat": 28.4230, "lon": 77.0730},
    {"id": "ghaziabad", "name": "Vasundhara", "district": "Ghaziabad", "lat": 28.6692, "lon": 77.3570},
]

FIRE_SEEDS = [
    {"id": "F-01", "lat": 30.72, "lon": 76.78, "frp": 48.2},
    {"id": "F-02", "lat": 30.32, "lon": 76.41, "frp": 31.5},
    {"id": "F-03", "lat": 29.82, "lon": 77.08, "frp": 19.7},
]


def derive_inversion_metrics(t925: float, t2m: float, pblh: float, wind: float, t850: float | None = None) -> dict[str, float | bool]:
    isi = round(t925 - t2m, 2)
    vc = round(max(pblh, 0) * max(wind, 0), 1)
    return {"isi": isi, "isi850": round(t850 - t2m, 2) if t850 is not None else None, "pblh": round(pblh), "vc": vc, "stagnant": vc < STAGNATION_VC_THRESHOLD_M2S, "inversion_active": isi > INVERSION_ISI_THRESHOLD_C}


def derive_stagnation_flag(vc: float, threshold: float = STAGNATION_VC_THRESHOLD_M2S) -> bool:
    return vc < threshold


def derive_inversion_duration(isi_series: list[float], threshold: float = INVERSION_ISI_THRESHOLD_C) -> int:
    duration = 0
    for value in reversed(isi_series):
        if value <= threshold:
            break
        duration += 1
    return duration


def aqi_from_pm25(pm25: float) -> int:
    # India CPCB-style PM2.5 sub-index interpolation, used as a prototype proxy.
    # A regulatory AQI requires all available pollutant sub-indices and station data.
    bands = [(0, 30, 0, 50), (30, 60, 51, 100), (60, 90, 101, 200), (90, 120, 201, 300), (120, 250, 301, 400), (250, 500, 401, 500)]
    c = max(0, pm25)
    for clo, chi, ilo, ihi in bands:
        if clo <= c <= chi:
            return round((ihi - ilo) / (chi - clo) * (c - clo) + ilo)
    return 500


def category(aqi: int) -> str:
    if aqi <= 50: return "Good"
    if aqi <= 100: return "Satisfactory"
    if aqi <= 200: return "Moderate"
    if aqi <= 300: return "Poor"
    if aqi <= 400: return "Very Poor"
    return "Severe"


def smoke_simulation(hours: int = HOURS, fire_reduction: float = 0) -> dict[str, Any]:
    """Simple deterministic Lagrangian advection/diffusion; SII is relative, not emissions."""
    rng = np.random.default_rng(SEED)
    particles: list[dict[str, float | int]] = []
    grids = []
    frames = []
    for hour in range(hours):
        h_particles = []
        for i, fire in enumerate(FIRE_SEEDS):
            # Wind advects generally east/southeast; random walk broadens the plume.
            age = max(hour - i * 3, 0)
            if hour < i * 3:
                continue
            count = max(3, round(fire["frp"] / 6))
            for n in range(count):
                lat = fire["lat"] - age * 0.018 + rng.normal(0, 0.035 + age * 0.0012)
                lon = fire["lon"] + age * 0.037 + rng.normal(0, 0.04 + age * 0.0012)
                intensity = (fire["frp"] / 50) * np.exp(-age / 34) * (1 - fire_reduction / 100)
                h_particles.append({"lat": round(float(lat), 4), "lon": round(float(lon), 4), "intensity": round(float(intensity), 3), "age": age, "fire": i})
        particles = h_particles
        frames.append(h_particles)
        grids.append({"hour": hour, "sii": round(float(sum(p["intensity"] for p in particles) / max(len(FIRE_SEEDS), 1)), 3)})
    eta = [{"station_id": s["id"], "hours": (18 if s["lon"] > 77.25 else 25 if s["lat"] > 28.65 else 34)} for s in STATIONS]
    return {"particles": particles, "particle_frames": frames, "sii_grid": grids, "eta": eta, "fires": FIRE_SEEDS, "label": "Smoke Influence Index — relative transport indicator"}


@dataclass
class SurrogateModelProvider(ModelProvider):
    """Demo surrogate. Interface is pluggable; no training or validation claim is made."""
    name: str = "SurrogateModelProvider"
    version: str = "v0.3-demo"

    def rollout(self, fire_reduction: float = 0) -> dict[str, Any]:
        hours = np.arange(HOURS)
        initial = np.array([164, 142, 151, 158, 126, 147], dtype=float)
        station_data = []
        smoke = smoke_simulation(fire_reduction=fire_reduction)
        pm_model = PM25Forecaster(demo_mode=True).fit_demo_fixture()
        o3_model = OzoneForecaster()
        for j, station in enumerate(STATIONS):
            pm = np.zeros(HOURS + 1); o3 = np.zeros(HOURS + 1); no2 = np.zeros(HOURS + 1)
            pm_uncoupled = np.zeros(HOURS + 1)
            pm[0] = initial[j]; pm_uncoupled[0] = initial[j]; o3[0] = 29 + j * 1.2; no2[0] = 34 + j * 2
            series = []
            for k, hour in enumerate(hours):
                # Diurnal NWP + a winter stagnation event, followed by daytime mixing.
                phase = (hour % 24) / 24 * 2 * np.pi
                t2m = 11 + 5 * np.sin(phase - 1.2) + 0.4 * np.sin(hour / 14)
                t925 = t2m + 4.4 + 1.4 * np.cos(phase) * (0.65 + 0.35 * np.cos(hour / 19))
                pblh = 260 + 420 * max(0, np.sin(phase - 0.8)) + 80 * np.sin(hour / 11)
                wind = 1.25 + 0.55 * (1 + np.sin(phase + 0.5)) / 2
                metrics = derive_inversion_metrics(t925, t2m, pblh, wind, t2m + 7.3)
                smoke_value = smoke["sii_grid"][k]["sii"] * (0.75 if station["lat"] > 28.65 else 0.58)
                # Explicit two-way path: previous PM modifies met, corrected met feeds next PM step.
                aerosol_feedback = min(pm[k] / 260, 1) * 0.22
                corrected_pblh = pblh * (1 - aerosol_feedback * 0.24)
                corrected_t2m = t2m - aerosol_feedback * 0.35
                corrected_vc = corrected_pblh * wind
                corrected_isi = t925 - corrected_t2m
                accumulation = max(0, (STAGNATION_VC_THRESHOLD_M2S - corrected_vc) / STAGNATION_VC_THRESHOLD_M2S) * 2.7 + max(0, corrected_isi - INVERSION_ISI_THRESHOLD_C) * 0.45
                daytime_mix = max(0, (corrected_vc - MIXING_VC_THRESHOLD_M2S) / MIXING_VC_THRESHOLD_M2S) * 1.8
                raw_vc = pblh * wind
                raw_accumulation = max(0, (STAGNATION_VC_THRESHOLD_M2S - raw_vc) / STAGNATION_VC_THRESHOLD_M2S) * 2.7 + max(0, metrics["isi"] - INVERSION_ISI_THRESHOLD_C) * .45
                raw_daytime_mix = max(0, (raw_vc - MIXING_VC_THRESHOLD_M2S) / MIXING_VC_THRESHOLD_M2S) * 1.8
                # A bounded surrogate recurrence, not a calibrated concentration model.
                physics_next = pm[k] + accumulation + smoke_value * 0.44 - daytime_mix - 0.78
                pm_uncoupled[k + 1] = np.clip(pm_uncoupled[k] + raw_accumulation + smoke_value * .44 - raw_daytime_mix - .78, 18, 380)
                model_features = np.array([pm[k], corrected_t2m, 68, wind, 250, corrected_pblh, corrected_isi, corrected_vc, smoke_value, hour % 24, 15, 1, o3[k], no2[k]])
                model_p50 = float(pm_model.predict(model_features)[0])
                pm[k + 1] = np.clip(.75 * physics_next + .25 * model_p50, 18, 380)
                radiation = max(0, np.sin(phase - 0.6))
                o3[k + 1] = o3_model.predict({"previous_o3": o3[k], "nox": no2[k], "temperature": corrected_t2m, "radiation": radiation, "pblh": corrected_pblh, "humidity": 68, "wind": wind, "hour": hour % 24, "season": 1})
                no2[k + 1] = np.clip(34 + 6 * np.cos(phase) + j * 1.3, 10, 80)
                series.append({
                    "hour": int(hour), "pm25": round(float(pm[k]), 1), "pm10": round(float(pm[k] * 1.65), 1),
                    "pm25_p10": round(float(max(0, pm[k] - max(8, pm[k] * .12))), 1), "pm25_p50": round(float(pm[k]), 1), "pm25_p90": round(float(pm[k] + max(10, pm[k] * .16)), 1),
                    "o3": round(float(o3[k]), 1), "no2": round(float(no2[k]), 1), "aqi": aqi_from_pm25(float(pm[k])),
                    "isi": round(float(corrected_isi), 2), "isi850": metrics["isi850"], "pblh": round(float(corrected_pblh)),
                    "vc": round(float(corrected_vc)), "wind": round(float(wind), 2), "temperature": round(float(corrected_t2m), 1),
                    "smoke": round(float(smoke_value), 2), "raw_pblh": round(float(pblh)), "raw_temperature": round(float(t2m), 1),
                    "uncoupled_pm25": round(float(pm_uncoupled[k]), 1),
                    "drivers": {"inversion": round(float(min(1, max(0, (corrected_isi - 1) / 6))), 2), "ventilation": round(float(min(1, max(0, 1 - corrected_vc / 1800))), 2), "smoke": round(float(min(1, smoke_value / 3)), 2)}
                })
            station_data.append({**station, "forecast": series})
        return {"episode": "Delhi Winter Stagnation — Replay", "mode": "REPLAY", "data_status": "DEMO / REPLAY DATA", "valid_time": "2026-01-15T22:00:00+05:30", "provider": self.name, "model_version": self.version, "station_forecasts": station_data, "smoke": smoke, "coupled_steps": HOURS, "fire_reduction": fire_reduction}


def get_replay() -> dict[str, Any]:
    return SurrogateModelProvider().rollout()
