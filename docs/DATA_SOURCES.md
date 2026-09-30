# VayuSangam — Data Sources (Phase 0 discovery)

All rows below were verified by **live calls made on 2026-09-30**, not from memory or tutorials.
Where a row says "unverified", the request was blocked by missing credentials and nothing has been
downloaded from that source.

## Master table

| Source | Dataset | Variables | Spatial res. | Temporal res. | Historical coverage | Authentication | Est. size (NCR, 2024→now) | Status |
|---|---|---|---|---|---|---|---|---|
| OpenAQ | v3 `/locations`, `/sensors/{id}` | station metadata, sensor inventory | point (station) | — | 2000s→live per sensor | `X-API-Key` header, 64-char key | 0.5 MB | **Verified working — collected** |
| OpenAQ | v3 `/sensors/{id}/hours` | PM2.5, PM10, NO2, NOx, O3, CO, SO2, temperature, RH, wind speed/dir | point (station) | hourly | 2014→live per sensor | same key | **11.9 GB measured** (all 11 vars) | **Downloading (approved)** |
| NASA FIRMS | `area` API, VIIRS SNPP/NOAA20 | lat, lon, acq_date/time, satellite, instrument, confidence, frp, daynight | ~375 m (VIIRS) | ~30 min swath overpass | 2012-05→now (archive) | `MAP_KEY` in path | 0.2–0.5 GB/year | **BLOCKED — no FIRMS_MAP_KEY** |
| Open-Meteo | Historical Weather API (archive) | temperature_2m, relative_humidity_2m, surface_pressure, wind_speed_10m, wind_direction_10m, cloud_cover, precipitation | 0.1°–0.25° or point | hourly | 1940→now (ERA5/ERA5-Land) | none | 9.8 MB (5 pts, 2.8 yr) | **Verified — collected** |
| Copernicus CDS | `reanalysis-era5-single-levels` | 2m_temperature, 2m_dewpoint_temperature, 10m_u/v_component_of_wind, surface_pressure, mean_sea_level_pressure, boundary_layer_height | 0.25° | hourly | 1940→present | `cdsapi` ≥0.7.7 + `~/.cdsapirc` (`url` + `key`, **no uid**) | 0.3–1.5 GB | **Schema verified; BLOCKED** |
| Copernicus CDS | `reanalysis-era5-pressure-levels` | temperature @ 925/850 hPa, geopotential | 0.25° | hourly | 1940→present | same | 0.1–0.4 GB | **Schema verified; BLOCKED** |
| Copernicus ADS | `cams-global-reanalysis-eac4` | particulate_matter_2.5um, particulate_matter_10um, particulate_matter_1um, nitrogen_dioxide, ozone, carbon_monoxide, sulphur_dioxide, dust/organic/sulphate/sea-salt/black-carbon aerosol optics, total_column_* | 0.75° | 3-hourly | 2003→2024 | `cdsapi` + ADS `~/.cdsapirc` | 0.01–0.6 GB | **Schema verified; BLOCKED** |
| OpenStreetMap | Overpass API | admin boundaries (geometry), motorway/trunk/primary roads, landuse | vector | static | current | none (rate-limited) | 44 MB (NCR) | **Verified — collected** |

## Verified API details (live, 2026-09-30)

### OpenAQ v3
- Base URL: `https://api.openaq.org/v3`, auth header `X-API-Key: <key>`.
- Project key in `.env` authenticates successfully (`/parameters?limit=1` → HTTP 200).
- Region query used: `/locations?iso=IN&bbox=74.0,26.0,80.0,32.5` → **220 locations** returned
  (Delhi NCR + adjacent Punjab/Haryana/Western-UP source regions). No global query is ever made.
- `limit` max observed on v3: 1000.
- Response shape: `{meta:{found,page,limit,pages}, results:[...]}`.
- Hourly records: `/sensors/{sensor_id}/hours?datetime_from=…&datetime_to=…` →
  `results[]` with `value`, `period.datetimeFrom.utc`, `coverage.datimeFrom/To`.
- **Limitation (important):** the v3 `/locations` objects do **not** carry a district field. The
  existing `district` column in `station_metadata.csv` is currently empty for all 220 stations.
  `locality` is also mostly unset. District must be filled from an authoritative administrative
  boundary join (OSM admin boundaries, phase 6) — we will not invent it.
- Rate limits: `x-ratelimit-remaining` / `x-ratelimit-reset` headers are honoured by the client.

### NASA FIRMS
- `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{source}/{west,south,east,north}/{days}/{MAP_KEY}`
- Live probe without a key returns `Invalid MAP_KEY.` → the endpoint is reachable, the credential
  is simply absent. Sources: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `MODIS_TERRA_CORRECTED`, …
- Country-level endpoints are marked *not available* by NASA; we must use the **area** endpoint.
- Retrospective data is on the same `area` path with `archive/{dataset}/{source}` style keys, or
  the near-real-time stream for recent periods. This must be pinned before the fire download.

### Open-Meteo
- `https://archive-api.open-meteo.com/v1/archive?latitude=…&longitude=…&start_date=…&end_date=…&hourly=…&timezone=UTC`
- Live probe for Delhi (28.61, 77.21) returned valid hourly data with declared units:
  `temperature_2m °C`, `relative_humidity_2m %`, `surface_pressure hPa`, **`wind_speed_10m km/h`**,
  `wind_direction_10m °`, `cloud_cover %`, `precipitation mm`.
- No API key. Note wind speed arrives in **km/h** → must be converted to m/s (÷3.6) and recorded.
- Underlying reanalysis is ERA5/ERA5-Land — not independent of Phase 4, must be documented so the
  model does not treat Open-Meteo and ERA5 as independent features.

### Copernicus CDS (ERA5) — current API
- New CDS Engine is live. `cdsapi>=0.7.7`; `~/.cdsapirc` contains **only** `url` and `key`
  (the `uid` field was removed in the new infrastructure).
- Dataset processes verified via `GET /api/retrieve/v1/processes/<name>`:
  - `reanalysis-era5-single-levels` — inputs `product_type, variable, year, month, day, time, area, data_format, download_format`; `product_type` enum includes `reanalysis`; `data_format` enum `grib|netcdf`.
  - `reanalysis-era5-pressure-levels` — same plus `pressure_level`.
  - Confirmed variable names: `2m_temperature`, `2m_dewpoint_temperature`,
    `10m_u_component_of_wind`, `10m_v_component_of_wind`, `surface_pressure`,
    `mean_sea_level_pressure`, `boundary_layer_height`; pressure-level `temperature`.
  - `area` is `[north, west, south, east]` — **note the different order vs our `west,south,east,north` convention**.
- Each dataset's licence must be accepted manually on the dataset page before the first API request.

### Copernicus ADS (CAMS EAC4)
- Endpoint currently responds at `https://ads.atmosphere.copernicus.eu/api/...` (the newer
  `https://atmosphere.copernicus.eu/api/...` returned 404 for the catalogue on 2026-09-30; both
  hosts are documented — we will confirm which one accepts our key before the download).
- `cams-global-reanalysis-eac4`: 0.75°, 3-hourly (00/03/…/21), 2003–2024, GRIB or `netcdf_zip`,
  pressure levels include 925/850/850/700/500 hPa. **62 variables confirmed available**, including
  `particulate_matter_2.5um`, `particulate_matter_10um`, `particulate_matter_1um`,
  `nitrogen_dioxide`, `ozone`, `carbon_monoxide`, `sulphur_dioxide`, `total_aerosol_optical_depth_550nm`,
  dust/organic-matter/sulphate/sea-salt/black-carbon aerosol optics and mixing ratios,
  `total_column_nitric_acid`, `total_column_ozone`, `2m_temperature`, `10m_u/v_component_of_wind`.
  No PM variable outside this list will be requested.

## Missing credentials — action required from the user

| Source | Account | Sign-up | Credential | Where |
|---|---|---|---|---|
| NASA FIRMS | NASA Earthdata | https://firms.modaps.eosdis.nasa.gov/api/ → "map_key" | `MAP_KEY` string | `FIRMS_MAP_KEY=` in project `.env` |
| Copernicus CDS | ECMWF (single sign-on) | https://cds.climate.copernicus.eu/ | personal access token | `~/.cdsapirc` → `url: https://cds.climate.copernicus.eu/api`, `key: <token>` |
| Copernicus ADS | ECMWF (single sign-on) | https://ads.atmosphere.copernicus.eu/ | personal access token | `~/.cdsapirc` → `url: https://ads.atmosphere.copernicus.eu/api`, `key: <token>` |

No key was invented, guessed, or substituted.
