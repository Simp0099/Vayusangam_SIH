#!/usr/bin/env python3
"""Discover Delhi NCR / adjacent OpenAQ stations and cache their hourly v3 data."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from typing import Any

import pandas as pd

try:  # Support both direct script execution and imports from tests/tools.
    from .common import (
        AVAILABILITY_COLUMNS, DATA_DIR, LOG, OpenAQClient, OpenAQError,
        RAW_DIR, VARIABLES, coordinates, district_from_location, month_chunks, normalize_parameter,
        paged_get, region_bbox, requested_dates,
    )
except ImportError:
    from common import (
        AVAILABILITY_COLUMNS, DATA_DIR, LOG, OpenAQClient, OpenAQError,
        RAW_DIR, VARIABLES, coordinates, district_from_location, month_chunks, normalize_parameter,
        paged_get, region_bbox, requested_dates,
    )


def entity_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    if isinstance(value, str):
        return value
    return None


def span_days(sensor: dict[str, Any], start: date, end: date) -> int:
    first = ((sensor.get("datetimeFirst") or {}).get("utc"))
    last = ((sensor.get("datetimeLast") or {}).get("utc"))
    a = pd.to_datetime(first, utc=True, errors="coerce") if first else pd.NaT
    b = pd.to_datetime(last, utc=True, errors="coerce") if last else pd.NaT
    if pd.isna(a) or pd.isna(b):
        return 0
    return max(0, (min(b.date(), end) - max(a.date(), start)).days + 1)


def gov_priority(location: dict[str, Any]) -> int:
    text = " ".join([
        str(entity_name(location.get("owner")) or ""),
        str(entity_name(location.get("provider")) or ""),
        " ".join(str(x.get("name", "")) for x in (location.get("instruments") or []) if isinstance(x, dict)),
    ]).lower()
    terms = ("government", "govt", "cpcb", "pollution control", "reference monitor")
    return int(bool(location.get("isMonitor"))) * 2 + int(any(t in text for t in terms))


def atomic_csv(frame: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temp, index=False)
    temp.replace(path)


def discover(client: OpenAQClient, start: date, end: date, refresh: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    locations = list(paged_get(client, "/locations", {"iso": "IN", "bbox": region_bbox()}, RAW_DIR / "locations", "india-ncr-region", refresh))
    # OpenAQ query bounds cover NCR and adjacent Punjab/Haryana/UP source regions; no worldwide query is made.
    LOG.info("OpenAQ returned %d locations in configured India bbox", len(locations))
    rows_meta: list[dict[str, Any]] = []
    rows_avail: list[dict[str, Any]] = []
    rows_sensors: list[dict[str, Any]] = []
    for i, loc in enumerate(locations, 1):
        loc_id = loc.get("id")
        if loc_id is None:
            continue
        try:
            payload, cached = client.get(f"/locations/{loc_id}/sensors", {}, RAW_DIR / "sensors", f"location-{loc_id}", refresh)
            sensors = payload.get("results") or []
            sensor_lookup_status = "ok"
        except OpenAQError as exc:
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                raise
            LOG.error("Sensor lookup failed for location %s; recording metadata and continuing: %s", loc_id, exc)
            sensors = []
            sensor_lookup_status = "error"
        lat, lon = coordinates(loc)
        district, district_source = district_from_location(loc)
        provider, owner = entity_name(loc.get("provider")), entity_name(loc.get("owner"))
        mapped: dict[str, list[dict[str, Any]]] = {v: [] for v in VARIABLES}
        for sensor in sensors:
            p = sensor.get("parameter") or {}
            variable = normalize_parameter(p.get("name"), p.get("displayName"))
            if not variable:
                continue
            item = {
                "sensor_id": sensor.get("id"), "station_id": loc_id, "parameter": variable,
                "original_parameter": p.get("name"), "original_unit": p.get("units"),
                "datetime_first_utc": ((sensor.get("datetimeFirst") or {}).get("utc")),
                "datetime_last_utc": ((sensor.get("datetimeLast") or {}).get("utc")),
                "span_days_in_request": span_days(sensor, start, end),
                "is_monitor": bool(loc.get("isMonitor")), "provider": provider, "owner": owner,
            }
            mapped[variable].append(item)
            rows_sensors.append(item)
        # One sensor per station/variable keeps wide records unambiguous. Prefer the sensor with
        # the broadest declared historical span; location monitor/provider metadata breaks ties.
        selected: dict[str, dict[str, Any]] = {}
        for variable, options in mapped.items():
            if options:
                options.sort(key=lambda x: (x["span_days_in_request"], x["is_monitor"], -int(x["sensor_id"] or 0)), reverse=True)
                selected[variable] = options[0]
                for option in options:
                    option["selected_for_variable"] = option["sensor_id"] == selected[variable]["sensor_id"]
        avail = {
            "station_id": loc_id, "station_name": loc.get("name"), "latitude": lat, "longitude": lon,
            "provider": provider, "owner": owner, "sensor_lookup_status": sensor_lookup_status,
            "has_pm25": bool(mapped["PM2.5"]), "has_pm10": bool(mapped["PM10"]),
            "has_no2": bool(mapped["NO2"]), "has_nox": bool(mapped["NOx"]), "has_o3": bool(mapped["O3"]),
            "has_co": bool(mapped["CO"]), "has_so2": bool(mapped["SO2"]),
            "has_temperature": bool(mapped["temperature"]), "has_relative_humidity": bool(mapped["relative_humidity"]),
            "has_wind_speed": bool(mapped["wind_speed"]), "has_wind_direction": bool(mapped["wind_direction"]),
            "selected_for_download": any(x["span_days_in_request"] > 0 for x in mapped["PM2.5"]), "is_monitor": bool(loc.get("isMonitor")),
            "is_mobile": bool(loc.get("isMobile")),
            "sensor_ids_by_variable": json.dumps({v: [x["sensor_id"] for x in xs] for v, xs in mapped.items() if xs}, ensure_ascii=False),
        }
        rows_avail.append(avail)
        rows_meta.append({
            "station_id": loc_id, "station_name": loc.get("name"), "latitude": lat, "longitude": lon,
            "district": district, "district_source": district_source,
            "locality": loc.get("locality"), "provider": provider, "owner": owner,
            "sensor_lookup_status": sensor_lookup_status,
            "is_monitor": bool(loc.get("isMonitor")), "is_mobile": bool(loc.get("isMobile")),
            "instruments": json.dumps(loc.get("instruments") or [], ensure_ascii=False),
            "timezone": loc.get("timezone"),
            "datetime_first_utc": ((loc.get("datetimeFirst") or {}).get("utc")),
            "datetime_last_utc": ((loc.get("datetimeLast") or {}).get("utc")),
            "selected_for_download": any(x["span_days_in_request"] > 0 for x in mapped["PM2.5"]),
            "reference_priority": gov_priority(loc),
        })
        if i % 25 == 0:
            LOG.info("Inspected sensors at %d/%d locations", i, len(locations))
    rows_meta.sort(key=lambda x: (-x["reference_priority"], x["station_name"] or ""))
    rows_avail.sort(key=lambda x: (-int(x["is_monitor"]), not x["selected_for_download"], x["station_name"] or ""))
    return rows_meta, rows_avail, rows_sensors


def download_hours(client: OpenAQClient, sensors: list[dict[str, Any]], start: date, end: date, refresh: bool, max_stations: int | None, sample_days: int | None) -> tuple[int, int, list[int], date, date]:
    selected_sensors = [s for s in sensors if s.get("selected_for_variable") and s["parameter"] in VARIABLES]
    eligible_stations = {s["station_id"] for s in sensors if s["parameter"] == "PM2.5" and s.get("selected_for_variable") and s["span_days_in_request"] > 0}
    selected_sensors = [s for s in selected_sensors if s["station_id"] in eligible_stations]
    effective_start, effective_end = start, end
    if max_stations is not None:
        ranked = []
        for station_id in eligible_stations:
            rows = [s for s in selected_sensors if s["station_id"] == station_id]
            pm_rows = [s for s in rows if s["parameter"] == "PM2.5"]
            latest = max((pd.to_datetime(s["datetime_last_utc"], utc=True, errors="coerce") for s in pm_rows), default=pd.NaT)
            latest_date = latest.date() if not pd.isna(latest) else date.min
            span = max((s["span_days_in_request"] for s in pm_rows), default=0)
            ranked.append((station_id, latest_date, span))
        ranked.sort(key=lambda x: (x[1], x[2], str(x[0])), reverse=True)
        chosen = ranked[:max_stations]
        allowed = {sid for sid, _, _ in chosen}
        selected_sensors = [s for s in selected_sensors if s["station_id"] in allowed]
        if sample_days and chosen:
            effective_end = min(end, max(latest for _sid, latest, _span in chosen))
            effective_start = max(start, effective_end - timedelta(days=sample_days - 1))
    downloaded_stations = sorted({int(s["station_id"]) for s in selected_sensors})
    requests = cached = 0
    for sensor in selected_sensors:
        if sample_days:
            sensor_ranges = [(effective_start, effective_end + timedelta(days=1))] if effective_start <= effective_end else []
        else:
            # Avoid requesting months outside this sensor's declared history.
            first = pd.to_datetime(sensor.get("datetime_first_utc"), utc=True, errors="coerce")
            last = pd.to_datetime(sensor.get("datetime_last_utc"), utc=True, errors="coerce")
            sensor_start = max(start, first.date()) if not pd.isna(first) else start
            sensor_end = min(end, last.date()) if not pd.isna(last) else end
            sensor_ranges = list(month_chunks(sensor_start, sensor_end)) if sensor_start <= sensor_end else []
        for range_start, range_stop in sensor_ranges:
            params = {"datetime_from": f"{range_start.isoformat()}T00:00:00Z", "datetime_to": f"{range_stop.isoformat()}T00:00:00Z"}
            prefix = f"sensor-{sensor['sensor_id']}-{range_start:%Y%m}"
            for _row in paged_get(client, f"/sensors/{sensor['sensor_id']}/hours", params, RAW_DIR / "hours", prefix, refresh):
                pass
            requests += 1
            if not refresh and list((RAW_DIR / "hours").glob(f"{prefix}_*.json")):
                # Count physical request/cache segments only for a useful progress summary.
                cached += 1
            if requests % 100 == 0:
                LOG.info("Hourly chunks processed: %d", requests)
    return requests, cached, downloaded_stations, effective_start, effective_end


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", help="Inclusive YYYY-MM-DD; defaults to OPENAQ_START_DATE or 2024-01-01")
    parser.add_argument("--end-date", help="Inclusive YYYY-MM-DD; defaults to OPENAQ_END_DATE or today")
    parser.add_argument("--check-connection", action="store_true", help="Authenticate a single small v3 parameters request")
    parser.add_argument("--sample", action="store_true", help="Discover all stations; download recent three days for the best one available")
    parser.add_argument("--sample-stations", type=int, default=1)
    parser.add_argument("--sample-days", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="Fetch new raw snapshots with timestamped filenames; existing raw files remain untouched")
    args = parser.parse_args()
    try:
        start, end = requested_dates(args.start_date, args.end_date)
        if args.sample and args.sample_days < 1:
            raise OpenAQError("--sample-days must be at least 1.")
        client = OpenAQClient()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if args.check_connection:
            payload, cached = client.get("/parameters", {"limit": 1, "page": 1}, RAW_DIR / "health", "api-check", args.refresh)
            print(f"OpenAQ v3 connection: OK ({len(payload.get('results') or [])} parameter sample; {'cached' if cached else 'authenticated request'})")
            client.close()
            return 0
        print(f"Requested inclusive date range: {start} → {end}")
        print(f"Search scope: India bbox {region_bbox()} (Delhi NCR plus adjacent north-west source regions)")
        client.get("/parameters", {"limit": 1, "page": 1}, RAW_DIR / "health", "api-check", args.refresh)
        metadata, availability, sensors = discover(client, start, end, args.refresh)
        metadata_columns = ["station_id", "station_name", "latitude", "longitude", "district", "district_source", "locality", "provider", "owner", "sensor_lookup_status", "is_monitor", "is_mobile", "instruments", "timezone", "datetime_first_utc", "datetime_last_utc", "selected_for_download", "reference_priority"]
        atomic_csv(pd.DataFrame(metadata, columns=metadata_columns), DATA_DIR / "station_metadata.csv")
        atomic_csv(pd.DataFrame(availability, columns=AVAILABILITY_COLUMNS), DATA_DIR / "station_availability.csv")
        atomic_csv(pd.DataFrame(sensors, columns=["sensor_id", "station_id", "parameter", "original_parameter", "original_unit", "datetime_first_utc", "datetime_last_utc", "span_days_in_request", "is_monitor", "provider", "owner", "selected_for_variable"]), DATA_DIR / "sensor_metadata.csv")
        selected = sum(bool(s.get("selected_for_download")) for s in availability)
        LOG.info("Locations discovered=%d; PM2.5 stations selected=%d", len(metadata), selected)

        # Write an IN-PROGRESS manifest before the (long, interruptible) hourly
        # download starts. The audit of 2026-09-30 found a manifest still reading
        # sample_mode=true from an earlier run while a full production download was
        # actually running — a reader had no way to tell which state was current.
        # An explicit "in_progress" state is written now and overwritten on success.
        manifest_path = DATA_DIR / "collection_manifest.json"
        if not args.sample:
            manifest_path.write_text(json.dumps({
                "api_version": "v3", "status": "in_progress", "phase": "hourly_download",
                "started_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                "bbox_wgs84": region_bbox(), "country_iso": "IN",
                "requested_start_date": start.isoformat(), "requested_end_date": end.isoformat(),
                "sample_mode": False,
                "note": ("Hourly download in progress or interrupted. The raw cache under "
                         "raw/hours is authoritative; air_quality_hourly.csv is NOT yet "
                         "regenerated from it. Re-run this command to resume."),
            }, indent=2), encoding="utf-8")
        if args.sample:
            chunks, _, downloaded_station_ids, effective_start, effective_end = download_hours(client, sensors, start, end, args.refresh, max(1, args.sample_stations), args.sample_days)
        else:
            chunks, _, downloaded_station_ids, effective_start, effective_end = download_hours(client, sensors, start, end, args.refresh, None, None)
        (DATA_DIR / "collection_manifest.json").write_text(json.dumps({
            "api_version": "v3", "status": "complete", "phase": "done",
            "completed_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "bbox_wgs84": region_bbox(), "country_iso": "IN",
            "requested_start_date": effective_start.isoformat(), "requested_end_date": effective_end.isoformat(),
            "source_start_date": start.isoformat(), "source_end_date": end.isoformat(),
            "sample_mode": bool(args.sample), "downloaded_station_ids": downloaded_station_ids,
            "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        }, indent=2), encoding="utf-8")
        client.close()
        print(f"Stations discovered: {len(metadata)}")
        print(f"Stations selected by PM2.5 sensor availability: {selected}")
        print(f"Requested date range: {start} → {end} (no date reduction)")
        if args.sample:
            print(f"Sample window aligned to latest selected PM2.5 sensor data: {effective_start} → {effective_end}")
        print(f"Sensor/month chunks processed: {chunks}")
        print("Next: python scripts/data_collection/openaq/process_openaq.py")
        print("Then: python scripts/data_collection/openaq/validate_openaq.py")
        return 0
    except OpenAQError as exc:
        print(f"OpenAQ collection stopped: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted. Raw pages already written are retained; rerun to resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
