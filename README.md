# VayuSangam

**Coupled air and weather intelligence for Delhi NCR**  
Smart India Hackathon 2026 · Problem Statement 26082 · LogiNexa

VayuSangam is an interactive prototype for exploring how atmospheric stability, ventilation, and transported smoke can influence air-quality forecasts. It combines a deterministic 72-hour replay, a coupled air-weather surrogate, and a browser dashboard.

> **Demo data:** The bundled Delhi winter episode is synthetic, deterministic replay data. It is not a live AQI feed, historical observation, operational weather-model output, or scientifically validated forecast.

## See it in action

The dashboard runs locally in your browser and includes:

- Forecast overview with AQI proxy, PM2.5, ozone, boundary-layer height, and ventilation.
- Interactive 72-hour timeline and station selection.
- Inversion diagnostics, smoke transport, model coupling, and driver explanations.
- Fire-reduction what-if scenario and a verification view for future validated data.
- Data archive views with source and coverage information when local archive data is available.

The replay map and smoke influence are schematic/model-derived demo outputs. The application does not claim live conditions or forecast accuracy.

## Run locally

You need **Python 3.11 or newer** and an internet connection for the initial package installation. No Node.js, database, API key, or Docker is required for the replay dashboard.

### 1. Download the project

If you have Git installed, open Terminal (macOS/Linux) or PowerShell (Windows), then run:

```bash
git clone <repository-url>
cd Vayusangam
```

Replace `<repository-url>` with the URL from the GitHub repository's **Code** button. If you downloaded a ZIP instead, extract it and open a terminal in the extracted `Vayusangam` folder.

### 2. Create and activate a virtual environment

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install the app dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-minimal.txt
```

### 4. Start the web app

From the project folder, run:

```bash
python -m uvicorn backend.app.main:app --reload
```

Wait for the message `Uvicorn running on http://127.0.0.1:8000`, then open **http://127.0.0.1:8000** in your browser. The API documentation is at **http://127.0.0.1:8000/docs**.

Keep the terminal open while using the app. To stop it, focus that terminal and press **Ctrl+C**. To run it again later, reopen a terminal in the project folder, activate `.venv` using the command above for your operating system, and run the Uvicorn command again.

> If port 8000 is already in use, start on another port with `python -m uvicorn backend.app.main:app --reload --port 8001` and visit http://127.0.0.1:8001.

### Troubleshooting

- **`python` not found:** Install Python 3.11+ and ensure it is available in your terminal. On Windows, use `py` in place of `python` if needed.
- **Activation is blocked in PowerShell:** Open Command Prompt and use `.venv\Scripts\activate.bat`, or adjust your local PowerShell execution policy according to your organization's guidance.
- **`No module named ...`:** Activate `.venv` and repeat the dependency installation step.
- **Browser cannot connect:** Check that Uvicorn is still running and that you opened the matching local URL and port.

## How it works

```text
Browser dashboard (HTML, CSS, JavaScript, inline SVG)
                         │
                         ▼
                FastAPI replay API
                  ├─ 72-hour coupled surrogate
                  ├─ deterministic replay data
                  └─ smoke particle transport demo
```

The frontend is served by FastAPI. The replay workflow works without external credentials or services. The model adjusts meteorological state using prior PM2.5, then feeds corrected conditions into the next pollution step. The smoke transport demonstration uses wind advection, diffusion, and age decay.

## API routes

The API includes health and station information, replay forecasts, grid and inversion data, smoke and coupling diagnostics, explanations, verification, and a smoke what-if endpoint. Local archive routes expose available station, air-quality, meteorology, and data-status information. Open `/docs` while the app is running for the complete interactive API reference.

## Optional: Docker Compose

The repository includes a multi-service Docker Compose configuration for the backend, frontend, and PostGIS database. This is an optional deployment path; use the local Python steps above for the simplest demo run. With Docker Desktop installed and running:

```bash
docker compose up --build
```

Then open **http://localhost:3000**. Stop the services with **Ctrl+C**; to remove the running containers, run `docker compose down`.

## Data and limitations

- The bundled replay is synthetic and deterministic; AQI is an approximate PM2.5 sub-index proxy, not a complete regulatory AQI.
- Historical archive files, when present, are separate from the synthetic forecast replay and include provenance and coverage limitations.
- NASA FIRMS, CAMS aerosols, pressure-level ERA5 inputs, and operational WRF-Chem/NCUM runs are not connected in this prototype.
- Verification scores remain blank until suitable validated historical data is available.

See [the model card](docs/model-card.md), [limitations](docs/limitations.md), [data sources](docs/DATA_SOURCES.md), and [data pipeline](docs/DATA_PIPELINE.md) for further details.

## Project documentation

- [Feature overview](docs/FEATURES.md)
- [Data UI mapping](docs/data-ui-mapping.md)
- [Data schema](docs/data-schema.md)
- [Frontend data contract](docs/frontend-data-contract.md)
- [Units](docs/UNITS.md)

## Optional data collection

OpenAQ collection requires a separate API key and setup. It is not needed to run the dashboard. See the [data pipeline guide](docs/DATA_PIPELINE.md) and `.env.example` for configuration details; keep real credentials out of Git and chat.
