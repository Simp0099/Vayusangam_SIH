# Forecast (Previous Model Runs) — Data Dictionary

Source: **Open-Meteo Historical Forecast API** (`https://historical-forecast-api.open-meteo.com/v1/forecast`).
No API key. 10 NCR/outer-ring points, **2024-09-01 → 2026-09-30**, 182,400 hourly rows.

## Why this dataset exists

The historical-weather archive used for `meteorology_hourly.csv` is **ERA5 reanalysis — hindsight,
not a forecast**. A 72-hour forecasting system cannot be honestly evaluated on reanalysis fields,
because the reanalysis has already assimilated the outcome. The dataset audit of 2026-09-30
correctly flagged "Forecast NWP archive" as **MISSING**.

This endpoint returns **what the forecast model actually issued at the time** (previous model
runs). That is the input an operational forecast would genuinely have had, and it is what
forecast-skill evaluation must run against.

It additionally supplies **`boundary_layer_height` (PBLH) and solar radiation**, which the archive
endpoint does not serve — closing a second gap the audit listed as credential-blocked.

## ⚠️ PBLH is only available from 2024-09-01

Verified by probing month by month: `boundary_layer_height` returns **0 non-null values** for
every month before 2024-09-01 and complete data from 2024-09-01 onward (binary-searched boundary:
first non-null hour is `2024-09-01T01:00`).

Critically, **the API returns HTTP 200 and declares `"boundary_layer_height": "m"` in its units
block even when the field is entirely absent.** A request for 2024-01-01→2024-01-02 therefore
looks like a clean success and yields a silently empty column. The collector now prints a
per-variable completeness table and flags any variable that is 0% populated, and
`validate_all.py` fails an entirely-null variable rather than passing it.

Consequence: **PBLH cannot be joined to air-quality observations before 2024-09-01** without
either restricting the analysis window or sourcing PBLH from ERA5. This constrains the usable
training period and is a real limitation, not a defect to be papered over.

## Variables

Units are asserted against the API's own `hourly_units` block on every request.

| Column | Unit | Completeness |
|---|---|---|
| `temperature_2m` | °C | 100% |
| `dew_point_2m` | °C | 100% |
| `relative_humidity_2m` | % | 100% |
| `surface_pressure` | hPa | 100% |
| `wind_speed_10m` | km/h | 100% |
| `wind_speed_10m_ms` | m/s | derived, ÷3.6 |
| `wind_direction_10m` | degrees | 100% (meteorological, direction wind comes *from*) |
| `cloud_cover` | % | 100% |
| `precipitation` | mm | 100% |
| **`boundary_layer_height_m`** | m | 99.998% — min 10, **median 200**, max 5525 |
| `shortwave_radiation` | W/m² | 100% |
| `grid_lat` / `grid_lon` | ° | ERA5 grid cell actually resolved to |
| `elevation` | m | cell-centre elevation |

## PBLH sanity

The max of 5525 m is **real, not a unit error**: all 35 hours above 5000 m occur in the 07–11
UTC morning boundary-layer growth window, and every one falls in April. The diurnal median
profile is physically coherent — ~80–95 m at night, peaking at ~1200 m at 09 UTC, collapsing back
to ~85 m by midday. A genuine inversion signal is a *low* PBLH at night, which this series shows.

The validator's ceiling is therefore 8000 m, not 5000 m: a 2–5 km daytime boundary layer over the
Delhi basin in summer is normal.

Absent PBLH stays **null, never 0**. A 0 m PBLH would read as a collapsed boundary layer — a
strong inversion signal — so filling with zero would fabricate exactly the feature the project
cares about.

## Independence — do not merge blindly

`forecast_hourly.csv` (previous model runs) and `meteorology_hourly.csv` (ERA5 reanalysis) are
**different products of the same underlying model**. They are not independent observations.
Feeding both to one model as separate feature groups gives it two correlated views of one
signal.

Use the forecast archive for **forecast-input skill evaluation** (what did we know at time T?)
and the ERA5 archive for **reanalysis-based training**. Do not concatenate them.

## Reproducing

```bash
.venv/bin/python scripts/data_collection/meteorology/download_forecast.py --test
.venv/bin/python scripts/data_collection/meteorology/download_forecast.py \
    --start-date 2024-09-01 --end-date 2026-09-30
```

Size: 20 MB raw / 19 MB processed. Runtime ~34 s.
