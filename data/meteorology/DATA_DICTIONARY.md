# Meteorology — Data Dictionary

Source: **Open-Meteo Historical Weather API** (`https://archive-api.open-meteo.com/v1/archive`).
No API key. Data is derived from **ERA5 / ERA5-Land** reanalysis — see the independence warning
below. All timestamps are **UTC**. Coordinates are the Open-Meteo grid cell returned for each
requested point (WGS84).

## Files

| File | Contents |
|---|---|
| `raw/*.json` | Immutable API responses, one per (point, window). Cached; re-runs reuse them. |
| `processed/meteorology_hourly.csv` | 120,480 rows — 5 NCR points × 24,096 hourly steps, 2024-01-01 → 2026-09-30 |

## Points

10 points. Five in the NCR core, five on the Haryana / western-UP outer ring. The outer points
were chosen by **greedy max-coverage over the real 220 OpenAQ station coordinates**, adding a
point only where it covered stations the previous points did not — not by naming cities by hand.

| Place | Requested | Grid cell | Elevation |
|---|---|---|---|
| Delhi | 28.6139, 77.2090 | 28.576, 77.187 | 214 m |
| Gurugram | 28.4595, 77.0266 | 28.436, 77.011 | 228 m |
| Noida | 28.5355, 77.3910 | 28.506, 77.406 | 200 m |
| Ghaziabad | 28.6692, 77.4538 | 28.647, 77.480 | 216 m |
| Faridabad | 28.4089, 77.3178 | 28.436, 77.318 | 207 m |
| Sonipat | 29.0272, 77.0621 | 28.998, 77.099 | 218 m |
| Hapur | 28.7256, 77.7497 | 28.717, 77.774 | 214 m |
| Ballabgarh | 28.3419, 77.3197 | 28.366, 77.333 | 206 m |
| Manesar | 28.3607, 76.9361 | 28.366, 76.924 | 248 m |
| AnandVihar_NCR | 28.6787, 77.2262 | 28.717, 77.260 | 218 m |

`grid_lat` / `grid_lon` / `elevation` are stored per row. **The grid cell is not the requested
coordinate** — Open-Meteo snaps to the nearest ERA5 cell, which can be several km away. Station
matching uses the recorded cell, not the nominal point, otherwise every reported distance would
be wrong by up to ~10 km.

### Effect of the outer ring on station coverage

| Threshold | 5 points | 10 points |
|---|---|---|
| within 10 km | 28.2% | 41.4% |
| within 20 km | 48.2% | 55.0% |
| within 35 km | 56.4% | **59.5%** |
| median distance | 22.1 km | **15.3 km** |

The remaining 89 stations are 100–405 km away (Punjab, Rajasthan, MP) and are not covered.

## Columns and units

Units are **asserted against the API's own `hourly_units` block** on every request. A mismatch
aborts the run rather than converting on an assumption.

| Column | Source unit | Final | Notes |
|---|---|---|---|
| `timestamp` | ISO8601, `timezone=UTC` | UTC | Explicitly requested as UTC, never local |
| `temperature_2m` | °C | °C | |
| `relative_humidity_2m` | % | % | |
| `surface_pressure` | hPa | hPa | |
| `wind_speed_10m` | **km/h** | km/h (retained) | Source column kept unchanged |
| `wind_speed_10m_ms` | km/h | **m/s** | Derived: `wind_speed_10m / 3.6` |
| `wind_direction_10m` | degrees | degrees | Meteorological convention (direction wind comes *from*) |
| `cloud_cover` | % | % | |
| `precipitation` | mm | mm | |
| `place` | — | — | Which of the 10 points the row belongs to |
| `grid_lat` / `grid_lon` | ° | ° | ERA5 grid cell the request resolved to (not the requested coordinate) |
| `elevation` | m | m | Cell-centre elevation |

Both wind columns are kept deliberately: the km/h value is what the source published, and the
m/s value is what the model uses. The conversion is stated rather than silently applied.

Missing values remain null. A null is "no value returned", never 0.

## ⚠️ Independence warning

Open-Meteo serves **ERA5 / ERA5-Land**. A direct ERA5 download (phase 4) is therefore **not an
independent observation** of the same quantity — it is the same underlying reanalysis. Using
both as separate feature groups gives the model two correlated copies of one signal and will
inflate apparent skill.

Decide before feature engineering:
- use Open-Meteo **or** ERA5 as the meteorological feature source, not both; or
- use ERA5 for everything, since it additionally provides PBLH, pressure levels (T925/T850 for
  inversion diagnostics) and u/v wind components, which Open-Meteo cannot supply.

Recommended: **ERA5 as the single meteorological source**, with Open-Meteo retained only as a
prototype/fallback. The ERA5 request is blocked on `~/.cdsapirc`.

## Reproducing

```bash
.venv/bin/python scripts/data_collection/meteorology/download_open_meteo.py --test
.venv/bin/python scripts/data_collection/meteorology/download_open_meteo.py \
    --start-date 2024-01-01 --end-date 2026-09-30
```

Size: 9.8 MB raw / 9.2 MB processed for the full 5-point, 2.8-year extract.
