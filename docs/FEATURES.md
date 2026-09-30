# VayuSangam — Feature Engineering & Master Dataset

## Build order

```bash
# features (safe: derives from whatever processed data exists)
.venv/bin/python scripts/data_collection/build_features.py

# master dataset — inspect the summary first
.venv/bin/python scripts/data_collection/build_master.py --dry-run
.venv/bin/python scripts/data_collection/build_master.py --build
```

`build_features.py` reads only `processed/` outputs. `build_master.py` **refuses** to build
when the air-quality coverage is under a year, so a leftover sample cannot silently become the
training set.

## Features produced

`data/features/air_quality_features.csv` (parquet if `pyarrow` is installed)

| Column | Definition | Source |
|---|---|---|
| `PM2.5_t-1h` … `t-24h` | Per-station shifted PM2.5, lags 1/3/6/12/24 h | OpenAQ |
| `target_PM2.5_t+72h` | PM2.5 **72 hours ahead** — the forecast target | OpenAQ |
| `hour`, `day_of_week`, `month`, `day_of_year` | UTC calendar features | derived |
| `hour_sin/cos`, `month_sin/cos`, `doy_sin/cos` | Cyclic encodings | derived |

`data/features/meteorology_features.csv` adds `u_wind`, `v_wind`, `wind_speed_mps` to the
meteorology file.

### Why cyclic encodings

`hour` is also provided as sin/cos so that 23:00 → 00:00 is a small circular step rather than a
±23-unit jump. A tree model reading a raw `hour` can split the day into an arbitrary
"hour < 12" boundary that has no meteorological meaning.

### PM2.5 lag rules

- Lags are computed **within each station**, never across stations.
- A lag of a missing hour is **NaN**. It is not back-filled from the previous hour, the previous
  day, or a neighbouring station. The first 24 rows of every station have `NaN` for `t-24h`
  rather than a wrapped value.
- `target_PM2.5_t+72h` is a forward shift, and the final 72 hours of a station are `NaN` by
  construction. The 72 h horizon is the target, never a lag.

### Wind components

Meteorological convention — `wind_direction_10m` is the direction the wind blows **from**:

    u_wind = −speed · sin(direction)   # eastward component
    v_wind = −speed · cos(direction)   # northward component

Wind **from** the north (0°) therefore has `u=0, v=−speed`: blowing toward the south. The minus
signs are asserted directly in the tests, because flipping them is a silent, plausible-looking
bug that inverts the transport direction the model learns.

## Master dataset alignment

Declared in `build_master.py::ALIGNMENT` and copied into `data/master/master_manifest.json`.

| Parameter | Value |
|---|---|
| Grain | one row per `(station_id, UTC hour)` |
| Time zone | UTC internally; `Asia/Kolkata` for display only |
| Spatial matching | **nearest** of 5 NCR reference points, no interpolation |
| Max spatial distance | **35 km** (stations beyond keep null met columns, they are **not** dropped) |
| Max temporal gap | **0 hours** — exact hour match only |
| Interpolation | **none** on either side |
| Fill policy | missing stays null; never 0, never interpolated |

Each merged row carries `met_place`, `met_distance_km` and `met_in_range`, so the spatial match
is auditable per row rather than implied.

**Why no interpolation:** interpolating a pollution field between sparse stations manufactures
concentration values that were never measured, and a model trained on them learns an artifact of
the interpolation rather than the atmosphere. Rows that fall outside the match are **kept with
null met columns** so the gap is visible and countable instead of silently shrinking the dataset.

**Why zero temporal tolerance:** a temperature or wind value from an adjacent hour describes a
different physical state. Allowing a tolerance would pair a station reading with weather that
did not co-occur with it.

## Settled decisions (2026-09-30)

Both were resolved by inspecting the real 220-station coordinate distribution, not by preference.

### 1. Nearest point, not bilinear

Open-Meteo already returns the value of the ERA5 grid cell **containing** the requested point, so
each of the 5 reference series is itself a nearest-cell sample. Bilinear interpolation between
those series would blend cells across the Yamuna and the Delhi Ridge, and at 0.25° (~25 km) the
surrounding cells are often not meaningfully different. Nearest adds no fabricated value between
cells; bilinear would. If ERA5 replaces Open-Meteo, revisit this — with a real grid in hand the
trade-off is closer.

### 2. 35 km cut-off, derived from the data

The nearest-point distance distribution is strongly **bimodal**:

| Percentile | Distance |
|---|---|
| p25 | 9.3 km |
| p50 | 22.1 km |
| p75 | 150.6 km |
| max | 404.9 km |

**123 of 220 stations sit within 35 km** — the NCR core: Delhi 79, Gurugram 17, Ghaziabad 11,
Faridabad 10, Noida 6. The remaining **97 are 100–405 km away**, in Punjab, Haryana, Rajasthan,
Madhya Pradesh and Himachal Pradesh (Amritsar 405 km, Jalandhar 342 km, Gwalior 263 km).

Those outlying stations are **not Delhi NCR**. The original 40 km figure was arbitrary; 35 km is
where the data actually separates. Crucially, this is **not** a meteorology-representation problem
that a looser threshold would solve — a station 260 km away in Amritsar should not inherit
Gurugram's 10 m wind. They are a different region, retained with null meteorology.

## Still open

**What to do with the 89 stations still beyond 35 km.** Adding the outer ring (below) lifted
coverage from 56.4% to **59.5%**, leaving 89 stations unreachable. Those are in Punjab
(Amritsar, Jalandhar, Ludhiana), Rajasthan (Ajmer, Hanumangarh, Tonk) and Madhya Pradesh
(Gwalior) — 100–405 km away. Covering them properly would need ~8–10 further points in those
states (~20 MB, still no credential needed), or they stay null-meteorology. Given the brief's
"surrounding pollution-source regions", the Punjab/Haryana agricultural belt is the scientifically
interesting part; Rajasthan and MP are not on the NCR wind axis and can be left out.

## Not yet built (blocked on credentials)

| Feature group | Blocked by |
|---|---|
| Fire features (counts, FRP sums, distance/bearing to Delhi, upwind indicators) | `FIRMS_MAP_KEY` |
| CAMS features (background PM2.5, aerosol optics) | `~/.cdsapirc` |
| Inversion features (`T925−T2m`, `T850−T2m`, PBLH) | `~/.cdsapirc` (ERA5) |

These produce **no columns and no synthetic stand-ins**. `build_features.py` names each one and
its blocker in its output so the gap is always visible.

## A note on interpretation

Fire counts, FRP, inversion strength and CAMS background are **predictive features**, not
demonstrated causes of a PM2.5 observation. A fire detection in Punjab is evidence of burning
activity, not evidence that a given Delhi station reading was caused by it. Causal claims would
need a transport or attribution analysis, which this pipeline does not perform.
