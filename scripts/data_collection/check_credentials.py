#!/usr/bin/env python3
"""Read-only credential and source-availability check for VayuSangam.

Prints whether each credential is present. Secrets are never printed: only
presence, length, and a 3-character fingerprint of the key, which is enough to
tell two keys apart without disclosing either.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "DATABASE_URL")


def fingerprint(value: str) -> str:
    return f"{value[:3]}…({len(value)} chars)"


def main() -> int:
    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"
    values = dict(dotenv_values(env_path)) if env_path.exists() else {}
    # A value still identical to the template is an unfilled placeholder. Comparing
    # against the template is exact; guessing from the value's shape is not.
    template = dict(dotenv_values(example_path)) if example_path.exists() else {}
    print(f".env present: {'yes' if env_path.exists() else 'NO — copy .env.example to .env'}")
    print("\nCredential status (values are never printed):")
    for key, value in sorted(values.items()):
        if not any(h in key.upper() for h in SECRET_HINTS):
            continue
        value = (value or "").strip()
        if not value:
            print(f"  {key:<26} MISSING")
            continue
        if (template.get(key) or "").strip() == value:
            print(f"  {key:<26} placeholder (identical to .env.example — fill in a real value)")
        else:
            print(f"  {key:<26} SET  {fingerprint(value)}")

    print("\nExternal credential files:")
    cdsapirc = Path(os.path.expanduser("~/.cdsapirc"))
    if cdsapirc.exists():
        # Parse only the host; the token line is deliberately not read.
        host = "unknown"
        for line in cdsapirc.read_text(encoding="utf-8").splitlines():
            if line.strip().lower().startswith("url:"):
                host = line.split(":", 1)[1].strip()
        has_uid = any(l.strip().lower().startswith("uid:") for l in cdsapirc.read_text(encoding="utf-8").splitlines())
        print(f"  ~/.cdsapirc            present, url={host}"
              + ("  [WARNING: contains a legacy 'uid:' field, remove it]" if has_uid else ""))
    else:
        print("  ~/.cdsapirc            MISSING (needed for ERA5 and CAMS)")

    print("\nPython packages required by the next phases:")
    for module, extra in [("cdsapi", "pip install 'cdsapi>=0.7.7'"), ("xarray", "pip install xarray"),
                          ("pyarrow", "pip install pyarrow"), ("geopandas", "pip install geopandas"),
                          ("cfgrib", "pip install cfgrib (needs ecCodes)")]:
        try:
            __import__(module)
            print(f"  {module:<12} installed")
        except ImportError:
            print(f"  {module:<12} NOT installed  -> {extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
