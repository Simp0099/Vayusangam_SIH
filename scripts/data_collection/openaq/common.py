"""OpenAQ v3 data access and unit normalization used by the VayuSangam pipeline."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx
import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data" / "air_quality"
RAW_DIR = DATA_DIR / "raw"
API_BASE = "https://api.openaq.org/v3"
PAGE_LIMIT = 1000
VARIABLES = ["PM2.5", "PM10", "NO2", "NOx", "O3", "CO", "SO2", "temperature", "relative_humidity", "wind_speed", "wind_direction"]
EXPECTED_COLUMNS = ["station_id", "station_name", "latitude", "longitude", "district", "source_provider", "timestamp", *VARIABLES]
PARAMETER_ALIASES = {
    "pm25":"PM2.5", "pm2.5":"PM2.5", "pm_2_5":"PM2.5", "pm10":"PM10", "pm_10":"PM10",
    "no2":"NO2", "nitrogen dioxide":"NO2", "nox":"NOx", "nitrogen oxides":"NOx",
    "o3":"O3", "ozone":"O3", "co":"CO", "carbon monoxide":"CO", "so2":"SO2",
    "sulfur dioxide":"SO2", "sulphur dioxide":"SO2", "temperature":"temperature", "temp":"temperature",
    "relativehumidity":"relative_humidity", "relative_humidity":"relative_humidity", "humidity":"relative_humidity",
    "windspeed":"wind_speed", "wind_speed":"wind_speed", "wind direction":"wind_direction",
    "winddirection":"wind_direction", "wind_direction":"wind_direction",
}
FINAL_UNITS = {"PM2.5":"µg/m³", "PM10":"µg/m³", "NO2":"ppb", "NOx":"ppb", "O3":"ppb", "CO":"ppb", "SO2":"ppb", "temperature":"°C", "relative_humidity":"%", "wind_speed":"m/s", "wind_direction":"degrees"}
AVAILABILITY_COLUMNS = ["station_id", "station_name", "latitude", "longitude", "provider", "owner", "sensor_lookup_status", "has_pm25", "has_pm10", "has_no2", "has_nox", "has_o3", "has_co", "has_so2", "has_temperature", "has_relative_humidity", "has_wind_speed", "has_wind_direction", "selected_for_download", "is_monitor", "is_mobile", "sensor_ids_by_variable"]

logging.basicConfig(level=os.getenv("OPENAQ_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("vayusangam.openaq")


class OpenAQError(RuntimeError):
    pass


class MissingAPIKey(OpenAQError):
    pass


def load_project_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def api_key() -> str:
    load_project_env()
    key = os.getenv("OPENAQ_API_KEY", "").strip()
    if not key:
        raise MissingAPIKey("OPENAQ_API_KEY is missing. Add OPENAQ_API_KEY=your_key to the project .env file (copy .env.example first if needed). Do not paste your key into chat or commit .env.")
    return key


def requested_dates(start: str | None = None, end: str | None = None) -> tuple[date, date]:
    load_project_env()
    start = start or os.getenv("OPENAQ_START_DATE", "2024-01-01")
    end = end or os.getenv("OPENAQ_END_DATE", "") or date.today().isoformat()
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise OpenAQError("Dates must use YYYY-MM-DD format.") from exc
    if last < first:
        raise OpenAQError("End date must be on or after start date.")
    return first, last


def region_bbox() -> str:
    load_project_env()
    value = os.getenv("OPENAQ_BBOX", "74.0,26.0,80.0,32.5").strip()
    try:
        west, south, east, north = map(float, value.split(","))
    except ValueError as exc:
        raise OpenAQError("OPENAQ_BBOX must be west,south,east,north in WGS84.") from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise OpenAQError("OPENAQ_BBOX has invalid WGS84 bounds.")
    return ",".join(f"{n:.4f}" for n in (west, south, east, north))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def raw_snapshot_path(folder: Path, name: str, query: dict[str, Any], refresh: bool = False) -> Path:
    digest = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()[:10]
    # Include microseconds so repeated refreshes in the same second never replace an earlier raw response.
    version = "_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") if refresh else ""
    return folder / f"{name}_{digest}{version}.json"


class OpenAQClient:
    def __init__(self, key: str | None = None, timeout: float = 60, attempts: int = 6):
        self.key, self.attempts = key or api_key(), attempts
        self.rate_remaining: int | None = None
        self.rate_reset_monotonic: float | None = None
        self.client = httpx.Client(base_url=API_BASE, headers={"X-API-Key": self.key, "Accept": "application/json", "User-Agent": "VayuSangam-OpenAQ/1.0"}, timeout=httpx.Timeout(timeout, connect=20))

    def close(self) -> None:
        self.client.close()

    def _record_rate_headers(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        try:
            if remaining is not None:
                self.rate_remaining = int(remaining)
            if reset is not None:
                seconds = float(reset)
                # OpenAQ documents a seconds-until-reset value; tolerate epoch timestamps too.
                if seconds > time.time():
                    seconds = max(0.0, seconds - time.time())
                self.rate_reset_monotonic = time.monotonic() + max(0.0, min(seconds, 3600.0))
            elif self.rate_remaining == 0:
                self.rate_reset_monotonic = time.monotonic() + 60.0
        except (TypeError, ValueError):
            return

    def _wait_for_rate_window(self) -> None:
        if self.rate_remaining == 0 and self.rate_reset_monotonic is not None:
            delay = max(0.0, self.rate_reset_monotonic - time.monotonic()) + 0.25
            if delay > 0.25:
                LOG.info("OpenAQ request quota exhausted; waiting %.1fs for rate-limit reset", delay)
                time.sleep(delay)
            self.rate_remaining = None

    def get(self, endpoint: str, params: dict[str, Any], raw_folder: Path, raw_name: str, refresh: bool = False) -> tuple[dict[str, Any], bool]:
        path = raw_snapshot_path(raw_folder, raw_name, params, refresh)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")), True
            except json.JSONDecodeError:
                LOG.warning("Invalid cache ignored: %s", path)
        for attempt in range(self.attempts):
            try:
                self._wait_for_rate_window()
                response = self.client.get(endpoint, params=params)
                self._record_rate_headers(response)
                if response.status_code == 429 or response.status_code >= 500:
                    # Keep honoring rate-limit backoff; persistent server errors are retried
                    # twice before the station-level caller records the lookup as failed.
                    if response.status_code >= 500 and attempt >= 2:
                        raise OpenAQError(f"OpenAQ returned HTTP {response.status_code} for {endpoint} after 3 attempts.")
                    delay_header = response.headers.get("Retry-After", "")
                    reset_header = response.headers.get("x-ratelimit-reset", "")
                    if delay_header.replace(".", "", 1).isdigit():
                        delay = float(delay_header)
                    elif reset_header.replace(".", "", 1).isdigit():
                        delay = float(reset_header)
                    elif response.status_code == 429:
                        delay = 60.0
                    else:
                        delay = min(60, 2**attempt)
                    if response.status_code == 429:
                        delay = max(1.0, delay)
                    if attempt + 1 < self.attempts:
                        LOG.warning("OpenAQ HTTP %s; retrying after %ss", response.status_code, delay)
                        time.sleep(delay)
                        # The explicit delay above already waits for the server's reset interval.
                        self.rate_remaining = None
                        continue
                if response.status_code in (401, 403):
                    raise OpenAQError(f"OpenAQ rejected OPENAQ_API_KEY (HTTP {response.status_code}); check or rotate the key.")
                response.raise_for_status()
                payload = response.json()
                atomic_json(path, payload)  # API secrets are request headers and never written to raw files.
                return payload, False
            except OpenAQError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError) as exc:
                if attempt + 1 == self.attempts:
                    raise OpenAQError(f"OpenAQ request failed for {endpoint}: {exc}") from exc
                delay = min(60, 2**attempt)
                LOG.warning("OpenAQ request error (%s); retrying after %ss", type(exc).__name__, delay)
                time.sleep(delay)
        raise OpenAQError(f"OpenAQ request failed after {self.attempts} attempts: {endpoint}")


def paged_get(client: OpenAQClient, endpoint: str, params: dict[str, Any], raw_folder: Path, prefix: str,
              refresh: bool = False, max_items: int | None = None) -> Iterator[dict[str, Any]]:
    page, emitted = 1, 0
    while True:
        query = {**params, "limit": PAGE_LIMIT, "page": page}
        payload, cached = client.get(endpoint, query, raw_folder, f"{prefix}_page{page:04d}", refresh)
        results = payload.get("results") or []
        LOG.info("%s page %s: %d rows (%s)", prefix, page, len(results), "cache" if cached else "download")
        if not results:
            return
        for row in results:
            if max_items is not None and emitted >= max_items:
                return
            yield row
            emitted += 1
        found = (payload.get("meta") or {}).get("found")
        try:
            pages = math.ceil(int(found) / PAGE_LIMIT) if found is not None else None
        except (TypeError, ValueError):
            pages = None
        if (pages is not None and page >= pages) or len(results) < PAGE_LIMIT:
            return
        page += 1


def normalize_parameter(name: Any, display_name: Any = None) -> str | None:
    for item in (name, display_name):
        if item is None:
            continue
        key = re.sub(r"\s+", " ", str(item).strip().lower())
        if key in PARAMETER_ALIASES:
            return PARAMETER_ALIASES[key]
        compact = re.sub(r"[\s._-]+", "", key)
        if compact in PARAMETER_ALIASES:
            return PARAMETER_ALIASES[compact]
    return None


def _unit_key(unit: Any) -> str:
    s = str(unit or "").strip().lower().replace("μg", "ug").replace("µg", "ug").replace("³", "3").replace("²", "2").replace("°", "").replace(" ", "")
    return s.replace("per", "/")


def normalize_value(variable: str, unit: Any, value: Any) -> tuple[float | None, str, str | None]:
    """Convert recognized units only. Unsupported values remain null and raw payloads are retained."""
    if value is None:
        return None, FINAL_UNITS.get(variable, str(unit or "")), None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None, FINAL_UNITS.get(variable, str(unit or "")), "not_numeric"
    if not math.isfinite(x):
        return None, FINAL_UNITS.get(variable, str(unit or "")), "non_finite"
    u = _unit_key(unit)
    if variable in {"PM2.5", "PM10"}:
        if u in {"ug/m3", "ug/m^3"}: out = x
        elif u in {"mg/m3", "mg/m^3"}: out = x * 1000
        else: return None, FINAL_UNITS[variable], "unsupported_unit"
    elif variable in {"NO2", "NOx", "O3", "CO", "SO2"}:
        if u in {"ppb", "nmol/mol"}: out = x
        elif u in {"ppm", "umol/mol"}: out = x * 1000
        else: return None, FINAL_UNITS[variable], "unsupported_unit"  # no assumed T/P for mass-to-mole conversion
    elif variable == "temperature":
        if u in {"c", "degc", "celsius"}: out = x
        elif u in {"f", "degf", "fahrenheit"}: out = (x - 32) * 5 / 9
        elif u in {"k", "kelvin"}: out = x - 273.15
        else: return None, FINAL_UNITS[variable], "unsupported_unit"
    elif variable == "relative_humidity":
        if u in {"%", "percent", "percentage"}: out = x
        elif u in {"1", "fraction", "unitless"} and 0 <= x <= 1: out = x * 100
        else: return None, FINAL_UNITS[variable], "unsupported_unit"
    elif variable == "wind_speed":
        if u in {"m/s", "mps", "ms-1", "m.s-1"}: out = x
        elif u in {"km/h", "kph", "kmh-1"}: out = x / 3.6
        elif u in {"mph", "mi/h"}: out = x * 0.44704
        elif u in {"kn", "knot", "knots"}: out = x * 0.514444
        else: return None, FINAL_UNITS[variable], "unsupported_unit"
    elif variable == "wind_direction":
        if u in {"degree", "degrees", "deg"}: out = x
        else: return None, FINAL_UNITS[variable], "unsupported_unit"
    else:
        return None, "", "unmapped_parameter"
    if variable in {"PM2.5", "PM10", "NO2", "NOx", "O3", "CO", "SO2", "relative_humidity", "wind_speed"} and out < 0:
        return None, FINAL_UNITS[variable], "negative_value"
    if variable == "relative_humidity" and out > 100: return None, FINAL_UNITS[variable], "out_of_range"
    if variable == "wind_direction" and not 0 <= out <= 360: return None, FINAL_UNITS[variable], "out_of_range"
    if variable == "temperature" and not -100 <= out <= 70: return None, FINAL_UNITS[variable], "out_of_range"
    return out, FINAL_UNITS[variable], None


def month_chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Yield request bounds [start, end) at month boundaries, including the requested end date."""
    cursor, stop = start.replace(day=1), end + timedelta(days=1)
    while cursor < stop:
        next_month = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
        left, right = max(start, cursor), min(stop, next_month)
        if left < right:
            yield left, right
        cursor = next_month


def district_from_location(location: dict[str, Any]) -> tuple[str | None, str | None]:
    for field in ("district", "adminArea", "administrativeArea", "subdivision"):
        value = location.get(field)
        if isinstance(value, dict): value = value.get("name")
        if isinstance(value, str) and value.strip(): return value.strip(), f"openaq:{field}"
    locality = str(location.get("locality") or "").strip().lower()
    aliases = {"gurugram":"Gurugram", "gurgaon":"Gurugram", "faridabad":"Faridabad", "ghaziabad":"Ghaziabad", "noida":"Gautam Buddha Nagar"}
    return (aliases[locality], "explicit locality-to-district alias") if locality in aliases else (None, None)


def coordinates(location: dict[str, Any]) -> tuple[float | None, float | None]:
    coords = location.get("coordinates") or {}
    return coords.get("latitude"), coords.get("longitude")


def timestamp_utc(row: dict[str, Any]) -> str | None:
    period = row.get("period") or {}
    coverage = row.get("coverage") or {}
    dt = row.get("datetimeFrom") or row.get("datetime") or period.get("datetimeFrom") or coverage.get("datetimeFrom") or {}
    raw = dt.get("utc") if isinstance(dt, dict) else dt
    parsed = pd.to_datetime(raw, utc=True, errors="coerce") if raw else pd.NaT
    return None if pd.isna(parsed) else parsed.floor("h").isoformat().replace("+00:00", "Z")
