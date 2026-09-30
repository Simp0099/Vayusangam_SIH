#!/usr/bin/env python3
"""Deliberately-broken manifests must FAIL, not silently pass.

A validator that has never been shown a broken input is an unverified
component. Each case below feeds validate_manifests() a manifest that is wrong
in one specific way and asserts the specific finding comes back.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.data_collection import validate_all  # noqa: E402


def _good() -> dict:
    return {
        "source": "openaq",
        "dataset": "test",
        "lifecycle": "complete",
        "download_timestamp_utc": "2026-09-30T00:00:00+00:00",
        "files": [{"file": "a.json", "bytes": 10, "sha256": "x"}],
        "files_omitted": 0,
    }


def _run(payload: dict, filename: str = "openaq_manifest.json") -> tuple[list[str], list[str]]:
    folder = Path(validate_all.DATA) / "manifests"
    original = folder / filename
    backup = original.read_text(encoding="utf-8") if original.exists() else None
    try:
        original.write_text(json.dumps(payload), encoding="utf-8")
        return validate_all.validate_manifests()[1:]
    finally:
        if backup is None:
            original.unlink(missing_ok=True)
        else:
            original.write_text(backup, encoding="utf-8")


def test_healthy_manifest_passes() -> None:
    problems, warnings = _run(_good())
    assert not problems, f"healthy manifest flagged: {problems}"
    assert not warnings, f"healthy manifest warned: {warnings}"


def test_missing_lifecycle_fails() -> None:
    payload = _good()
    del payload["lifecycle"]
    problems, _ = _run(payload)
    assert any("lifecycle" in p for p in problems), f"undetected: {problems}"


def test_missing_timestamp_fails() -> None:
    payload = _good()
    del payload["download_timestamp_utc"]
    problems, _ = _run(payload)
    assert any("download_timestamp_utc" in p for p in problems), f"undetected: {problems}"


def test_missing_files_key_fails() -> None:
    payload = _good()
    del payload["files"]
    problems, _ = _run(payload)
    assert any("'files'" in p for p in problems), f"undetected: {problems}"


def test_in_progress_warns_and_does_not_read_as_final() -> None:
    payload = _good() | {"lifecycle": "in_progress"}
    problems, warnings = _run(payload)
    assert any("in_progress" in w for w in warnings), f"undetected: {warnings}"
    assert not any("in_progress" in p for p in problems), "in_progress is a warning, not a failure"


def test_omitted_files_is_a_problem_not_a_warning() -> None:
    """A silently truncated inventory is the exact bug this guards against."""
    payload = _good() | {"files_omitted": 11230}
    problems, _ = _run(payload)
    assert any("omitted" in p for p in problems), f"undetected: {problems}"


def test_invalid_json_fails() -> None:
    folder = Path(validate_all.DATA) / "manifests"
    original = folder / "broken_manifest.json"
    original.write_text("{not json", encoding="utf-8")
    try:
        problems, _ = validate_all.validate_manifests()[1:]
        assert any("invalid JSON" in p for p in problems), f"undetected: {problems}"
    finally:
        original.unlink(missing_ok=True)


def test_redactor_strips_key_from_query_and_path() -> None:
    from scripts.data_collection.write_manifest import redact

    assert "SUPERSECRET" not in redact("https://api.x.org/v3/hours?api_key=SUPERSECRET&limit=10")

    # A key carried as a path segment, at a realistic key length. The fixture
    # must be realistic: a path rule cannot distinguish a short opaque segment
    # from an ordinary name like "meteorology", so anything below the length
    # threshold is left alone by design.
    key = "a3f9c1d7e5b2048fa6c9137d2e8b40f15c2a9d6e3b7104c8f2a5e9d1b6c3f7082"
    for url in (f"https://api.x.org/v3/{key}",
                f"https://api.x.org/v3/{key}/hours",
                f"https://api.x.org/{key}"):
        assert key not in redact(url), f"key leaked through path: {url} -> {redact(url)}"

    assert redact("https://api.x.org/v3/hours?limit=10") == "https://api.x.org/v3/hours?limit=10"


def test_redactor_preserves_hostname_and_normal_paths() -> None:
    """A long hostname is a 16+ segment; redacting it destroys provenance for nothing."""
    from scripts.data_collection.write_manifest import redact

    for url in ("https://overpass-api.de/api/interpreter",
                "https://historical-forecast-api.open-meteo.com/v1/forecast",
                "https://api.openaq.org/v3/sensors/1234/hours"):
        assert redact(url) == url, f"mangled a non-secret URL: {url} -> {redact(url)}"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"[FAIL] {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
