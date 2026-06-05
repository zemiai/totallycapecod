"""Enrich data/eats.json with live Google Places data (Places API New).

For each restaurant in data/eats.json this fills:
  - rating       (real Google star rating, replaces the editorial estimate)
  - reviews      (user_ratings_total)
  - website      (official site)
  - open_now     (True/False right now, or None if no hours published)
  - price        ($..$$$$ from Google price level, when available)
  - photo        (downloads the top photo to data/eats-photos/<id>.jpg)
  - place_id     (cached on first run so we never re-resolve)

Cost control:
  - place_id is resolved with a Text Search ONLY when it's missing (first run).
    After that every run is just a Place Details + Photo fetch per restaurant.
  - ~83 restaurants once a week is trivially inside Google's free monthly tier.
  - Run this on a schedule (weekly is plenty); it is NOT called per visitor.

Setup:
  - Enable "Places API (New)" in Google Cloud and create an API key.
  - Provide it as an env var:  GOOGLE_PLACES_API_KEY
  - Run:  GOOGLE_PLACES_API_KEY=xxxx python scripts/update_eats.py

The key is read from the environment only and is NEVER written to eats.json or
committed — the public site only ever sees ratings/photos, never the key.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import env, now_iso, read_existing, safe_write

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "eats.json"
PHOTO_DIR = ROOT / "data" / "eats-photos"

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{pid}"
PHOTO_MAX_WIDTH = 900
REQUEST_PAUSE = 0.15  # seconds between API calls, be polite

PRICE_MAP = {
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


def resolve_place_id(api_key: str, r: dict) -> str | None:
    """Find the Google place_id for a restaurant via Text Search, biased to its
    known lat/lng so we don't match a same-named spot in another town."""
    body = {
        "textQuery": f'{r["name"]} {r["town"]} Cape Cod MA',
        "maxResultCount": 1,
        "locationBias": {
            "circle": {
                "center": {"latitude": r["lat"], "longitude": r["lng"]},
                "radius": 4000.0,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName",
    }
    try:
        resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=20)
        resp.raise_for_status()
        places = resp.json().get("places", [])
        if places:
            return places[0]["id"]
    except Exception as e:
        print(f"[hermes] search failed for {r['name']}: {e}", file=sys.stderr)
    return None


def fetch_details(api_key: str, place_id: str) -> dict | None:
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "id,rating,userRatingCount,websiteUri,priceLevel,"
            "currentOpeningHours.openNow,photos"
        ),
    }
    try:
        resp = requests.get(DETAILS_URL.format(pid=place_id), headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[hermes] details failed for {place_id}: {e}", file=sys.stderr)
    return None


def download_photo(api_key: str, photo_name: str, dest: Path) -> bool:
    """Download a Places photo by its resource name to <dest>. Returns True on success."""
    url = f"https://places.googleapis.com/v1/{photo_name}/media"
    params = {"maxWidthPx": PHOTO_MAX_WIDTH, "key": api_key}
    try:
        resp = requests.get(url, params=params, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"[hermes] photo failed for {dest.name}: {e}", file=sys.stderr)
    return False


def main() -> None:
    api_key = env("GOOGLE_PLACES_API_KEY")  # exits(2) if missing

    data = read_existing(OUT)
    if not data or "eats" not in data:
        print("[hermes] data/eats.json missing or invalid — run scripts/_gen_eats_seed.py first", file=sys.stderr)
        sys.exit(1)

    enriched_count = 0
    for r in data["eats"]:
        # 1) Resolve place_id once, then cache it forever.
        if not r.get("place_id"):
            r["place_id"] = resolve_place_id(api_key, r)
            time.sleep(REQUEST_PAUSE)
        if not r.get("place_id"):
            continue  # couldn't match — keep editorial data as-is

        # 2) Live details.
        d = fetch_details(api_key, r["place_id"])
        time.sleep(REQUEST_PAUSE)
        if not d:
            continue

        if d.get("rating") is not None:
            r["rating"] = round(float(d["rating"]), 1)
            r["rating_source"] = "google"
        if d.get("userRatingCount") is not None:
            r["reviews"] = int(d["userRatingCount"])
        if d.get("websiteUri"):
            r["website"] = d["websiteUri"]
        if d.get("priceLevel") in PRICE_MAP:
            r["price"] = PRICE_MAP[d["priceLevel"]]
        co = d.get("currentOpeningHours") or {}
        r["open_now"] = co.get("openNow")  # True / False / None

        # 3) Top photo -> local file (no API key ever lands in eats.json).
        photos = d.get("photos") or []
        if photos:
            dest = PHOTO_DIR / f'{r["id"]}.jpg'
            if download_photo(api_key, photos[0]["name"], dest):
                r["photo"] = f'data/eats-photos/{r["id"]}.jpg'
            time.sleep(REQUEST_PAUSE)

        r["enriched_at"] = now_iso()
        enriched_count += 1
        print(f"[hermes] enriched {r['name']} ({r.get('rating')}★ / {r.get('reviews')} reviews)")

    data["enriched"] = enriched_count > 0
    safe_write(OUT, data, count_key="eats", min_ratio=0.5)
    print(f"[hermes] done — enriched {enriched_count}/{len(data['eats'])} restaurants")


if __name__ == "__main__":
    main()
