# Frontend data contract

## Data classes

Every plotted value belongs to one source class:

| Class | Meaning | Display treatment |
|---|---|---|
| `observation` | OpenAQ hourly station measurement | Provider, station, interval timestamp and gaps shown. No regional aggregation from the one-station sample. |
| `reanalysis` | Retrospective Open-Meteo ERA5 archive | Label as reanalysis / historical; never as live weather. |
| `forecast_archive` | Open-Meteo Historical Forecast API values by valid time | Label as historical forecast archive. No forecast run or lead time is implied. |
| `derived` | Transparent calculation from one or more real fields | Name formula, inputs, units, time range and source classes. |
| `replay` | Deterministic synthetic surrogate / scenario | Keep DEMO / REPLAY visible; synthetic uncertainty, fire and plume remain confined to replay. |
| `unavailable` | Source field or sufficient coverage is absent | Render `—` or a short empty state; explain required source. Never substitute zero. |

## Entity shape

```text
Station {
  id: string
  name: string
  latitude: number
  longitude: number
  district: string | null
  provider: string | null
  owner: string | null
  timezone: "Asia/Kolkata"
  availability: { [field: string]: boolean }
  hasNormalizedObservations: boolean
}

TimeSeriesPoint {
  timestampUtc: string
  validTimeLocal: string
  value: number | null
  variable: string
  unit: string
  source: string
  dataClass: "observation" | "reanalysis" | "forecast_archive" | "derived" | "replay"
}

DataResult<T> {
  status: "ready" | "empty" | "error"
  source: string
  dataClass: string
  coverage: { startUtc: string | null, endUtc: string | null }
  retrievedAtUtc: string | null
  records: T[]
  limitations: string[]
}
```

Use nullable values rather than omitting unsupported pollutants. A zero is a measured or calculated zero only when its source actually supplied one. Empty, failed, stale, and unavailable are distinct UI states.

## Existing replay API

The following endpoints remain prototype/replay endpoints:

| Endpoint | Contract / label |
|---|---|
| `GET /api/health` | API liveness only, not data freshness. |
| `GET /api/stations` | Synthetic replay stations. Do not conflate these IDs with OpenAQ location IDs. |
| `GET /api/replay/{episode}` | Fixed-seed synthetic 72-hour replay. |
| `GET /api/forecast/station/{station_id}` | Replay station forecast. |
| `GET /api/forecast/grid?hour=` | Replay station values at a selected hour. |
| `GET /api/met/inversion?hour=` | Replay inversion and ventilation diagnostics. |
| `GET /api/fires`, `/api/smoke/plume?hour=` | Synthetic replay fire/particle data only. |
| `GET /api/coupling/{station_id}`, `/api/explain/{station_id}?hour=` | Replay coupling and explanation. |
| `POST /api/whatif/smoke` | Deterministic replay scenario; response remains labeled prototype. |
| `GET /api/verification` | Unavailable until an independent paired dataset is connected. |

## Real data endpoints to expose

Real source data should be served through small query responses; raw 1.7+ GiB OpenAQ JSON and full meteorology CSVs must never be embedded in the page.

| Endpoint | Query and response | Backing file / behavior |
|---|---|---|
| `GET /api/data/stations` | `Station[]`; 220 metadata records with per-field sensor availability and whether normalized sample rows exist | `station_metadata.csv`, `station_availability.csv`, `air_quality_hourly.csv`; station IDs remain strings. Metadata presence never asserts latest observation. |
| `GET /api/data/air-quality?station_id=&variable=&start=&end=` | UTC hourly nullable points and source/coverage metadata | Processed `air_quality_hourly.csv`; current sample is 72 hours for one station. Reject unknown station/variable; clamp the requested interval to actual data and do not fill. |
| `GET /api/data/meteorology?place=&product=&start=&end=&variable=` | Time series for one configured place and one product (`reanalysis` or `forecast_archive`), with units, UTC coverage and product label | Processed meteorology CSVs. Filter server-side; enforce a bounded time range/point cap. Derived speed/ventilation carry formula metadata. |
| `GET /api/data/status` | Per-source state, row counts, timestamp coverage, last valid observation and source product | Manifests + normalized tables. Separate retrieval time from observation/valid time. In-progress/stale manifests must be explicit. |

`GET /api/data/boundaries` is not part of the first real-data contract until NCR feature selection, map simplification, OSM attribution, and size/performance are verified. The source relation file is too large and contains geometries far outside NCR.

## UI state and interaction rules

- `overview` replay values keep the source banner, replay episode, valid time and surrogate version visible.
- The real-data explorer must not reuse replay AQI, fires, uncertainty or forecasts. Station choice filters real observation and weather charts only where IDs/time/location actually join.
- A selected station with metadata but no normalized measurements shows its real coordinates/provider/availability and an empty observations state.
- A variable with 100% missingness is unavailable; do not draw an empty zero line or offer it as an enabled chart variable.
- A time-range control affects the query window and chart, and the selected range/UTC coverage is shown in text.
- Historical archive charts use valid time and product class. They are not labelled NOW, LIVE, current, or 72-hour forecast.
- Loading and request failures preserve the previous valid data only if its timestamp/source stays visible; otherwise show an error with retry.
- Alerts and verification remain empty/unavailable for observations until a rule set or paired validation source exists. Demo alerts may be presented only inside the replay workflow with their rule and synthetic-data label.

## Performance and evolution

- Keep raw source files server-side. Read only normalized CSVs for the initial integration.
- Filter by station/place and date on the API; return a bounded series (the UI needs at most a few thousand points per request).
- Do not add a chart/map dependency just to draw the current inline SVG plots and station map. Revisit a tile/vector-map library when NCR boundaries, dense zoom/pan, or real fire layers are ready.
- If full OpenAQ history is normalized, preserve the source files, process to a compact indexed/partitioned table, validate it, then update the row/coverage numbers here. Do not rely on the raw cache while its collection manifest is stale.
