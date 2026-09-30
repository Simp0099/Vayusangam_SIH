# VayuSangam — Units Register

Rule: a value whose source unit cannot be verified is **not** converted and **not** stored as a
number. It stays null and is counted as an invalid/unsupported value. Nothing is guessed.

Internally the pipeline standardises on:

- Time: **UTC** (interval start, hourly). Local time retained for display as `Asia/Kolkata`.
- Coordinates: **WGS84 / EPSG:4326**, `latitude`,`longitude` in decimal degrees, no reprojection of
  source values (sources are already WGS84); any future transformation is recorded in the manifest.
- Missing pollution observations are **null**, never 0.

## Air quality (OpenAQ v3 → `data/air_quality/`)

Final units are fixed in `scripts/data_collection/openaq/common.py::FINAL_UNITS` and enforced by
`normalize_value`, which only converts from an explicit whitelist.

| Variable | Source unit(s) accepted | Final unit | Conversion |
|---|---|---|---|
| PM2.5 | `µg/m³` (also `ug/m3`) | µg/m³ | identity |
| PM2.5 | `mg/m³` | µg/m³ | × 1000 |
| PM10 | `µg/m³` | µg/m³ | identity |
| PM10 | `mg/m³` | µg/m³ | × 1000 |
| NO2, NOx, O3, CO, SO2 | `ppb` | ppb | identity |
| NO2, NOx, O3, CO, SO2 | `ppm`, `µmol/mol` | ppb | × 1000 |
| temperature | `°C` | °C | identity |
| temperature | `K` | °C | − 273.15 |
| temperature | `°F` | °C | (x−32)×5/9 |
| relative_humidity | `%` | % | identity |
| relative_humidity | unitless 0–1 | % | × 100 |
| wind_speed | `m/s` | m/s | identity |
| wind_speed | `km/h` | m/s | ÷ 3.6 |
| wind_speed | `mph` | m/s | × 0.44704 |
| wind_speed | `kn` | m/s | × 0.514444 |
| wind_direction | `degree(s)` | degrees | identity |

Deliberately **not** converted:
- Mass→mole conversion for gases (e.g. mg/m³ → ppb) requires an assumed T/P; OpenAQ supplies
  per-sensor unit metadata, so ambiguous values are rejected rather than converted.
- Any unknown unit string → null, `unsupported_unit`.

Validity gates applied: RH ≤ 100, wind direction 0–360, temperature −100…70 °C, negatives rejected
for concentrations/RH/wind speed. Rejected values are logged as `invalid_values` in
`data/air_quality/data_quality_report.csv` and are never zero-filled.

## Meteorology (Open-Meteo, verified from a live response 2026-09-30)

| Variable | Source unit | Final unit | Conversion |
|---|---|---|---|
| `temperature_2m` | °C | °C | identity |
| `relative_humidity_2m` | % | % | identity |
| `surface_pressure` | hPa | hPa | identity (kept as hPa; 1 hPa = 100 Pa) |
| `wind_speed_10m` | **km/h** | m/s | ÷ 3.6 |
| `wind_direction_10m` | degrees | degrees | identity |
| `cloud_cover` | % | % | identity |
| `precipitation` | mm | mm | identity |

## ERA5 (Copernicus CDS) — units as declared by the dataset, to be re-verified from the downloaded GRIB/netCDF metadata

| CDS variable | Expected unit | Final |
|---|---|---|
| `2m_temperature`, `2m_dewpoint_temperature` | K | K (converted to °C only if recorded in the manifest) |
| `10m_u_component_of_wind`, `10m_v_component_of_wind` | m s⁻¹ | m s⁻¹ |
| `surface_pressure`, `mean_sea_level_pressure` | Pa | Pa → hPa ÷ 100 |
| `boundary_layer_height` | m | m |
| pressure-level `temperature` | K | K |

These are marked **expected, not verified**, because no ERA5 bytes have been downloaded. The
loader must read `units` from the file metadata and assert the table above; a mismatch is a hard
stop for that variable.

## CAMS EAC4

Units must be read from the GRIB/netCDF metadata at download time. Do not assume. Expected, to be
verified: particulate matter µg/m³, gas species µg/m³ (model level) or mol/m² (total column),
AOD dimensionless.

## NASA FIRMS

| Field | Unit |
|---|---|
| `frp` | MW (Fire Radiative Power) |
| `latitude`, `longitude` | decimal degrees, WGS84 |
| `acq_date` + `acq_time` | UTC acquisition time (padded to HHMM, e.g. `0654`) |
| `confidence` | categorical: `low` / `nominal` / `high` |

## FRP note

FRP is energy release rate of a fire at overpass time, **not** an emission mass. It is used in
VayuSangam only as a relative activity/intensity proxy and never as a direct concentration.

## Status of this document

Anything not listed here is `UNKNOWN` and is not processed.
