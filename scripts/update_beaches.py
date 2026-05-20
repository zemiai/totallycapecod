"""Update data/beaches.json — refresh water temp + 'updated' freshness.

This script is intentionally minimal. The seed data in data/beaches.json has
the canonical list of 28 beaches with lat/lng/amenities. Each cron run:
  - refreshes water_temp from NOAA (one reading covers the whole Cape)
  - bumps each beach's 'updated' string so the app shows recent timestamps

To make this truly live (crowd-sourced parking/crowd), wire a webhook endpoint
that ingests reportBeach() POSTs from the app and merges them here. See
HERMES.md §"User submissions back to Hermes".

Runs every 20 min during summer via update-beaches.yml.
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import read_existing, safe_write

OUT = Path(__file__).parent.parent / "data" / "beaches.json"
NOAA_STATION = "8447435"  # Chatham


def fetch_water_temp() -> int | None:
    try:
        r = requests.get(
            "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
            params={
                "date": "latest",
                "station": NOAA_STATION,
                "product": "water_temperature",
                "units": "english",
                "time_zone": "lst",
                "format": "json",
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if data:
            return round(float(data[0]["v"]))
    except Exception as e:
        print(f"[hermes] water_temp lookup failed: {e}", file=sys.stderr)
    return None


def main() -> None:
    existing = read_existing(OUT)
    if not existing or "beaches" not in existing:
        print("[hermes] data/beaches.json missing or invalid — cannot bootstrap from cron", file=sys.stderr)
        sys.exit(1)

    water_temp = fetch_water_temp()

    for b in existing["beaches"]:
        if water_temp is not None:
            b["water_temp"] = water_temp
        # NOTE: status/spots_text/crowd are NOT modified here.
        # They're updated only when real user reports arrive via webhook.
        b["updated"] = "just now"

    safe_write(OUT, existing, count_key="beaches", min_ratio=0.5)


if __name__ == "__main__":
    main()
