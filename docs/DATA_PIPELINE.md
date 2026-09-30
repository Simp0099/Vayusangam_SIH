# VayuSangam — Data Pipeline

Air-pollution–weather coupled data pipeline for **Delhi NCR** and the surrounding pollution-source
regions. This document describes what is collected, from where, how, and under which approval
gate.

## 1. Datasets

| Domain | Dataset | Source | Status | Role |
|---|---|---|---|---|
| Air quality | Hourly station observations | OpenAQ v3 | 🔄 downloading (status in manifest) | **Target variable** (PM2.5, AQI) |
| Meteorology | Historical weather (reanalysis) | Open-Meteo archive (ERA5/ERA5-Land) | ✅ 240,960 rows, 10 points | Training features |
| **Meteorology** | **Historical FORECAST (prev. model runs)** | **Open-Meteo forecast archive** | **✅ 182,400 rows, incl. PBLH** | **Forecast-input skill evaluation** |
| Meteorology | Reanalysis + PBLH + T925/T850 | Copernicus ERA5 | ⛔ blocked on `~/.cdsapirc` | Upper-air inversion diagnostics |
| Fire | VIIRS fire detections | NASA FIRMS | ⛔ blocked on `FIRMS_MAP_KEY` | Biomass-burning source activity |
| Composition | CAMS global reanalysis (EAC4) | Copernicus ADS | ⛔ blocked on `~/.cdsapirc` | Background PM, gases, aerosol optics |
| Geospatial | Boundaries, major roads, land use | OpenStreetMap | ✅ 44 MB | Spatial context |

Full detail, live-verified: `docs/DATA_SOURCES.md`.

## 2. Credentials

| Variable | Where | Source of the key |
|---|---|---|
| `OPENAQ_API_KEY` | project `.env` | https://explore.openaq.org/register |
| `FIRMS_MAP_KEY` | project `.env` | https://firms.modaps.eosdis.nasa.gov/api/ → *map_key* |
| Copernicus token | `~/.cdsapirc` (**not** the project `.env`) | login at https://cds.climate.copernicus.eu/ and https://ads.atmosphere.copernicus.eu/ |

Copy the template and check status:

```bash
cp .env.example .env          # then fill in the keys
.venv/bin/python scripts/data_collection/check_credentials.py
```

`check_credentials.py` prints only presence, length and a 3-character fingerprint — never a full
key. `~/.cdsapirc` must contain **only** `url` and `key` since the 2025 CDS/ADS migration
(the legacy `uid:` field is gone); use `cdsapi>=0.7.7`.

## 3. Approval gates

Anything that could exceed ~100 MB, ~10,000 records, multiple stations at once, multi-month
hourly data, or a few minutes of runtime **must not be executed** before explicit approval
("approve" / "yes" / "continue" / "download it" / "proceed"). Silence is never approval.

Safe without asking: metadata requests, documentation inspection, API capability checks, tiny test
downloads, schema inspection, and local processing of already-downloaded files.

Every gate is accompanied by a report produced by
`scripts/data_collection/approval_request.py`, which prints the dataset, source, region, date
range, variables, station/grid count, estimated records/size/runtime, and the exact command
proposed.

## 4. Run order

```bash
# 0. credentials and layout
.venv/bin/python scripts/data_collection/check_credentials.py

# 1. OpenAQ — station discovery + metadata (no hourly download)
.venv/bin/python scripts/data_collection/openaq/download_openaq.py --check-connection
.venv/bin/python scripts/data_collection/openaq/download_openaq.py

# 2. OpenAQ — tiny sample (1 station, 3 days) then STOP for approval
.venv/bin/python scripts/data_collection/openaq/download_openaq.py \
    --sample --sample-stations 1 --sample-days 3
.venv/bin/python scripts/data_collection/openaq/process_openaq.py
.venv/bin/python scripts/data_collection/openaq/validate_openaq.py

# 3. OpenAQ — production historical download (ONLY after approval)
.venv/bin/python scripts/data_collection/openaq/download_openaq.py \
    --start-date 2024-01-01 --end-date 2026-09-30
.venv/bin/python scripts/data_collection/openaq/enrich_availability.py
.venv/bin/python scripts/data_collection/openaq/process_openaq.py
.venv/bin/python scripts/data_collection/openaq/validate_openaq.py

# 5. Meteorology — Open-Meteo, no key, ~10 MB, ~10 s (no approval needed)
.venv/bin/python scripts/data_collection/meteorology/download_open_meteo.py --test
.venv/bin/python scripts/data_collection/meteorology/download_open_meteo.py \
    --start-date 2024-01-01 --end-date 2026-09-30

# 6. Geospatial — OSM, no key, ~44 MB, ~75 s
.venv/bin/python scripts/data_collection/geospatial/download_osm.py --test
.venv/bin/python scripts/data_collection/geospatial/download_osm.py --only roads
.venv/bin/python scripts/data_collection/geospatial/download_osm.py --only landuse

# 7. ERA5 / CAMS — schema + credential check only; no download without approval
.venv/bin/python scripts/data_collection/era5/prepare_era5.py
.venv/bin/python scripts/data_collection/cams/prepare_cams.py

# 8. FIRMS — blocked without FIRMS_MAP_KEY
.venv/bin/python scripts/data_collection/fires/download_firms.py --check-key

# 9. Provenance manifest for any dataset, then cross-dataset validation
.venv/bin/python scripts/data_collection/write_manifest.py meteorology --start-date 2024-01-01
.venv/bin/python scripts/data_collection/validate_all.py

# 10. Features and the master dataset (see docs/FEATURES.md)
.venv/bin/python scripts/data_collection/build_features.py
.venv/bin/python scripts/data_collection/build_master.py --dry-run
.venv/bin/python scripts/data_collection/build_master.py --build
```

Downstream phases (fires, meteorology, ERA5, CAMS, geospatial) each begin with a metadata-only
step, then a tiny test, then an approval gate.

## 5. Processing rules

- `raw/` is **immutable**. Nothing ever writes into it; processing re-reads it and writes
  `processed/`. To reprocess, delete only the `processed/` output.
- Time is UTC internally (hourly interval start). Local time is `Asia/Kolkata` for display only.
  UTC and IST are never mixed implicitly.
- Coordinates are WGS84 / EPSG:4326 as published by the sources; no source coordinate is altered.
- Missing pollution values stay **null**. They are never replaced with 0.
- Unit conversion happens only through an explicit whitelist (`common.py::normalize_value`);
  an unrecognised unit yields null and an `invalid_values` increment.
- Duplicate `(station_id, timestamp, variable)` rows are counted, then de-duplicated by mean of the
  duplicate readings; hourly aggregation is **mean over the readings in that hour**, documented in
  `data/air_quality/DATA_DICTIONARY.md`.
- Where a station has several sensors for one variable, the sensor with the broadest declared
  history is selected (ties broken by reference-monitor status, then lowest sensor id) and recorded
  in `data/air_quality/sensor_metadata.csv`.

## 6. Validation

`scripts/data_collection/validate_all.py` checks schema, duplicates, timestamp continuity and
range, coordinate bounds, unit consistency, impossible values, station-id referential integrity and
source metadata, then writes `reports/data_validation_report.json` and `.html`.

## 7. Expected storage

| Phase | Raw | Processed | State |
|---|---|---|---|
| OpenAQ (2024→now, all 11 variables, 165 stations) | **~11.9 GB measured** | ~770 MB | 🔄 downloading |
| OpenAQ (2024→now, PM2.5 only) | ~1.4 GB | ~70 MB | not run |
| Open-Meteo (5 NCR points, 3 yr hourly) | 9.8 MB | 9.2 MB | ✅ done |
| OSM (boundaries + major roads + landuse, NCR) | 44 MB | — | ✅ done |
| NASA FIRMS (1 yr, NCR bbox) | ~0.2–0.5 GB | ~20 MB | ⛔ no key |
| ERA5 (NCR subset, 9 fields, 3 yr hourly) | ~0.4–1.5 GB (0.42 GB est.) | ~0.5 GB | ⛔ no token |
| CAMS EAC4 (PM + gases, 3-hourly, 1 yr) | ~0.01–0.6 GB | ~0.3 GB | ⛔ no token |

Total for a full build: roughly **13–15 GB**, dominated by the OpenAQ raw cache. Only the
`processed/` artefacts (well under 1 GB) are needed at training time; `raw/` can be deleted and
re-fetched with the collector scripts if disk pressure requires it.

## 8. Known limitations

0. **Background production download (approved 2026-09-30).** An unapproved full-set download was
   found already running (PID 95430, started 09:49, ~307 MB cached). It was stopped at the user's
   request — it was resumable, so the 307 MB was kept. An **approved all-11-variable** run
   (2024-01-01 → 2026-09-30) was then launched and the user chose to let it run to completion.
   **Measured true size: ~11.9 GB raw, ~11 h runtime** (see the estimation error note below).
   The raw cache is resumable: re-running the same command reuses every cached page.

   ⚠️ **Estimation error, recorded so it is not repeated.** The first estimate (1.93 GB / 84 min)
   was derived from a 3-day sample in which most stations had sparse history, giving
   0.078 MB per station-month. Real 2024–2026 pages average **0.484 MB** — a ~6× underestimate.
   `approval_request.py` now uses the measured value and the observed throughput
   (~37 pages/min). Sizing a download from a small, unrepresentative sample is not reliable;
   size estimates for the remaining phases should be validated the same way.
1. **OpenAQ `district` is empty.** The v3 `/locations` object carries no administrative area; the
   existing `district_from_location` alias table therefore yields null for all 220 stations.
   The OSM boundary extract **partially** closes this: `Gurgaon`, `Ghaziabad`, `Faridabad` and
   `Gautam Buddha Nagar` (which contains Noida) are present at `admin_level=6`, and
   `Gurgaon` must be mapped explicitly to `Gurugram`. **Delhi's own districts are absent** — it
   is a union territory, so OSM's `admin_level=6` layer does not cover it, and only a single
   `admin_level=4` "Delhi" relation exists. A point-in-polygon join will not resolve a district
   for Delhi stations. The Survey of India / LGD route in
   `data/air_quality/DATA_DICTIONARY.md` remains the correct fix. No district is inferred from a
   station name.
2. **OSM roads and land use are tags-only** (no geometry) to keep the extract at 44 MB instead of
   several GB. They support classification features but not distance or point-in-polygon work.
   Only `osm_boundaries.json` carries usable geometry.
3. **Open-Meteo archive is not independent of ERA5** — it serves ERA5/ERA5-Land. Using both as
   separate feature groups leaks the same reanalysis and inflates apparent model skill.
4. **Forecast archive (previous model runs) — collected, with a hard date limit.**
   `data/meteorology/processed/forecast_hourly.csv` supplies genuine forecast fields plus
   `boundary_layer_height` (PBLH) and solar radiation, closing the "forecast NWP archive" and
   "PBLH" gaps the audit flagged. **PBLH only exists from 2024-09-01** — before that the API
   returns HTTP 200 with a declared unit and entirely null values, so PBLH cannot be joined to
   air-quality observations earlier than that without either narrowing the training window or
   getting PBLH from ERA5. The forecast archive and the ERA5 archive are **the same model** and
   must not be merged as independent feature groups.
5. **FIRMS blocked** on `FIRMS_MAP_KEY`; no fire data has been downloaded.
6. ERA5 over India has known biases in the nocturnal boundary layer, which is precisely the
   regime VayuSangam cares about.
7. FIRMS detects fire *activity*, not emissions, and a detection in Punjab/Haryana is not evidence
   that a given Delhi PM2.5 spike was caused by it.

## 9. Licensing

- OpenAQ — data licensed per upstream provider; attribution required (CPCB, state boards, AirGradient, …).
- NASA FIRMS — free for research/educational use with attribution to NASA FIRMS/LANCE.
- Copernicus ERA5 & CAMS — Copernicus Licence; users must accept dataset terms on the dataset page
  before the first API request.
- Open-Meteo — free for non-commercial use below 10,000 calls/day, CC-BY 4.0 attribution.
- OpenStreetMap — ODbL; attribution required.

Retain these attributions in the VayuSangam dashboard and README.
