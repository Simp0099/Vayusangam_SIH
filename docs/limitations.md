# Prototype limitations

- The current provider is a deterministic surrogate, not operational WRF-Chem or NCUM.
- Demo/replay values are synthetic and are not scientific validation or historical observations.
- Smoke Influence Index is a relative transport indicator, not an emissions inventory, fire detection product or exposure estimate.
- The prototype has limited local/regional source separation and no calibrated chemical mechanism.
- The 72-hour display is a schematic/downscaled prototype view; no validated high-resolution grid is connected.
- Real historical data must be connected before computing verification metrics.
- CPCB/OpenAQ, FIRMS, CAMS and ERA5 integrations are planned provider interfaces; no live integration is currently active.

## Air-quality station coverage: measured, not assumed

Measured 2026-09-30 from `data/air_quality/station_availability.csv` (220 stations
inside the Delhi NCR bbox 74,26 → 80,32.5):

| Metric | Value |
|---|---|
| Stations discovered | 220 (all inside bbox) |
| Selected for download | 167 (75.9%) |
| Sensor lookup failed | 9 — see below |

**9 stations are unrecoverable as of 2026-09-30.** Their
`/locations/<id>/sensors` endpoint returns HTTP 500 — persistently, on repeat
probes over ~12 hours, not as a transient blip. Verified by
`scripts/data_collection/retry_failed_sensors.py --check`: 0/9 recovered.
Affected: Chhatikara (Vrindavan), Dadupura (Fatehpur Sikri), Baraut,
New Anaj Mandi (Khairthal), New Tehsil (Shamli), Pali Dungra (Mathura),
Rajanpur (Gajraula), Vigyan Nagar (Alwar), Wave City (Ghaziabad).
These are mostly **western/upwind UP and Rajasthan source stations** — exactly
the biomass-burning belt the project cares about. Their absence biases the fire
source region, not the urban core. No re-run recovers them until OpenAQ fixes the
endpoint; the failure is recorded in
`data/manifests/failed_sensor_retry.json`.

**2 further reference monitors (Civil Lines, IGI Airport) are legitimately
excluded, not lost.** They have live PM2.5 sensors but return 0 rows for the
full 2024-01 → 2026-09 window, confirmed against a control sensor that returned
1000 rows in the same query. Their exclusion is correct.

## Credential-blocked domains: probed, not assumed

`scripts/data_collection/probe_blocked_domains.py` checks each blocked domain
against its live endpoint. Results in
`data/manifests/blocked_domains_probe.json`:

| Domain | Live probe | Verdict |
|---|---|---|
| NASA FIRMS | HTTP 400 `Invalid MAP_KEY` | Key genuinely required |
| ERA5 T925/T850 (inversion) | HTTP 200 but **0/24 non-null** on every Open-Meteo endpoint/model | No keyless data — CDS token genuinely required |
| CAMS | Catalogue HTTP 200 | Catalogue reachable; GRIB retrieval needs a CDS token |

Note the ERA5 row: Open-Meteo **declares** `temperature_925hPa` in its schema and
returns HTTP 200 with the field present — and every value null. A declared unit is
the schema, not the data. There is no keyless substitute for pressure-level
temperature, so inversion detection is genuinely blocked, not merely un-attempted.
- The map and particle display are schematic inline SVG, not a live basemap or geospatially rigorous plume raster.
- The PM2.5 model uses a synthetic training fixture for demo pipeline behavior; it is not trained on real air-quality measurements.
- Verification framework returns no invented values. WRF-Chem and NCUM integrations are planned.
