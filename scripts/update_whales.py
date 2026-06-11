"""Update data/whales.json — auto-feed recent whale + white-shark sightings off Cape Cod.

Source: the iNaturalist API (https://api.inaturalist.org/v1) — free, no API key,
stable, well-documented. We query recent, geolocated observations of the target
species inside a Cape Cod bounding box and map them into the app's sighting schema.

Why iNaturalist: the gold-standard Cape shark source (AWSC "Sharktivity") has no
public API; OBIS/GBIF lag and carry no photos. iNaturalist is the best sanctioned,
queryable, free option that covers BOTH whales and great whites with coordinates,
dates, and photos.

Each run:
  1. Pull observations for each target species in the last MAX_AGE_DAYS days.
  2. Map to {species, lat, lng, location, reported_by, reported_at, photo_url, ...}.
  3. Merge with any real user submissions already in the file, dedupe, prune by age.

No secret required. Runs every 30 min May–Oct via update-whales.yml (cheap; keyless).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import read_existing, safe_write, now_iso

OUT = Path(__file__).parent.parent / "data" / "whales.json"
MAX_AGE_DAYS = 14
MAX_SIGHTINGS = 30

API = "https://api.inaturalist.org/v1"
HEADERS = {"User-Agent": "totallycapecod/1.0 (whale + shark sightings updater)"}

# Cape Cod waters bounding box: Cape Cod Bay, Stellwagen Bank, the Outer Cape,
# Monomoy, and Nantucket Sound, plus a margin offshore where sharks/whales feed.
BBOX = {"nelat": 42.42, "nelng": -69.55, "swlat": 41.30, "swlng": -70.95}

# scientific name -> app schema species label (drives the card emoji:
# seal->🦦, dolphin->🐬, shark->🦈, anything else->🐋)
TARGETS = [
    ("Carcharodon carcharias", "shark"),
    ("Megaptera novaeangliae", "humpback"),
    ("Balaenoptera physalus", "fin"),
    ("Balaenoptera acutorostrata", "minke"),
    ("Eubalaena glacialis", "right whale"),
    ("Halichoerus grypus", "seal"),
    ("Phoca vitulina", "seal"),
    ("Delphinus delphis", "dolphin"),
    ("Lagenorhynchus acutus", "dolphin"),
]


def resolve_taxon_id(name: str) -> int | None:
    try:
        r = requests.get(f"{API}/taxa", params={"q": name, "rank": "species", "per_page": 1},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        results = r.json().get("results", [])
        return results[0]["id"] if results else None
    except Exception as e:
        print(f"[hermes] taxon lookup failed for {name}: {e}", file=sys.stderr)
        return None


def time_ago(dt: datetime, now: datetime) -> str:
    mins = int((now - dt).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 1)} min ago"
    if mins < 1440:
        return f"{mins // 60} h ago"
    days = mins // 1440
    return f"{days} day{'s' if days != 1 else ''} ago"


def fetch_species(name: str, species: str, since: str, now: datetime) -> list[dict]:
    taxon_id = resolve_taxon_id(name)
    if not taxon_id:
        return []
    params = {
        "taxon_id": taxon_id, "d1": since,
        "order_by": "observed_on", "order": "desc",
        "per_page": 15, "geo": "true", **BBOX,
    }
    try:
        r = requests.get(f"{API}/observations", params=params, headers=HEADERS, timeout=25)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as e:
        print(f"[hermes] observations failed for {name}: {e}", file=sys.stderr)
        return []

    out = []
    for o in results:
        geo = o.get("geojson") or {}
        coords = geo.get("coordinates")
        if not coords or len(coords) != 2:
            continue
        lng, lat = float(coords[0]), float(coords[1])
        if not (BBOX["swlat"] <= lat <= BBOX["nelat"] and BBOX["swlng"] <= lng <= BBOX["nelng"]):
            continue
        iso = o.get("time_observed_at") or o.get("observed_on")
        if not iso:
            continue
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        taxon = o.get("taxon") or {}
        common = taxon.get("preferred_common_name") or name
        photos = o.get("photos") or []
        photo_url = ""
        if photos and photos[0].get("url"):
            # iNat returns a 'square' thumb; request a larger 'medium' variant
            photo_url = photos[0]["url"].replace("square", "medium")
        user = (o.get("user") or {}).get("login") or "observer"
        out.append({
            "id": f"inat-{o['id']}",
            "species": species,
            "count": 1,
            "lat": round(lat, 4),
            "lng": round(lng, 4),
            "location": o.get("place_guess") or "Off Cape Cod",
            "reported_by": f"iNaturalist · {user}",
            "reported_at": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time_ago": time_ago(dt.astimezone(timezone.utc), now),
            "photo_url": photo_url,
            "notes": common,
            "source_url": f"https://www.inaturalist.org/observations/{o['id']}",
        })
    return out


def main() -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    since = cutoff.strftime("%Y-%m-%d")

    existing = read_existing(OUT) or {"version": "1.0", "recent_sightings": []}

    # Keep real user/operator submissions (not the iNat-sourced ones we re-fetch),
    # within the age window. Drops stale iNat entries and any manual seed data.
    kept = []
    for s in existing.get("recent_sightings", []):
        sid = str(s.get("id", ""))
        if sid.startswith("inat-"):
            continue  # re-fetched fresh below
        ts = s.get("reported_at", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt < cutoff:
                continue
        except Exception:
            pass
        # only retain genuine submissions, not placeholder/seed rows
        if sid.startswith("user-") or s.get("source") == "user_submission":
            kept.append(s)

    fetched = []
    for name, species in TARGETS:
        fetched.extend(fetch_species(name, species, since, now))

    # Dedupe by id, prefer fetched
    by_id = {s["id"]: s for s in kept}
    for s in fetched:
        by_id[s["id"]] = s

    sightings = list(by_id.values())
    sightings.sort(key=lambda s: s.get("reported_at", ""), reverse=True)
    sightings = sightings[:MAX_SIGHTINGS]

    existing["version"] = existing.get("version", "1.0")
    existing["recent_sightings"] = sightings
    existing["updated_at"] = now_iso()
    existing["_hermes_note"] = (
        "Auto-fed from the iNaturalist API: recent whale + white-shark sightings in a "
        "Cape Cod bounding box (Cape Cod Bay, Stellwagen, Outer Cape, Monomoy, Nantucket "
        f"Sound), last {MAX_AGE_DAYS} days. User/operator submissions are preserved and "
        "merged. No API key required."
    )

    print(f"[hermes] whales: {len(fetched)} fetched from iNaturalist, "
          f"{len(kept)} submissions kept, {len(sightings)} total after dedupe/cap")

    # Pruning/refresh may shrink the file (e.g. quiet week) — allow it.
    safe_write(OUT, existing, count_key=None, min_ratio=0)


if __name__ == "__main__":
    main()
