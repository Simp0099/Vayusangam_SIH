#!/usr/bin/env python3
"""Extract credentials from RTF / text-clipping wrappers into usable config.

The supplied files are macOS RTF and .textClipping documents, so the values are
embedded in RTF markup rather than being plain text. This strips the markup and
writes a real config file WITHOUT printing any secret to stdout or logs.

    .venv/bin/python scripts/data_collection/install_credentials.py

Writes ~/.cdsapirc (mode 600) and puts FIRMS_MAP_KEY into the project .env.
"""
from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CRED_DIR = PROJECT_ROOT.parent / "Api - Vayusangam"
CDS_RTF = CRED_DIR / ".cdsapirc.rtf"
FIRMS_CLIP = CRED_DIR / "Map Key - Firm.textClipping"
CDS_TARGET = Path.home() / ".cdsapirc"
ENV_FILE = PROJECT_ROOT / ".env"


def strip_rtf(text: str) -> str:
    """Reduce RTF to its plain-text content runs."""
    text = re.sub(r"\{\\\*?\\[a-z]+-?\d*[^\s{}]*\s?", "{", text)
    text = re.sub(r"\\[a-z]+-?\d*\s?", "", text)
    text = re.sub(r"\\[!'*+\-.,@:^_`|~][0-9a-f]{2}", "", text, flags=re.I)
    text = text.replace("{", "").replace("}", "")
    return text.replace("\r", "\n")


def fingerprint(value: str) -> str:
    """Non-reversible identifier so logs can prove WHICH key was used."""
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def main() -> int:
    if not CDS_RTF.exists():
        print(f"missing {CDS_RTF}", file=sys.stderr)
        return 2

    plain = strip_rtf(CDS_RTF.read_text(errors="replace"))
    url = re.search(r"url:\s*(\S+)", plain)
    key = re.search(r"key:\s*([0-9a-zA-Z\-_]+)", plain)
    if not url or not key:
        print("could not parse url/key from the RTF", file=sys.stderr)
        return 2

    url_v, key_v = url.group(1), key.group(1)
    # The RTF leaves a trailing backslash on the URL; cdsapi would treat it as
    # part of the endpoint and fail with an opaque error.
    url_v = url_v.rstrip("\\").strip()
    body = f"url: {url_v}\nkey: {key_v}\n"
    CDS_TARGET.write_text(body, encoding="utf-8")
    CDS_TARGET.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600

    print(f"wrote {CDS_TARGET} (mode 600)")
    print(f"  url  = {url_v}")
    print(f"  key  = <redacted, len {len(key_v)}, fingerprint {fingerprint(key_v)}>")

    if FIRMS_CLIP.exists():
        raw = FIRMS_CLIP.read_text(errors="replace")
        candidate = None
        try:  # a .textClipping may be a binary plist
            import subprocess
            out = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(FIRMS_CLIP)],
                                 capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and out.stdout.strip():
                raw = out.stdout
        except Exception:  # noqa: BLE001
            pass
        flat = strip_rtf(raw)
        # The key is ALPHANUMERIC (32 chars, includes letters outside a-f), so a
        # hex-only pattern silently truncates it to a prefix and FIRMS answers
        # "Invalid MAP_KEY". Match the full alphanumeric token instead.
        token = re.search(r"\b([0-9a-zA-Z]{24,64})\b", flat)
        if token:
            fk = token.group(1)
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
            lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
            lines = [l for l in lines if not l.startswith("FIRMS_MAP_KEY=")]
            lines.append(f"FIRMS_MAP_KEY={fk}")
            ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ENV_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
            print(f"wrote FIRMS_MAP_KEY to {ENV_FILE} (mode 600)")
            print(f"  key  = <redacted, len {len(fk)}, fingerprint {fingerprint(fk)}>")
        else:
            print("FIRMS key: no hex token found in the clipping", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())