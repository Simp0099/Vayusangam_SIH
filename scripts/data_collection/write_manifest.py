#!/usr/bin/env python3
"""Record dataset provenance in data/manifests/.

Every collected dataset gets one JSON manifest describing what was downloaded,
from where, when, and with what checksums, so a run can be reproduced and
audited. Secrets are never written: URLs are passed through a redactor that
replaces any known key/token before the string is stored.

    .venv/bin/python scripts/data_collection/write_manifest.py openaq
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
PROCESSING_VERSION = "1.0.0"


def redact(text: str) -> str:
    """Strip anything credential-shaped from a URL or path before it is stored.

    Three layers, because each covers a leak the others miss:
      1. Literal known secrets read from the environment. A redactor that only
         pattern-matches will happily pass through a key whose alphabet it did
         not anticipate.
      2. Credential-shaped query parameters (?key=, ?api_key=, &token= ...).
      3. Opaque path segments. A key as the final segment has no trailing
         delimiter to anchor on, so end-of-string must count as a terminator.
    """
    for secret in _known_secrets():
        if len(secret) >= 8 and secret in text:
            text = text.replace(secret, "<REDACTED>")
    text = re.sub(r"(?i)([?&](?:key|api_key|apikey|token|access_token|MAP_KEY)=)[^&\s]+",
                  r"\1<REDACTED>", text)
    # Any path segment of 16+ token-ish characters, including at end of string.
    # Applied after the scheme+host only: a long hostname ("historical-forecast-api")
    # is a segment too, and redacting it would destroy the endpoint's provenance
    # while protecting nothing.
    def _redact_path(m: re.Match[str]) -> str:
        prefix, path = m.group(1), m.group(2)
        return prefix + re.sub(r"(?<=/)[\w~-]{16,}(?=/|$)", "<REDACTED>", path)

    return re.sub(r"^([a-zA-Z][\w+.-]*://[^/\s]+)(/\S*)?$", _redact_path, text)


def _known_secrets() -> list[str]:
    """Values of any credential-looking env var, so real keys can be matched literally.

    Read from the process environment first, then from the project .env, since the
    collector may run with the key in either place.
    """
    out: list[str] = []
    names = [k for k in os.environ if re.search(r"(?i)(key|token|secret|password)", k)]
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                value = value.strip().strip("'\"")
                if value and re.search(r"(?i)(key|token|secret|password)", name):
                    out.append(value)
        except OSError:
            pass
    out.extend(os.environ[n] for n in names if os.environ.get(n))
    return out


def checksum(path: Path) -> str | None:
    """SHA-256 of a file. Returns None for files over 200 MB (too slow to hash inline)."""
    try:
        if path.stat().st_size > 200 * 1024 * 1024:
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def describe_files(root: Path, limit: int = 2000, checksum_files: bool = True) -> tuple[list[dict], int]:
    """Describe every file under root.

    Returns (entries, truncated_count). Truncation is reported, never silent: a
    manifest that quietly listed the first 2000 of 25,000 files would describe a
    fraction of the download while reading as complete.
    """
    out = []
    # A path given relative to cwd is not under PROJECT_ROOT, so resolve both and
    # fall back to the absolute path rather than raising on relative_to().
    root = root if root.is_absolute() else (PROJECT_ROOT / root)
    root = root.resolve()
    if not root.exists():
        return out, 0
    truncated = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if len(out) >= limit:
            truncated += 1
            continue
        try:
            name = str(p.relative_to(PROJECT_ROOT))
        except ValueError:
            name = str(p)
        out.append({"file": name, "bytes": p.stat().st_size,
                    "sha256": checksum(p) if checksum_files else None})
    return out, truncated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="openaq | fires | meteorology | era5 | cams | geospatial")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--url", default="", help="API endpoint (redacted before storage)")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--area", default="", help="Human-readable geographic area")
    parser.add_argument("--variables", default="")
    parser.add_argument("--raw-dir", default="", help="Directory whose files are described")
    parser.add_argument("--license", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--lifecycle", default="complete",
                        choices=["in_progress", "complete", "sample"],
                        help="in_progress is written at the START of a long run and "
                             "overwritten with complete on success, so a reader can never "
                             "infer the run's scope from a superseded manifest.")
    parser.add_argument("--file-limit", type=int, default=2000,
                        help="Max files listed. Anything beyond is counted in "
                             "files_omitted rather than silently dropped.")
    parser.add_argument("--no-checksums", action="store_true",
                        help="Skip hashing (use while a download is still running).")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir) if args.raw_dir else PROJECT_ROOT / "data" / args.source / "raw"
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    files, files_omitted = describe_files(raw_dir, limit=args.file_limit,
                                         checksum_files=not args.no_checksums)
    payload = {
        "source": args.source,
        "dataset": args.dataset or args.source,
        "lifecycle": args.lifecycle,
        "url_api": redact(args.url),
        "download_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "date_range": {"start": args.start_date, "end": args.end_date},
        "geographic_area": args.area,
        "variables": [v.strip() for v in args.variables.split(",") if v.strip()],
        "processing_version": PROCESSING_VERSION,
        "license": args.license,
        "notes": args.notes,
        "files": files,
    }
    payload["total_bytes"] = sum(f["bytes"] for f in payload["files"])
    payload["files_omitted"] = files_omitted
    payload["checksums_skipped"] = sum(1 for f in payload["files"] if f["sha256"] is None)

    out = MANIFEST_DIR / f"{args.source}_manifest.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(payload['files'])} files, {payload['total_bytes'] / 1e6:.1f} MB)"
          f" [lifecycle={args.lifecycle}]")
    if payload["files_omitted"]:
        print(f"  {payload['files_omitted']} file(s) NOT listed (over --file-limit "
              f"{args.file_limit}); raise the limit for a complete inventory")
    if payload["checksums_skipped"]:
        print(f"  {payload['checksums_skipped']} file(s) without a sha256 "
              f"(over 200 MB, or --no-checksums)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
