"""Update data/beaches.json — real water temperature from stations that actually report it.

The previous version polled NOAA Chatham (8447435), a tide station with NO water-temp
sensor, so the fetch always failed and the seed temps were shown as "live." This version
pulls from sources that genuinely report water temperature and assigns each beach the
reading from its NEAREST working source (bay side vs ocean side vs Sound differ by 5-10°F):

  - NOAA CO-OPS Woods Hole (8447930)  — Buzzards Bay / Woods Hole / Sound (Upper Cape)
  - NDBC buoy 44090 (Cape Cod Bay)    — bay side (Mid/Outer north)
  - NDBC buoy 44020 (Nantucket Sound) — south-facing Sound beaches

Each beach gets water_temp + water_temp_at (ISO, only when a real reading was fetched) so
the app can honestly show "live" vs an estimate. Crowd/parking are NOT touched here — those
come from real user reports via the beach-report function (crowdsourced, Waze-style).

Runs every 20 min during summer via update-beaches.yml. Keyless.
"""
from __future__ import annotations

import sys
from math import radians, sin, cos, asin, sqrt
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import read_existing, safe_write, now_iso

OUT = Path(__file__).parent.parent / "data" / "beaches.json"
HEADERS = {"User-Agent": "totallycapecod/1.0 (beach water-temp updater)"}

# Water-temp sources with their real locations. Each beach uses the nearest one that responds.
SOURCES = [
    {"name": "Woods Hole",          "kind": "coops", "id": "8447930", "lat": 41.5236, "lng": -70.6711},
    {"name": "Cape Cod Bay buoy",   "kind": "ndbc",  "id": "44090",   "lat": 41.840,  "lng": -70.329},
    {"name": "Nantucket Sound buoy","kind": "ndbc",  "id": "44020",   "lat": 41.493,  "lng": -70.279},
]


def fetch_coops(station: str):
    try:
        r = requests.get(
            "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
            params={"date": "latest", "station": station, "product": "water_temperature",
                    "units": "english", "time_zone": "lst", "format": "json"},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if data:
            return round(float(data[0]["v"]))
    except Exception as e:
        print(f"[hermes] coops {station} water_temp failed: {e}", file=sys.stderr)
    return None


def fetch_ndbc(buoy: str):
    """Parse NDBC realtime2 text; WTMP is in °C, newest row first."""
    try:
        r = requests.get(f"https://www.ndbc.noaa.gov/data/realtime2/{buoy}.txt",
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        lines = [l for l in r.text.splitlines() if l.strip()]
        if len(lines) < 3:
            return None
        header = lines[0].lstrip("#").split()
        if "WTMP" not in header:
            return None
        wi = header.index("WTMP")
        for row in lines[2:]:  # skip header + units rows
            cols = row.split()
            if len(cols) > wi:
                v = cols[wi]
                if v not in ("MM", "999.0", "99.0", "999"):
                    return round(float(v) * 9 / 5 + 32)
    except Exception as e:
        print(f"[hermes] ndbc {buoy} water_temp failed: {e}", file=sys.stderr)
    return None


def miles(lat1, lng1, lat2, lng2):
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 3959 * 2 * asin(sqrt(a))


def main() -> None:
    existing = read_existing(OUT)
    if not existing or "beaches" not in existing:
        print("[hermes] data/beaches.json missing or invalid — cannot bootstrap from cron", file=sys.stderr)
        sys.exit(1)

    readings = []
    for s in SOURCES:
        t = fetch_coops(s["id"]) if s["kind"] == "coops" else fetch_ndbc(s["id"])
        if t is not None and 32 <= t <= 90:  # sanity bound
            readings.append({**s, "tempF": t})
            print(f"[hermes] {s['name']}: {t}°F")

    now = now_iso()
    updated = 0
    for b in existing["beaches"]:
        if not readings or b.get("lat") is None:
            continue
        best = min(readings, key=lambda r: miles(b["lat"], b["lng"], r["lat"], r["lng"]))
        b["water_temp"] = best["tempF"]
        b["water_temp_at"] = now
        b["water_temp_src"] = best["name"]
        updated += 1
        # NOTE: status / spots_text / crowd are intentionally NOT set here — they come from
        # real user reports (crowdsourced via netlify/functions/beach-report.js). We no longer
        # fake an "updated: just now" on parking/crowd.

    if not readings:
        print("[hermes] no water-temp source responded — leaving existing values (not faking 'live')", file=sys.stderr)

    safe_write(OUT, existing, count_key="beaches", min_ratio=0.5)
    print(f"[hermes] done — {len(readings)} water-temp sources, {updated}/{len(existing['beaches'])} beaches updated")


if __name__ == "__main__":
    main()
