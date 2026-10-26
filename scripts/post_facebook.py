"""Auto-post to the Totally Cape Cod Facebook Page + Instagram — variety engine.

Two slots a day, each with a real Cape photo (not a text-card infographic):

  MORNING (7:30 AM ET) — a different format each weekday so the page never
  repeats itself:
    Mon  beach pick of the day     (live lot status → one great beach)
    Tue  tonight's picks           (3 evening events)
    Wed  question day              (rotating local either/or — engagement)
    Thu  hidden gem                (rotating locals-only spot)
    Fri  weekend roundup           (Sat+Sun events — the shareable one)
    Sat  spotlight                 (festival/family event today)
    Sun  sunset spot               (best spot + time tonight)
  Fireworks days override everything with the fireworks lineup.

  OFF-SEASON (data/season.json → mode offseason, or auto outside summer): beach-lot
  formats switch to off-season ones (Mon beach walk + water temp, Sat "what's open"
  community ask), the evening post drops the "room for a swim" line, and summer-only
  questions/hashtags rotate out. Flip season.json back to summer to restore.

  Honesty rule: lot status in data/beaches.json is a static TYPICAL pattern, not a live
  reading, so posts never claim a beach "has room right now" unless a beachgoer
  reported it in the last 3 hours (live reports from the beach-report function).

  EVENING (5 PM ET) — "Tonight on Cape": events with times + which beach lots
  still have room + sunset. Posted when people decide what to do.

Distribution rules learned the hard way:
  - NO link in the post body (Facebook demotes link posts) — the tracked link is
    auto-added as the FIRST COMMENT on Facebook, and as a comment on Instagram.
  - Hook first: the opening line is written to stop the scroll, and rotates.
  - 4-6 hashtags, varied per format — not the same 8 every day.

Idempotent per slot: data/.fb_state.json records the last posted date for each
slot. DRY_RUN=1 prints instead of posting; FORCE=1 reposts; MODE=morning|evening
overrides the time-based slot detection; TCC_FAKE_WEEKDAY=0..6 forces a format
(testing only).

Secrets: FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN, IG_USER_ID (see SETUP_FACEBOOK.md).
Run via .github/workflows/post-facebook.yml, or locally: DRY_RUN=1 python scripts/post_facebook.py
"""
from __future__ import annotations
import json, os, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.season import is_offseason, season_hashtag  # noqa: E402  (season switch: data/season.json)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
SOCIAL = ROOT / "img" / "social"
STATE = DATA / ".fb_state.json"
ET = ZoneInfo("America/New_York")
GRAPH = "https://graph.facebook.com/v21.0"
SITE = "https://totallycapecod.com"
RAW_BASE = "https://raw.githubusercontent.com/zemiai/totallycapecod/main"
FIREWORKS_IMG = f"{RAW_BASE}/img/fireworks.png"

PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
FORCE = os.environ.get("FORCE", "") == "1"

# ---------------------------------------------------------------- photo pool --
# Founder photos in img/social/ (see STOCK_CREDITS.md). Credited photos live in
# data/photos.json — see scenery_pool()/pick_photo() below.
PHOTO_TAGS = {
    # Founder-shot originals (Nauset Light Beach, Eastham — no license needed). House rule
    # (Oct 2026): real Cape Cod scenery only, no people — so the Pexels stock shots and the
    # dusk beach shot (beachgoers in frame) are retired from posts and reels.
    "nauset-light-red-beacon.jpg": {"sunset", "gem", "question"},
    "nauset-light-glow.jpg":       {"sunset", "gem", "events"},
    "nauset-light-bluff.jpg":      {"gem", "question"},
}

def now_et() -> datetime:
    return datetime.now(ET)

def photo_for(kind: str, salt: int = 0) -> str:
    pool = sorted(f for f, tags in PHOTO_TAGS.items()
                  if kind in tags and (SOCIAL / f).exists())
    if not pool:
        pool = sorted(f for f in PHOTO_TAGS if (SOCIAL / f).exists())
    if not pool:
        return f"{RAW_BASE}/img/social/default.png"
    doy = now_et().timetuple().tm_yday
    return f"{RAW_BASE}/img/social/{pool[(doy + salt) % len(pool)]}"

# ------------------------------------------------------------------- helpers --
def weekday_et() -> int:
    fake = os.environ.get("TCC_FAKE_WEEKDAY", "")
    if fake.isdigit():
        return int(fake) % 7
    return now_et().weekday()

def load(name: str):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return {}

def _norm_title(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split())

def dedupe_by_title(evs: list[dict]) -> list[dict]:
    """Drop repeats of the same event — the same show on two nights, or one event listed
    by two chambers ("Hymn Sing" vs "X hosts Hymn Sing"). Keeps the first occurrence."""
    out, seen = [], []
    for e in evs:
        n = _norm_title(e.get("title"))
        if not n or any(n == s or (min(len(n), len(s)) >= 12 and (n in s or s in n)) for s in seen):
            continue
        seen.append(n)
        out.append(e)
    return out

def events_on(date_iso: str) -> list[dict]:
    """All events (scraped + curated) starting on the given ET date."""
    out, seen = [], set()
    for fname in ("events.json", "curated.json"):
        for e in (load(fname) or {}).get("events") or []:
            if (e.get("start") or "")[:10] == date_iso and e.get("id") not in seen:
                seen.add(e.get("id"))
                out.append(e)
    out.sort(key=lambda e: (0 if e.get("pinned") else 1, e.get("start") or ""))
    return dedupe_by_title(out)

def evening_events(date_iso: str, n: int) -> list[dict]:
    evs = [e for e in events_on(date_iso) if "PM" in (e.get("time") or "") and plausible_time(e)]
    return evs[:n]

def clock_of(e: dict) -> str:
    """The displayed clock time, or '' if the event only has a date."""
    t = (e.get("time") or "").split("·")[-1].strip()
    return t if ("AM" in t or "PM" in t) else ""

def plausible_time(e: dict) -> bool:
    """Drop 12:00–5:59 AM 'times' — scraper artifacts, not real Cape events."""
    t = clock_of(e)
    if not t.endswith("AM"):
        return True
    try:
        hour = int(t.split(":")[0])
    except ValueError:
        return True
    return not (hour == 12 or hour < 6)

def ev_line(e: dict) -> str:
    t = clock_of(e)
    where = e.get("venue") or e.get("town") or ""
    s = "• " + (e.get("title", "").strip() or "…")
    if where:
        s += f" — {where}"
    if t:
        s += f" · {t}"
    return s

def rotate(seq, salt: int = 0):
    """Deterministic weekly rotation so copy varies without randomness."""
    wk = now_et().isocalendar()[1]
    return seq[(wk + salt) % len(seq)]

def hashtag(word: str) -> str:
    return "#" + "".join(c for c in word.title() if c.isalnum())

# ------------------------------------------------------------------ formats ---
# Each format returns (lines, image_url, campaign, tags). No links in lines —
# the tracked link goes in the first comment (see main()).
BASE_TAGS = ["#CapeCod", "#CapeCodLife", "#CapeCodMA", "#CapeCodSummer"]

def base_tags() -> list[str]:
    wk = now_et().isocalendar()[1]
    tags = BASE_TAGS[:3] + [season_hashtag()]          # #CapeCodSummer only in summer mode
    return [tags[wk % 4], tags[(wk + 1) % 4]]

def live_reports() -> dict:
    """Real beachgoer lot reports from the last 3 hours (slug → {status, at, count})."""
    try:
        r = requests.get(f"{SITE}/.netlify/functions/beach-report", timeout=15)
        data = r.json() if r.ok else {}
    except Exception:
        return {}
    now_ms = datetime.now().timestamp() * 1000
    return {k: v for k, v in (data or {}).items()
            if isinstance(v, dict) and v.get("at") and now_ms - float(v["at"]) < 3 * 3600 * 1000}

def fmt_fireworks(evs: list[dict]):
    lines = [rotate(["🎆 Fireworks on the Cape TONIGHT — here's where:",
                     "🎆 Tonight's the night — Cape Cod fireworks lineup:",
                     "🎆 Grab a blanket. Fireworks tonight at:"]), ""]
    towns = []
    for e in evs[:6]:
        lines.append(ev_line(e))
        if e.get("town"):
            towns.append(e["town"])
    lines += ["", "Tag who you're taking." + (" 🇺🇸" if now_et().month == 7 else "")]
    tags = base_tags() + ["#Fireworks", "#CapeCodEvents"] + [hashtag(t) for t in towns[:2]]
    return lines, FIREWORKS_IMG, "fireworks", tags

def fmt_beach_pick():
    if is_offseason():
        return fmt_beach_walk()
    beaches = (load("beaches.json") or {}).get("beaches") or []
    live = live_reports()
    live_open = [b for b in beaches if (live.get(b.get("slug")) or {}).get("status") == "open"]
    opens = live_open or sorted([b for b in beaches if b.get("status") == "open"],
                                key=lambda b: b.get("crowd", 3))
    if not opens:
        return fmt_tonight()
    cond = (load("conditions.json") or {}).get("today") or {}
    water = cond.get("water_temp_f")
    b = opens[0]
    if live_open:
        hook = rotate([f"Reported just now: {b.get('name')} has spots.",
                       f"Skip the circling — beachgoers say {b.get('name')} has room right now."])
        detail = (b.get("town") or "") + " · live report from the app"
    else:   # typical pattern only — no "right now" claims
        hook = rotate([f"Locals' move today: {b.get('name')}.",
                       f"If you only hit one beach today, make it {b.get('name')}.",
                       f"Usually an easier lot: {b.get('name')}."])
        detail = (b.get("town") or "") + " · usually has parking — check live reports before you drive"
    lines = [f"🏖️ {hook}", ""]
    if detail.strip():
        lines.append(detail)
    if water:
        lines.append(f"🌊 Water's {water}° today.")
    if len(opens) > 1:
        lines.append(f"Backup: {opens[1].get('name')}, {opens[1].get('town','')}.")
    lines += ["", "Live lot status for all 27 beaches on the app — check before you drive."]
    tags = base_tags() + ["#CapeCodBeaches", hashtag(b.get("town", "CapeCod"))]
    return lines, photo_for("beach"), "beach_pick", tags

def temp_is_fresh(b: dict, hours: int = 6) -> bool:
    """True only when the beach's water-temp reading is recent (feeds slow off-season)."""
    try:
        at = datetime.fromisoformat(str(b.get("water_temp_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(ET) - at).total_seconds() < hours * 3600

def fmt_beach_walk():
    """Off-season Monday: one beach for a walk, with today's real water temp + tides."""
    beaches = (load("beaches.json") or {}).get("beaches") or []
    if not beaches:
        return fmt_sunset()
    b = rotate(sorted(beaches, key=lambda x: x.get("slug", "")))
    cond = (load("conditions.json") or {}).get("today") or {}
    sset = (cond.get("sun") or {}).get("sunset")
    tides = ", ".join(f"{'High' if t.get('type') == 'high' else 'Low'} {t.get('time')}"
                      for t in (cond.get("tides") or [])[:4] if t.get("time"))
    hook = rotate([f"Off-season beach walk of the week: {b.get('name')}.",
                   f"The Cape's best-kept secret is {now_et().strftime('%B')}. This week: {b.get('name')}.",
                   f"Quiet lot, open sand: {b.get('name')}, {b.get('town', '')}."])
    lines = [f"🍂 {hook}", "", f"📍 {b.get('name')} — {b.get('town', '')}"]
    if b.get("water_temp") and temp_is_fresh(b):
        lines.append(f"🌊 Water {b['water_temp']}° right now (nearest NOAA/buoy reading)")
    if tides:
        lines.append(f"↕️ Tides today: {tides}")
    if sset:
        lines.append(f"🌅 Sunset {sset}")
    lines += ["", "No lifeguards this time of year — enjoy it from the sand. 🧥",
              "Live water temps + tides for 27 beaches on the app."]
    tags = base_tags() + ["#CapeCodBeaches", hashtag(b.get("town", "CapeCod"))]
    return lines, photo_for("beach"), "beach_walk", tags

def fmt_open_ask():
    """Off-season Saturday: community ask — what's open this weekend (the #1 off-season question)."""
    hook = rotate(["🙋 Off-season question for the locals:",
                   "🙋 Help a visitor out this weekend:",
                   "🙋 Cape crowd — settle this for the off-season folks:"])
    lines = [hook, "",
             "What's your favorite spot that stays open all winter? Coffee, chowder, "
             "breakfast, a bar with a fireplace — drop the name and town. 👇",
             "",
             "We'll check the best answers and add them to our off-season guide — with credit to you."]
    tags = base_tags() + ["#CapeCodOffSeason", "#CapeCodEats"]
    return lines, photo_for("town", salt=1), "open_ask", tags

def fmt_report_ask():
    """Community ask: crowdsource beach-lot reports. Runs Saturday morning — peak
    beach traffic, when a report is worth the most to the next family in the car.
    The ask is the point; the beach list is the excuse to post it."""
    if is_offseason():
        return fmt_open_ask()
    beaches = (load("beaches.json") or {}).get("beaches") or []
    picks = sorted(beaches, key=lambda b: b.get("crowd", 3), reverse=True)[:3]
    hook = rotate(["🙏 Cape crowd, do a stranger a solid this morning:",
                   "🙏 One tap from your beach chair helps the whole Cape:",
                   "🙏 Beach-day favor — takes literally ten seconds:"])
    lines = [hook, "",
             "If you're AT a beach today, open the app, tap your lot's status "
             "(🟢 spots · 🟠 filling · 🔴 full). That's it.",
             "",
             "Somebody circling with hot kids in the back seat sees your report "
             "before they waste the drive. Next weekend, someone does it for you."]
    if picks:
        names = " · ".join(f"{b.get('name')}" for b in picks if b.get("name"))
        lines += ["", f"Busiest lots most Saturdays: {names} — reports from those help most."]
    lines += ["", "Live lot status for all 27 beaches is free on the app."]
    tags = base_tags() + ["#CapeCodBeaches", "#CapeCodTips"]
    return lines, photo_for("beach", salt=1), "report_ask", tags

def fmt_tonight():
    today = now_et().strftime("%Y-%m-%d")
    evs = evening_events(today, 3)
    if not evs:
        return fmt_sunset()
    hook = rotate(["Don't say there's nothing to do tonight:",
                   "Tonight on the Cape — three good calls:",
                   "Your evening, sorted:"])
    lines = [f"🎟️ {hook}", ""]
    towns = []
    for e in evs:
        lines.append(ev_line(e))
        if e.get("town"):
            towns.append(e["town"])
    lines += ["", "Full list — every town, every night — on the app."]
    tags = base_tags() + ["#CapeCodEvents"] + [hashtag(t) for t in dict.fromkeys(towns)][:2]
    return lines, photo_for("events"), "tonight", tags

QUESTIONS = [
    ("Nauset or Race Point — you only get one this week. Defend your answer. 🦞", "beach"),
    ("Settle it once and for all: lobster roll HOT with butter, or COLD with mayo?", "food"),
    ("Best sunset on the Cape: Rock Harbor, Skaket… or somewhere you won't tell anyone?", "sunset"),
    ("Ocean side or bay side — where does your beach chair actually live?", "beach"),
    ("One Cape ice cream stand gets your entire summer budget. Which one?", "food"),
    ("P-town or Chatham for a day trip when guests are visiting?", "town"),
    ("Clam shack fries or onion rings? (There is a wrong answer.)", "food"),
    ("8 AM empty beach or 5 PM golden-hour beach?", "beach"),
    ("Which Main Street wins: Chatham, Falmouth, or Wellfleet?", "town"),
    ("Sagamore or Bourne at 9 AM on a Saturday — which do you chance?", "question"),
]

QUESTIONS_OFF = [
    ("Best off-season Cape day: empty beach walk, or a long lunch in P-town?", "beach"),
    ("Settle it once and for all: lobster roll HOT with butter, or COLD with mayo?", "food"),
    ("Best sunset on the Cape: Rock Harbor, Skaket… or somewhere you won't tell anyone?", "sunset"),
    ("Chowder or bisque on a cold Cape night? Defend your answer. 🥣", "food"),
    ("Which Main Street is best in the off-season: Chatham, Falmouth, or Wellfleet?", "town"),
    ("Clam shack fries or onion rings? (There is a wrong answer.)", "food"),
    ("Ocean side or bay side for a winter beach walk?", "beach"),
    ("Sagamore or Bourne — which bridge do you trust on a Sunday in November?", "question"),
]

def fmt_question():
    q, kind = rotate(QUESTIONS_OFF if is_offseason() else QUESTIONS)
    lines = [q, "", "👇 Drop it in the comments."]
    tags = base_tags() + ["#CapeCodDebate"]
    return lines, photo_for(kind, salt=3), "question", tags

# Locals-only spots (sourced from hidden-gems.html; keep the two in sync).
GEMS = [
    ("Ballston Beach", "Truro", "a smaller lot, fewer people, and waves instead of Bluetooth speakers", "late afternoon into sunset"),
    ("Great Pond", "Truro", "beach energy without the Atlantic chill — calm, pretty, perfect with a book", "early morning on hot days"),
    ("Paine's Creek Beach", "Brewster", "marsh, light, and quiet — the kind of place that makes you whisper", "45 minutes before sunset"),
    ("Jeremy Point Trail", "Wellfleet", "a wild walk to a remote point that feels gloriously far from everything", "low-tide windows"),
    ("Long Point Lighthouse", "Provincetown", "the walk out IS the experience — water, sky, and that perfect Cape weirdness", "morning or late day"),
    ("Herring River Overlook", "Wellfleet", "a tiny detour that pays off with huge golden-hour light and zero chaos", "golden hour"),
    ("The quiet side of Chatham", "Chatham", "skip the main drag — harbor nooks and a softer, slower Chatham", "late afternoon"),
    ("Marconi Beach trails", "Wellfleet", "everyone knows the beach; the cliff and dune paths are where the wow happens", "any breezy day"),
    ("Old Colony Rail Trail", "Lower Cape", "not every gem is a beach — this stretch lets you actually notice the Cape", "early mornings"),
]

def fmt_gem():
    name, town, why, when = rotate(GEMS)
    hook = rotate(["Locals would prefer we didn't post this one:",
                   "A Cape spot that never makes the guidebooks:",
                   "Hidden gem of the week:"], salt=1)
    lines = [f"🤫 {hook}", "",
             f"📍 {name} — {town}",
             f"{why[0].upper()}{why[1:]}.",
             f"Best time: {when}.", "",
             "Save this for your next trip. More locals-only spots on the app."]
    tags = base_tags() + ["#HiddenGem", hashtag(town)]
    return lines, photo_for("gem"), "gem", tags

def fmt_weekend():
    today = now_et()
    sat = (today + timedelta(days=(5 - today.weekday()) % 7)).strftime("%Y-%m-%d")
    sun = (today + timedelta(days=(6 - today.weekday()) % 7)).strftime("%Y-%m-%d")
    sat_evs = [e for e in events_on(sat) if plausible_time(e)][:6]
    sun_evs = [e for e in events_on(sun) if plausible_time(e)][:6]
    if len(sat_evs) + len(sun_evs) < 3:
        return fmt_tonight()
    lines = [rotate(["🗓️ THE CAPE THIS WEEKEND — save this list:",
                     "🗓️ Your Cape Cod weekend, planned in one post:",
                     "🗓️ Everything worth leaving the beach for this weekend:"]), ""]
    towns = []
    for label, evs in (("SATURDAY", sat_evs), ("SUNDAY", sun_evs)):
        if not evs:
            continue
        lines.append(label)
        for e in evs:
            lines.append(ev_line(e))
            if e.get("town"):
                towns.append(e["town"])
        lines.append("")
    lines.append("Share this with whoever you're dragging along. 🦞")
    tags = base_tags() + ["#CapeCodEvents", "#ThingsToDoCapeCod"] + \
        [hashtag(t) for t in dict.fromkeys(towns)][:2]
    return lines, photo_for("events", salt=1), "weekend", tags

def fmt_spotlight():
    today = now_et().strftime("%Y-%m-%d")
    evs = events_on(today)
    pick = next((e for e in evs if e.get("category") in ("festival", "family")), None) \
        or (evs[0] if evs else None)
    if not pick:
        return fmt_beach_pick()
    t = (pick.get("time") or "").split("·")[-1].strip()
    lines = [rotate([f"Today's the day: {pick.get('title')}.",
                     f"If you're near {pick.get('town','the Cape')} today — {pick.get('title')}.",
                     f"Worth the drive today: {pick.get('title')}."]), ""]
    where = " · ".join(x for x in (pick.get("venue"), pick.get("town"), t) if x)
    if where:
        lines.append(f"📍 {where}")
    if pick.get("info"):
        lines.append(pick["info"])
    if pick.get("price"):
        lines.append(f"🎟️ {pick['price']}")
    lines += ["", "More happening today on the app."]
    kind = "family" if pick.get("category") == "family" else "events"
    tags = base_tags() + ["#CapeCodEvents", hashtag(pick.get("town", "CapeCod"))]
    return lines, photo_for(kind, salt=2), "spotlight", tags

def fmt_sunset():
    cond = (load("conditions.json") or {}).get("today") or {}
    sun = cond.get("sun") or {}
    spot = sun.get("best_sunset_spot") or {}
    sset = sun.get("sunset") or "tonight"
    name = spot.get("name", "Rock Harbor")
    town = spot.get("town", "Orleans")
    hook = rotate([f"Tonight's sunset call: {name}.",
                   f"Golden hour homework: be at {name} by {sset}.",
                   f"The Cape shows off at {sset} tonight. Best seat: {name}."])
    lines = [f"🌅 {hook}", "", f"📍 {name}, {town} · sunset {sset}"]
    wx = cond.get("weather") or {}
    if wx.get("condition"):
        lines.append(f"{wx.get('icon','')} {wx['condition']}, high {wx.get('temp_high','?')}°".strip())
    lines += ["", rotate(["Tag the person you'd watch it with.",
                          "Bring a sweatshirt. Thank us later.",
                          "Photos in the comments, please. 📸"], salt=2)]
    tags = base_tags() + ["#CapeCodSunset", hashtag(town)]
    return lines, photo_for("sunset"), "sunset", tags

def fmt_evening():
    today = now_et().strftime("%Y-%m-%d")
    evs = evening_events(today, 4)
    cond = (load("conditions.json") or {}).get("today") or {}
    sset = (cond.get("sun") or {}).get("sunset")
    beaches = (load("beaches.json") or {}).get("beaches") or []
    live = {} if is_offseason() else live_reports()
    opens = [b for b in beaches if (live.get(b.get("slug")) or {}).get("status") == "open"][:2]
    lines = [rotate(["🌙 Tonight on the Cape:",
                     "🌙 Making plans? Here's tonight:",
                     "🌙 The Cape after 5, sorted:"]), ""]
    towns = []
    for e in evs:
        lines.append(ev_line(e))
        if e.get("town"):
            towns.append(e["town"])
    if opens:
        names = " & ".join(b.get("name", "") for b in opens)
        lines.append(f"🏖️ Beachgoers report room at {names} for a late-day swim.")
    if sset:
        lines.append(f"🌅 Sunset {sset}.")
    lines += ["", "Live events + water temps on the app." if is_offseason() else "Live events + beach lots on the app."]
    tags = base_tags() + ["#CapeCodTonight"] + [hashtag(t) for t in dict.fromkeys(towns)][:2]
    return lines, photo_for("sunset", salt=1), "evening", tags

# ------------------------------------------------------------------ compose ---
# Saturday = report_ask: peak beach morning, when a lot report helps the most people.
# (fmt_spotlight still runs via the weekend/evening slots' event coverage.)
MORNING_FORMATS = {0: fmt_beach_pick, 1: fmt_tonight, 2: fmt_question,
                   3: fmt_gem, 4: fmt_weekend, 5: fmt_report_ask, 6: fmt_sunset}

# --------------------------------------------------------- photos for posts --
# House rule (Oct 2026): posts use ONLY real Cape Cod scenery with NO people in the shot.
# The pool = the founder's own Nauset Light shots (PHOTO_TAGS, no credit needed) + every
# data/photos.json photo with post.rotation (local photographers who gave permission, and
# public-domain National Park Service photos). Least-recently-used goes first so the feed
# doesn't repeat; any photo that isn't the founder's gets a full credit line automatically.
# post.occasions maps MM-DD -> a holiday post (e.g. "12-25": "christmas").

def _in_window(mmdd: str, win: dict | None) -> bool:
    if not win:
        return True
    a, b = win.get("from", "01-01"), win.get("to", "12-31")
    return a <= mmdd <= b if a <= b else (mmdd >= a or mmdd <= b)

def _mmdd() -> str:
    return os.environ.get("TCC_FAKE_MMDD", "") or now_et().strftime("%m-%d")

def scenery_pool() -> list[dict]:
    """Every photo the posters may use, as dicts with id/file/title/place and _by (credit info)."""
    pool = [{"id": f"founder:{f}", "file": f"img/social/{f}", "title": "", "place": "", "_by": None}
            for f in sorted(PHOTO_TAGS) if (SOCIAL / f).exists()]
    data = load("photos.json") or {}
    people = data.get("photographers") or {}
    mmdd = _mmdd()
    for ph in data.get("photos") or []:
        post = ph.get("post") or {}
        if post.get("rotation") and _in_window(mmdd, post.get("window")) and (ROOT / ph["file"]).exists():
            pool.append({**ph, "_by": people.get(ph.get("photographer"), {})})
    return pool

def pick_photo(mode: str, state: dict) -> dict | None:
    data = load("photos.json") or {}
    people = data.get("photographers") or {}
    mmdd = _mmdd()
    if mode == "morning":                                  # dated occasions win
        for ph in data.get("photos") or []:
            occ = ((ph.get("post") or {}).get("occasions") or {}).get(mmdd)
            if occ and (ROOT / ph["file"]).exists():
                return {**ph, "_by": people.get(ph.get("photographer"), {}), "_occasion": occ}
    pool = scenery_pool()
    if not pool:
        return None
    used = state.get("photo_last_used") or {}
    salt = now_et().timetuple().tm_yday
    # least recently used first; never-used photos first of all; stable shuffle among ties
    pool.sort(key=lambda ph: (used.get(ph["id"], ""), (hash_str(ph["id"]) + salt) % 9973))
    return pool[0]

def hash_str(s: str) -> int:
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h

def photo_label(ph: dict) -> str:
    """'Highland Light — Truro', or just the place when the title is already in it."""
    what, place = ph.get("title", ""), ph.get("place", "")
    if place and what and what.lower() in place.lower():
        return place
    return f"{what} — {place}" if place and place != what else what

def pd_credit(ph: dict, by: dict) -> str:
    """'Brittni Connell / National Park Service' or 'National Park Service, Cape Cod National Seashore'."""
    c = (ph.get("credit") or "").strip()
    named = c.split("/", 1)[1].strip() if "/" in c else ""
    return f"{named} / National Park Service" if named else by.get("name", "National Park Service")

def photo_credit(ph: dict | None) -> tuple[str, str]:
    """(facebook_line, instagram_line). Empty for the founder's own photos."""
    by = (ph or {}).get("_by") or {}
    if not ph or not by:
        return "", ""
    label = photo_label(ph)
    if by.get("license") == "public-domain":
        who = pd_credit(ph, by)
        fb = f"📸 {label}. Photo: {who} (public domain) → {ph.get('source_url', '')}".strip()
        ig = f"📸 {label}. Photo: {who} (public domain)."
        return fb, ig
    name = by.get("name", "the photographer")
    fb = f"📸 {label}. Photo by {name}, shared with permission. See more of their work → {by.get('facebook', '')}".strip()
    ig = f"📸 {label}. Photo by {name}, shared with permission. Find more of their work on Facebook: {name}"
    return fb, ig

def fmt_christmas():
    lines = ["🎄 Merry Christmas from all of us at Totally Cape Cod!", "",
             "Wishing you a warm, bright day, wherever you're celebrating. Thanks for spending the year on the Cape with us."]
    return lines, "", "christmas", ["#MerryChristmas", "#CapeCod", "#CapeCodLife"]

def compose(mode: str, state: dict | None = None):
    """Return (fb_message, ig_caption, image_url, campaign, photo_id)."""
    today = now_et().strftime("%Y-%m-%d")
    fireworks = [e for e in events_on(today) if "FIREWORK" in (e.get("tag") or "").upper()]
    ph = pick_photo(mode, state or {})
    if ph and ph.get("_occasion") == "christmas":
        lines, img, campaign, tags = fmt_christmas()
    elif mode == "evening":
        lines, img, campaign, tags = fmt_evening()
    elif fireworks:
        lines, img, campaign, tags = fmt_fireworks(fireworks)
    else:
        lines, img, campaign, tags = MORNING_FORMATS[weekday_et()]()
    july_fireworks = img == FIREWORKS_IMG and now_et().month == 7     # that graphic says "4th of July"
    if ph and not july_fireworks:
        img = f"{RAW_BASE}/{ph['file']}"
    else:
        ph = None

    body = "\n".join(lines).rstrip()
    tagline = " ".join(dict.fromkeys(tags))          # dedupe, keep order
    credit_fb, credit_ig = photo_credit(ph)
    fb_message = f"{body}\n\n{credit_fb + chr(10) + chr(10) if credit_fb else ''}{tagline}"
    ig_caption = f"{body}\n\n{credit_ig + chr(10) + chr(10) if credit_ig else ''}🔗 totallycapecod.com\n\n{tagline}"
    return fb_message, ig_caption, img, campaign, (ph or {}).get("id", "")

def tracked_link(campaign: str) -> str:
    return f"{SITE}/?utm_source=facebook&utm_medium=social&utm_campaign={campaign}"

# -------------------------------------------------------------------- posting -
def post(message: str, image: str | None) -> str:
    if image:
        r = requests.post(f"{GRAPH}/{PAGE_ID}/photos",
                          data={"url": image, "caption": message, "access_token": TOKEN},
                          timeout=60)
    else:
        r = requests.post(f"{GRAPH}/{PAGE_ID}/feed",
                          data={"message": message, "access_token": TOKEN}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Facebook API {r.status_code}: {r.text[:400]}")
    return (r.json().get("post_id") or r.json().get("id") or "")

def comment(object_id: str, message: str) -> None:
    """First-comment the tracked link (links in comments dodge the feed demotion)."""
    r = requests.post(f"{GRAPH}/{object_id}/comments",
                      data={"message": message, "access_token": TOKEN}, timeout=60)
    if not r.ok:
        print(f"[fb] comment failed (non-fatal): {r.status_code} {r.text[:200]}", file=sys.stderr)

def post_instagram(caption: str, image: str) -> str:
    """Two-step Instagram publish: create a media container, then publish it."""
    c = requests.post(f"{GRAPH}/{IG_USER_ID}/media",
                      data={"image_url": image, "caption": caption, "access_token": TOKEN},
                      timeout=60)
    if not c.ok:
        raise RuntimeError(f"IG create {c.status_code}: {c.text[:400]}")
    cid = c.json().get("id")
    # Instagram processes the image asynchronously. Publishing too early fails with
    # "Media ID is not available / not ready for publishing" (code 9007) — that was
    # behind ~1 in 4 missed IG posts in Sep–Oct 2026. Wait for FINISHED, then publish,
    # and retry the publish a few times if Instagram still says it isn't ready.
    for _ in range(12):                       # up to ~60 s
        st = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code", "access_token": TOKEN}, timeout=30)
        code = st.json().get("status_code") if st.ok else None
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG container {code}: {st.text[:300]}")
        time.sleep(5)
    for attempt in range(4):
        p = requests.post(f"{GRAPH}/{IG_USER_ID}/media_publish",
                          data={"creation_id": cid, "access_token": TOKEN}, timeout=60)
        if p.ok:
            return p.json().get("id", "")
        if '"code":9007' in p.text and attempt < 3:
            time.sleep(10)
            continue
        raise RuntimeError(f"IG publish {p.status_code}: {p.text[:400]}")
    return ""

def main() -> None:
    mode = os.environ.get("MODE", "").strip() or ("evening" if now_et().hour >= 15 else "morning")
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}
    fb_message, ig_caption, image, campaign, photo_id = compose(mode, state)
    today_iso = now_et().strftime("%Y-%m-%d")
    state_key = "last_posted_date" if mode == "morning" else "last_posted_evening_date"
    link = tracked_link(campaign)
    link_comment = (f"📍 Live water temps, bridge delays & tonight's events → {link}" if is_offseason()
                    else f"📍 Live beach parking, bridge delays & tonight's events → {link}")

    if DRY_RUN:
        targets = "Facebook" + (" + Instagram" if IG_USER_ID else "")
        print(f"--- DRY RUN [{mode} · {campaign}] (to {targets}, image={image}) ---")
        print(fb_message)
        if photo_id:
            print(f"--- instagram caption ---\n{ig_caption}")
        print(f"--- first comment ---\n{link_comment}")
        return

    if not PAGE_ID or not TOKEN:
        print("ERROR: FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if state.get(state_key) == today_iso and not FORCE:
        print(f"[fb] already posted {mode} slot for {today_iso} — skipping (FORCE=1 to override)")
        return

    pid = post(fb_message, image)
    print(f"[fb] ✓ posted {pid} [{mode} · {campaign}] for {today_iso}")
    comment(pid, link_comment)

    ig_id = ""
    if IG_USER_ID:
        if not image:
            print("[ig] skipped — Instagram requires an image", file=sys.stderr)
        else:
            try:
                ig_id = post_instagram(ig_caption, image)
                print(f"[ig] ✓ posted {ig_id}")
                comment(ig_id, (f"Live water temps + tonight's events → {link}" if is_offseason()
                                else f"Live beach parking + tonight's events → {link}"))
            except Exception as e:
                print(f"[ig] ✗ {e}", file=sys.stderr)

    if photo_id:
        state.setdefault("photo_last_used", {})[photo_id] = today_iso
    state.update({state_key: today_iso,
                  f"last_{mode}_post_id": pid,
                  f"last_{mode}_ig_post_id": ig_id,
                  f"last_{mode}_campaign": campaign})
    STATE.write_text(json.dumps(state, indent=2) + "\n")

if __name__ == "__main__":
    main()
