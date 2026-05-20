"""Update data/bridges.json — Sagamore + Bourne live traffic.

Source: Google Maps Distance Matrix API (paid, ~$5/mo at hourly cadence).
Requires GOOGLE_MAPS_KEY env var.

Computes current delay vs. free-flow as:
    delay_min = (duration_in_traffic - duration) / 60

Runs hourly 6 AM–11 PM ET via update-bridges.yml.
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import env, read_existing, safe_write

OUT = Path(__file__).parent.parent / "data" / "bridges.json"

# Approach point (Cape side) → destination point (mainland side)
BRIDGES = {
    "sagamore": {
        "name": "Sagamore Bridge",
        "origin": "41.7681,-70.5042",
        "destination": "41.7984,-70.5390",
        "free_flow_mph": 55,
    },
    "bourne": {
        "name": "Bourne Bridge",
        "origin": "41.7430,-70.5970",
        "destination": "41.7600,-70.6100",
        "free_flow_mph": 55,
    },
}


def fetch_one(b: dict, key: str) -> dict:
    r = requests.get(
        "https://maps.googleapis.com/maps/api/distancematrix/json",
        params={
            "origins": b["origin"],
            "destinations": b["destination"],
            "departure_time": "now",
            "traffic_model": "best_guess",
            "key": key,
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    el = data["rows"][0]["elements"][0]
    if el.get("status") != "OK":
        raise RuntimeError(f"Distance Matrix returned {el.get('status')}: {data}")
    duration = el["duration"]["value"]  # seconds, free-flow estimate
    duration_in_traffic = el.get("duration_in_traffic", el["duration"])["value"]
    delay_sec = max(0, duration_in_traffic - duration)
    delay_min = round(delay_sec / 60)

    if delay_min < 5: status = "light"
    elif delay_min < 20: status = "moderate"
    else: status = "heavy"

    distance_m = el["distance"]["value"]
    live_speed_mph = round((distance_m / 1609.34) / (duration_in_traffic / 3600)) if duration_in_traffic else b["free_flow_mph"]

    return {
        "name": b["name"],
        "current_delay_min": delay_min,
        "current_status": status,
        "direction": "off_cape",
        "advice": _advice(delay_min),
        "live_speed_mph": live_speed_mph,
        "free_flow_mph": b["free_flow_mph"],
        "last_check": "just now",
    }


def _advice(delay_min: int) -> str:
    if delay_min < 5: return "Sail through — no delays right now"
    if delay_min < 15: return "Light backup — go now or wait 1 hour"
    if delay_min < 30: return "Moderate backup — consider waiting until after 7 PM"
    return "Heavy traffic — wait if you can, leave very early/late"


def main() -> None:
    key = env("GOOGLE_MAPS_KEY")
    current = {slug: fetch_one(b, key) for slug, b in BRIDGES.items()}

    # Preserve existing forecasts (those are weekly-updated, not hourly)
    existing = read_existing(OUT) or {}
    payload = {
        "current": current,
        "forecast_24h": existing.get("forecast_24h", []),
        "forecast_7day": existing.get("forecast_7day", []),
        "best_times_to_leave": existing.get("best_times_to_leave", {
            "off_cape_sunday": "Before 8 AM or after 7 PM",
            "on_cape_friday": "Before 11 AM or after 9 PM",
        }),
    }
    safe_write(OUT, payload, count_key=None, min_ratio=0.5)


if __name__ == "__main__":
    main()
