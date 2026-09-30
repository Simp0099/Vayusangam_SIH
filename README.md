# VayuSangam

**Coupled Air–Weather Intelligence for Delhi NCR** · LogiNexa · Smart India Hackathon 2026, PS 26082

VayuSangam is a replay-first prototype for exploring how boundary-layer stability, ventilation and transported smoke can shape an air-quality forecast. It includes an explicit 72-step surrogate coupling loop, deterministic replay data, a smoke particle transport demonstration and an interactive local dashboard.

> **Data status:** the bundled Delhi Winter Stagnation episode is synthetic, deterministic **DEMO / REPLAY DATA**. It is not an actual historical event, live CPCB observation, NASA FIRMS detection, WRF-Chem output, or scientific validation. No accuracy values are claimed.

## What works

- Overview dashboard with AQI, PM2.5, O3, PBLH, ventilation and relative smoke influence.
- **Data archive** with the normalized OpenAQ sample and local Open-Meteo ERA5 / historical forecast tables. Source class, units, valid-time coverage, missing samples and archive limitations are shown with each series; this is not a live conditions page.
- AQI is an approximate PM2.5 sub-index proxy for display, not a complete regulatory multi-pollutant AQI.
- 72-hour slider and playback; selecting a station updates the forecast and driver explanation.
- Inversion diagnostics using `ISI = T925 − T2m` and `VC = PBLH × mean PBL wind speed`.
- Explicit coupled rollout: prior PM2.5 applies an aerosol-feedback adjustment to the next meteorological state; corrected temperature, PBLH, ISI and ventilation feed the pollution recurrence.
- PM25Forecaster fits a fixed-seed synthetic fixture and emits quantile predictions; LightGBM estimators are used when installed. The O3 component is separate and does not take smoke as a direct input.
- Deterministic particle transport with wind advection, diffusion, age decay and a relative Smoke Influence Index.
- Fire-reduction what-if scenario that reruns the coupled surrogate and shows output changes.
- Coupling, plume, inversion, alert and verification screens. Verification scores remain blank until a verified historical dataset is connected.
- Provider interfaces and WRF-Chem/NCUM stubs; deterministic briefing fallback.

## Architecture

```text
Browser (HTML/CSS/JS + inline SVG map/charts)
                 │ same origin
                 ▼
         FastAPI replay API
          ├─ normalized provider interfaces
          ├─ SurrogateModelProvider (72-hour coupled loop)
          ├─ Lagrangian smoke prototype (NumPy)
          └─ deterministic replay cache
                 │ planned normalized persistence
                 ▼
          PostgreSQL / PostGIS schema
```

The frontend uses a self-contained responsive interface and inline SVG map/chart rendering so the demo works without a map token, Node toolchain, or external tile service. The replay map is schematic. The separate archive view plots real OpenAQ coordinates and reads the normalized CSV tables through bounded FastAPI routes; it does not load the multi-gigabyte raw cache into the browser. See [docs/data-ui-mapping.md](docs/data-ui-mapping.md), [docs/data-schema.md](docs/data-schema.md), and [docs/frontend-data-contract.md](docs/frontend-data-contract.md).

## Local setup

Python 3.11+ is recommended. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-minimal.txt
python scripts/generate_replay.py
python -m uvicorn backend.app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The first launch uses replay mode and requires no API credentials. The generated JSON episode is stored at `demo/replay/delhi-winter-stagnation.json`; the API also precomputes the same fixed-seed replay in memory.

To enable optional model libraries, use `pip install -r backend/requirements.txt`. LightGBM support is optional; PM25Forecaster exposes `fit()`, `predict()` and `predict_quantiles()` and falls back to a clearly labelled demo equation if LightGBM is absent. The synthetic fixture is solely for pipeline demonstration, never validation.

## API

`GET /api/health`, `/api/stations`, `/api/forecast/station/{id}`, `/api/forecast/grid?hour=48`, `/api/met/inversion`, `/api/fires`, `/api/smoke/plume`, `/api/coupling/{station}`, `/api/explain/{station}`, `/api/verification`, `/api/replay/{episode}` and `POST /api/whatif/smoke` serve the replay workflow. `/api/data/status`, `/api/data/stations`, `/api/data/air-quality` and `/api/data/meteorology` expose bounded local archive data with explicit provenance. `/docs` exposes the FastAPI OpenAPI UI.

## Demo workflow

1. Start in **REPLAY MODE** and point out the synthetic-data banner.
2. Scrub to +48h and select Anand Vihar or Noida on the map.
3. Explain the forecast curve and deterministic model-derived driver bars.
4. Open Inversion to show ISI, PBLH and ventilation.
5. Open Plume tracker to show synthetic source points and relative transport.
6. Open Coupling to trace previous PM2.5 → feedback → corrected meteorology → next step.
7. Open Demo walkthrough → What-if scenario; change reduction and rerun.
8. Open Verification to explain the historical data required before reporting skill metrics.

## Tests and browser QA

```bash
pytest
```

Playwright CLI/browser QA can be run after starting the app:

```bash
playwright-cli open http://127.0.0.1:8000
playwright-cli snapshot
playwright-cli screenshot --filename=artifacts/screenshots/overview.png
```

The browser automation package is not bundled as a runtime dependency. See `artifacts/screenshots/` for any captured review images.

## Environment variables

Copy `.env.example` as needed. All external credentials are optional in replay mode. Adapters do not silently claim live data; each planned source must be configured and normalized before it is surfaced as live.

### OpenAQ station-history collection

The OpenAQ v3 pipeline discovers Indian monitoring locations in the configurable WGS84 bbox (default includes Delhi NCR and adjacent Haryana, Punjab and Uttar Pradesh source regions), inspects each location's sensors, selects stations with PM2.5, and downloads precomputed hourly sensor data in resumable monthly chunks. Government/reference indicators are used for station ranking when the API exposes them; secondary variables remain nullable when a station does not provide them. OpenAQ does not provide all requested meteorological variables or reliable district boundaries for every location, so missing fields remain missing and ambiguous Delhi districts are left blank.

Install the pipeline dependencies, then add your key to the project-local `.env` file. Do not send the key in chat or commit `.env`:

```bash
cp .env.example .env
# Edit .env and set OPENAQ_API_KEY=your_key
python -m pip install -r scripts/data_collection/openaq/requirements.txt
```

Start with an authenticated connection check and a three-day, one-station sample. The sample still discovers the full configured region, but only downloads the sample station's recent measurements:

```bash
python scripts/data_collection/openaq/download_openaq.py --check-connection
python scripts/data_collection/openaq/download_openaq.py --sample --sample-stations 1 --sample-days 3
python scripts/data_collection/openaq/process_openaq.py
python scripts/data_collection/openaq/validate_openaq.py
```

After reviewing the sample outputs, run the full configured period (default `2024-01-01` through today), then process and validate:

```bash
python scripts/data_collection/openaq/download_openaq.py
python scripts/data_collection/openaq/process_openaq.py
python scripts/data_collection/openaq/validate_openaq.py
```

Set `OPENAQ_START_DATE`, `OPENAQ_END_DATE`, and `OPENAQ_BBOX` in `.env` to change the range and region without editing code. Leave `OPENAQ_END_DATE` blank to use today's date. Existing raw response pages are reused; `--refresh` stores new timestamped responses and preserves prior raw files. Outputs are written under `data/air_quality/`, including `station_metadata.csv`, `station_availability.csv`, `air_quality_hourly.csv`, `data_quality_report.csv`, and `DATA_DICTIONARY.md`. Raw API JSON and collection metadata are retained under `data/air_quality/raw/`; raw data is git-ignored. The dictionary documents output units and conversions. Station availability distinguishes NO2 from NOx.

The API key is required for station discovery and collection. If it is missing, the downloader exits with instructions; it does not create fake observations. See the [OpenAQ API key guide](https://docs.openaq.org/using-the-api/api-key) and [v3 API reference](https://docs.openaq.org/api).

## Data adapters and roadmap

- **Implemented:** deterministic demo weather/fire/observation interfaces and the surrogate provider.
- **Available in archive view:** 72 hours of normalized OpenAQ station data (one station, partial pollutant coverage), 2024–2026 ERA5 reanalysis and historical forecast archive for 10 locations. These are historical products; archive rows have no operational forecast run ID.
- **Not collected:** NASA FIRMS/fire detections, CAMS aerosols, and ERA5 pressure-level fields. They remain unavailable in the UI.
- **Planned:** production training on quality-controlled, aligned station/NWP/CAMS/fire data; interval calibration and held-out temporal evaluation.
- **Planned:** operational WRF-Chem and NCUM provider adapters. No such model runs in this prototype.
- **Planned:** replace schematic map with MapLibre/deck.gl spatial layers and connect PostGIS-backed forecast persistence.

## Limitations

See [docs/model-card.md](docs/model-card.md), [docs/limitations.md](docs/limitations.md), and the data documents above. Key limits: surrogate equations and synthetic replay, only one incomplete normalized observation station, no live NCR AQI, no collected FIRMS/CAMS/ERA5 pressure-level data, relative synthetic smoke indicator, no validated source apportionment, no operational WRF-Chem/NCUM, no scientific accuracy metrics and schematic replay map.
