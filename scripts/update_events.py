"""Update data/events.json — REAL Cape Cod events scraped from public sources.

Deterministic, no API key required. Aggregates a rolling ~3-week window of
dated events from three kinds of source, each handled by one parser:

  1. ChamberMaster / GrowthZone chambers (9 town chambers, Cape-wide)
     -> stable DOM: .gz-events-card / .gz-card-date / .gz-events-card-title
  2. "The Events Calendar" (Tribe) REST API  -> clean JSON, e.g. Payomet
  3. schema.org Event JSON-LD on a calendar page -> e.g. Heritage Museums

Each event is normalised to the app's event-card shape, geocoded to its town,
de-duplicated, filtered to the upcoming window, and written to data/events.json.

No Facebook/Instagram (blocked + ToS). Social-only venues are intentionally
omitted. Add sources to SOURCES below — every new venue widens the net.

Run:  python scripts/update_events.py
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import now_iso, safe_write

OUT = Path(__file__).parent.parent / "data" / "events.json"

WINDOW_DAYS = 21          # how far ahead to look
PER_SOURCE_CAP = 25       # don't let one source flood the feed
TOTAL_CAP = 200
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124 Safari/537.36"}
TIMEOUT = 25

# ---- Cape Cod town / village coordinates (for geolocating cards) -------------
TOWN_COORDS = {
    "Provincetown": (42.0587, -70.1787), "Truro": (41.9979, -70.0492),
    "North Truro": (42.0392, -70.0900), "Wellfleet": (41.9362, -70.0331),
    "Eastham": (41.8300, -69.9740), "Orleans": (41.7901, -69.9873),
    "Brewster": (41.7601, -70.0819), "Harwich": (41.6863, -70.0780),
    "Harwich Port": (41.6709, -70.0772), "West Harwich": (41.6770, -70.1050),
    "Chatham": (41.6815, -69.9597), "Dennis": (41.7353, -70.1936),
    "East Dennis": (41.7486, -70.1597), "Dennisport": (41.6553, -70.1331),
    "West Dennis": (41.6620, -70.1700), "South Dennis": (41.6900, -70.1500),
    "Yarmouth": (41.7038, -70.2286), "Yarmouth Port": (41.7038, -70.2419),
    "South Yarmouth": (41.6680, -70.1770), "West Yarmouth": (41.6510, -70.2400),
    "Hyannis": (41.6520, -70.2828), "Barnstable": (41.7003, -70.2995),
    "West Barnstable": (41.7000, -70.3700), "Centerville": (41.6481, -70.3447),
    "Osterville": (41.6281, -70.3858), "Cotuit": (41.6151, -70.4361),
    "Marstons Mills": (41.6590, -70.4150), "Mashpee": (41.6481, -70.4822),
    "Sandwich": (41.7590, -70.4940), "East Sandwich": (41.7400, -70.4500),
    "Falmouth": (41.5515, -70.6148), "Woods Hole": (41.5246, -70.6731),
    "East Falmouth": (41.5760, -70.5530), "Bourne": (41.7412, -70.5990),
    "Buzzards Bay": (41.7456, -70.6181), "Cataumet": (41.6700, -70.6200),
}
DEFAULT_COORD = (41.668, -70.250)  # Mid-Cape

# ---- Sources ----------------------------------------------------------------
# kind: "chambermaster" (base list URL), "tribe" (wp-json api URL), "jsonld" (page URL)
CHAMBERS = [
    ("Provincetown", "https://ptownchamber.com/calendar-of-events/", "custom_ptown"),
    ("Eastham",   "https://members.easthamchamber.com/events",        "chambermaster"),
    ("Orleans",   "https://members.orleanscapecod.org/events",        "chambermaster"),
    ("Brewster",  "https://members.brewster-capecod.com/events",      "chambermaster"),
    ("Chatham",   "https://business.chathaminfo.com/events",          "chambermaster"),
    ("Harwich",   "https://business.harwichcc.com/events",            "chambermaster"),
    ("Dennis",    "https://business.dennischamber.com/calendar",       "chambermaster"),
    ("Yarmouth",  "https://business.yarmouthcapecod.com/events",      "chambermaster"),
    ("Hyannis",   "https://business.hyannis.com/events",              "chambermaster"),
    ("Mashpee",   "https://business.mashpeechamber.com/events",       "chambermaster"),
    ("Bourne",    "https://www.capecodcanalchamber.org/all-events/",  "custom_canal"),
]
VENUES = [
    # (display name, town, kind, url, venue_coord_override or None)
    ("Payomet",            "Truro",     "tribe",  "https://payomet.org/wp-json/tribe/events/v1/events", (42.0392, -70.0731)),
    ("Cape Cod Beer",      "Hyannis",   "tribe",  "https://capecodbeer.com/wp-json/tribe/events/v1/events", (41.6650, -70.2860)),
    ("Highfield Hall",     "Falmouth",  "tribe",  "https://highfieldhallandgardens.org/wp-json/tribe/events/v1/events", (41.5560, -70.6230)),
    ("Heritage Museums",   "Sandwich",  "jsonld", "https://heritagemuseumsandgardens.org/events-calendar/all-events/", (41.7560, -70.4980)),
    # aggregators + nightlife with clean structured feeds
    ("Provincetown Events","Provincetown","jsonld","https://ptownie.com/provincetown-calendar/", (42.0587, -70.1787)),
    ("Pier 37 Boathouse",  "Falmouth",  "jsonld", "https://www.falmouthpier37.com/events/category/live-music/", (41.5510, -70.6140)),
    ("Sundancers",         "West Dennis","ics",   "https://sundancerscapecod.com/entertainment/", (41.6620, -70.1700)),
]

# ---- Category / tag inference -----------------------------------------------
CATEGORY_TAGS = [
    ("music",   "🎵 LIVE MUSIC",  ["concert", "live music", "band", "jazz", "acoustic", "dj", "symphony", "blues", "rock", "folk", "open mic", "songwriter", "orchestra"]),
    ("comedy",  "😂 COMEDY",       ["comedy", "comedian", "stand-up", "standup", "improv"]),
    ("theater", "🎭 THEATER",      ["theater", "theatre", "play", "musical", "stage", "drama", "cabaret", "opera"]),
    ("film",    "🎬 FILM",         ["film", "movie", "cinema", "screening", "drive-in"]),
    ("market",  "🥕 MARKET",       ["farmers market", "farmers' market", "market", "craft fair"]),
    ("art",     "🎨 ART",          ["gallery", "exhibit", "art ", "artist", "painting", "sculpture", "opening reception"]),
    ("family",  "👨‍👩‍👧 FAMILY",       ["story time", "children", "kids", "family", "puppet", "petting"]),
    ("food",    "🍴 FOOD & DRINK", ["tasting", "wine", "beer", "oyster", "dinner", "brunch", "food", "clambake", "happy hour", "brewery"]),
    ("festival","🎪 FESTIVAL",     ["festival", "parade", "fair", "celebration", "fireworks", "carnival"]),
    ("talk",    "🎙️ TALK",         ["lecture", "talk", "author", "reading", "presentation", "workshop", "history"]),
]

def categorize(text: str) -> tuple[str, str]:
    t = (text or "").lower()
    for cat, tag, kws in CATEGORY_TAGS:
        if any(k in t for k in kws):
            return cat, tag
    return "event", "📅 EVENT"


# ---- Date parsing -----------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

def cm_build_date(mon_name: str, day: int, year=None):
    mon = MONTHS.get((mon_name or "")[:3].lower())
    if not mon:
        return None
    now = datetime.now(timezone.utc)
    if year is None:                       # infer: roll to next year if already well past
        year = now.year
        try:
            cand = datetime(year, mon, day, tzinfo=timezone.utc)
        except ValueError:
            return None
        if cand < now - timedelta(days=2):
            year += 1
    try:
        return datetime(year, mon, day, tzinfo=timezone.utc)
    except ValueError:
        return None

_CM_DATE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?", re.I)

def parse_chambermaster_date(s: str):
    """Parse 'Saturday Jun 6, 2026' OR 'FRI June 5' (year inferred)."""
    m = _CM_DATE.search(s or "")
    if not m:
        return None
    return cm_build_date(m.group(1), int(m.group(2)), int(m.group(3)) if m.group(3) else None)

def parse_iso(s: str):
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    for fmt in (None,):
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", s)
    if m:
        return datetime(*[int(x) for x in m.groups()], tzinfo=timezone.utc)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    return None

def fmt_when(dt: datetime, has_time: bool) -> str:
    day = dt.strftime("%a %b ") + str(dt.day)
    if has_time:
        t = dt.strftime("%I:%M %p").lstrip("0")
        return f"{day} · {t}"
    return day


# ---- Parsers ----------------------------------------------------------------
def fetch(url: str):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r

def _cm_event(title, dt, town, url):
    return {"title": html.unescape(title), "start": dt, "has_time": False,
            "town": town, "venue": "", "price": "", "url": url, "img": None}

JUNK_TITLES = {"read more", "details", "more info", "view details", "buy tickets", "register"}

def parse_chambermaster(town: str, base: str) -> list[dict]:
    """Handles all three GrowthZone/ChamberMaster layouts seen on the Cape:
       A) .gz-events-card list   B) .gz-cards calendar grid   C) detail-link fallback."""
    out, seen = [], set()

    def add(title, dt, url):
        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 4 or title.lower() in JUNK_TITLES or not dt:
            return
        key = (title.lower(), dt.date())
        if key in seen:
            return
        seen.add(key)
        out.append(_cm_event(title, dt, town, url))

    for url in (base, base.rstrip("/") + "/calendar", base.rstrip("/") + "/events"):
        try:
            soup = BeautifulSoup(fetch(url).text, "html.parser")
        except Exception:
            continue

        # Layout A — list view: .gz-events-card with .gz-card-date
        for c in soup.select(".gz-events-card"):
            t = c.select_one(".gz-events-card-title, .gz-card-title")
            d = c.select_one(".gz-card-date")
            link = c.select_one('a[href*="etails/"]')
            if t and d:
                add(t.get_text(" ", strip=True), parse_chambermaster_date(d.get_text(" ", strip=True)),
                    link.get("href") if link else url)

        # Layout B — calendar grid: .gz-cards with .gz-card-month/.gz-card-dday
        if not out:
            yr = None
            hdr = soup.select_one(".gz-calendar-month-text")
            if hdr:
                ym = re.search(r"(\d{4})", hdr.get_text())
                yr = int(ym.group(1)) if ym else None
            for c in soup.select(".gz-cards .card, .gz-cards .gz-card"):
                t = c.select_one(".gz-card-title")
                mo = c.select_one(".gz-card-month")
                dd = c.select_one(".gz-card-dday")
                if not (t and mo and dd):
                    continue
                try:
                    day = int(re.sub(r"\D", "", dd.get_text()))
                except ValueError:
                    continue
                dt = cm_build_date(mo.get_text(strip=True), day, yr)
                link = c.select_one("a[href]")
                add(t.get_text(" ", strip=True), dt, link.get("href") if link else url)

        # Layout D — legacy "mn-" ChamberMaster theme (date lives inside each .mn-listing)
        if not out:
            for item in soup.select(".mn-listing"):
                t = item.select_one(".mn-title")
                if not t:
                    continue
                dt = parse_chambermaster_date(item.get_text(" ", strip=True))
                link = item.select_one('a[href*="etails/"]') or item.select_one("a[href]")
                add(t.get_text(" ", strip=True), dt, link.get("href") if link else url)

        # Layout C — last-ditch fallback: detail links + nearest date (year optional)
        if not out:
            for a in soup.select('a[href*="etails/"]'):
                title = a.get_text(" ", strip=True)
                if not title or len(title) < 4 or title.lower() in JUNK_TITLES:
                    continue
                anc, dt = a, None
                for _ in range(5):
                    if anc.parent:
                        anc = anc.parent
                    de = anc.select_one(".gz-card-date") if hasattr(anc, "select_one") else None
                    if de:
                        dt = parse_chambermaster_date(de.get_text(" ", strip=True))
                        if dt:
                            break
                if not dt:
                    dt = parse_chambermaster_date(re.sub(r"\s+", " ", anc.get_text(" ", strip=True)))
                add(title, dt, a.get("href"))

        if out:
            break
    return out

def parse_tribe(name: str, town: str, api: str, coord) -> list[dict]:
    start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end = (datetime.now(timezone.utc) + timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    url = f"{api}?start_date={start}&end_date={end} 23:59:59&per_page=50"
    out = []
    try:
        data = fetch(url).json()
    except Exception:
        return out
    for e in data.get("events", []):
        dt = parse_iso(e.get("start_date") or e.get("utc_start_date"))
        if not dt:
            continue
        venue = (e.get("venue") or {}).get("venue", "") if isinstance(e.get("venue"), dict) else ""
        cost = html.unescape((e.get("cost") or "").strip())
        img = None
        if isinstance(e.get("image"), dict):
            img = e["image"].get("url")
        out.append({
            "title": html.unescape(e.get("title", "").strip()),
            "start": dt, "has_time": True, "town": town,
            "venue": html.unescape(venue) or name, "price": cost,
            "url": e.get("url", ""), "img": img,
        })
    return out

def parse_jsonld(name: str, town: str, page: str, coord) -> list[dict]:
    import json
    out = []
    try:
        soup = BeautifulSoup(fetch(page).text, "html.parser")
    except Exception:
        return out
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        flat = []
        for it in items:
            if isinstance(it, dict) and "@graph" in it:
                flat.extend(it["@graph"])
            else:
                flat.append(it)
        for it in flat:
            if not isinstance(it, dict) or it.get("@type") not in ("Event", "TheaterEvent", "MusicEvent", "Festival"):
                continue
            dt = parse_iso(it.get("startDate"))
            if not dt:
                continue
            loc = it.get("location") or {}
            venue = loc.get("name", "") if isinstance(loc, dict) else ""
            img = it.get("image")
            if isinstance(img, list):
                img = img[0] if img else None
            if isinstance(img, dict):
                img = img.get("url")
            out.append({
                "title": html.unescape(it.get("name", "").strip()),
                "start": dt, "has_time": "T" in str(it.get("startDate", "")),
                "town": town, "venue": html.unescape(venue) or name, "price": "",
                "url": it.get("url", ""), "img": img,
            })
    return out

def parse_ics(name: str, town: str, url: str, coord) -> list[dict]:
    """Parse an iCalendar feed (Squarespace ?format=ical / Tribe ?ical=1)."""
    text = ""
    for suf in ("?ical=1", "?format=ical", ""):
        try:
            r = fetch(url + suf)
            if "BEGIN:VCALENDAR" in r.text[:400]:
                text = r.text
                break
        except Exception:
            continue
    if "BEGIN:VEVENT" not in text:
        return []
    text = text.replace("\r\n ", "").replace("\n ", "")  # unfold wrapped lines
    out = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        sm = re.search(r"\nSUMMARY[^:]*:(.+)", block)
        dm = re.search(r"\nDTSTART[^:]*:(\d{8})(?:T(\d{6}))?", block)
        if not sm or not dm:
            continue
        d = dm.group(1)
        tm = dm.group(2)
        try:
            dt = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]),
                          int(tm[:2]) if tm else 0, int(tm[2:4]) if tm else 0, tzinfo=timezone.utc)
        except ValueError:
            continue
        title = sm.group(1).strip().replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
        out.append({"title": html.unescape(title), "start": dt, "has_time": bool(tm),
                    "town": town, "venue": name, "price": "", "url": url, "img": None})
    return out

def parse_custom_ptown(town: str, url: str, *_a) -> list[dict]:
    """Provincetown Chamber: events link to /events/<slug>; dates in nearby text."""
    out = []
    try:
        soup = BeautifulSoup(fetch(url).text, "html.parser")
    except Exception:
        return out
    for a in soup.select('a[href*="/events/"]'):
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4:
            continue
        block = a
        for _ in range(3):
            if block.parent:
                block = block.parent
        txt = re.sub(r"\s+", " ", block.get_text(" ", strip=True))
        m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})", txt)
        if not m:
            continue
        yr = datetime.now(timezone.utc).year
        try:
            dt = datetime(yr, MONTHS[m.group(1)[:3].lower()], int(m.group(2)), tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt < datetime.now(timezone.utc) - timedelta(days=1):
            dt = dt.replace(year=yr + 1)
        out.append({"title": html.unescape(title), "start": dt, "has_time": False,
                    "town": town, "venue": "", "price": "", "url": a.get("href"), "img": None})
    return out

def parse_custom_canal(town: str, url: str, *_a) -> list[dict]:
    return parse_custom_ptown(town, url)  # same custom-HTML shape


# ---- Normalise + assemble ---------------------------------------------------
def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]

_DATE_TAIL = re.compile(
    r"\s*(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat)[a-z]*,?\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s*\d{4})?.*$",
    re.I)

def clean_title(t: str) -> str:
    t = _DATE_TAIL.sub("", t).strip(" -|·")
    return re.sub(r"\s+", " ", t)

def main() -> None:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=WINDOW_DAYS)
    raw = []

    jobs = []
    for town, url, kind in CHAMBERS:
        jobs.append((kind, town, town, url, None))
    for name, town, kind, url, coord in VENUES:
        jobs.append((kind, name, town, url, coord))

    for kind, name, town, url, coord in jobs:
        try:
            if kind == "chambermaster":
                evs = parse_chambermaster(town, url)
            elif kind == "tribe":
                evs = parse_tribe(name, town, url, coord)
            elif kind == "jsonld":
                evs = parse_jsonld(name, town, url, coord)
            elif kind == "ics":
                evs = parse_ics(name, town, url, coord)
            elif kind == "custom_ptown":
                evs = parse_custom_ptown(town, url)
            elif kind == "custom_canal":
                evs = parse_custom_canal(town, url)
            else:
                evs = []
        except Exception as e:
            print(f"[hermes] {name} failed: {e}", file=sys.stderr)
            evs = []
        kept = 0
        for e in evs:
            dt = e["start"]
            if dt < now - timedelta(hours=12) or dt > horizon:
                continue
            town_name = e.get("town") or town
            lat, lng = TOWN_COORDS.get(town_name, coord or DEFAULT_COORD) if not coord else coord
            if e.get("town") and e["town"] in TOWN_COORDS:
                lat, lng = TOWN_COORDS[e["town"]]
            title = clean_title(e["title"])
            if not title or len(title) < 3:
                continue
            has_time = e.get("has_time", False) and not (dt.hour == 0 and dt.minute == 0)
            cat, tag = categorize(f'{title} {e.get("venue","")}')
            raw.append({
                "id": slugify(f'{title}-{dt.strftime("%Y%m%d")}'),
                "tag": tag, "category": cat,
                "time": fmt_when(dt, has_time),
                "title": title,
                "venue": (e.get("venue") or "") if (e.get("venue") or "") != town_name else "",
                "town": town_name,
                "info": "", "price": e.get("price", "") or "",
                "lat": round(lat, 4), "lng": round(lng, 4),
                "img": e.get("img"),
                "source": name, "source_url": e.get("url", ""),
                "start": dt.isoformat(),
            })
            kept += 1
            if kept >= PER_SOURCE_CAP:
                break
        print(f"[hermes] {name:16} -> {kept} events in window")

    # de-dupe by id, sort by start, cap
    seen, events = set(), []
    for e in sorted(raw, key=lambda x: x["start"]):
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        events.append(e)
    events = events[:TOTAL_CAP]

    payload = {
        "version": "1.0", "updated_at": now_iso(),
        "window_days": WINDOW_DAYS, "count": len(events),
        "_hermes_note": "Real Cape Cod events scraped from chambers + venues. update_events.py",
        "events": events,
    }
    safe_write(OUT, payload, count_key="events", min_ratio=0.4)
    print(f"[hermes] wrote {len(events)} events to {OUT.name}")


if __name__ == "__main__":
    main()
