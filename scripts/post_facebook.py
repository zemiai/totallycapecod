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
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

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
# Curated Cape photos in img/social/ (Pexels, free commercial — STOCK_CREDITS.md),
# tagged so each format gets an on-topic image. Day-of-year rotation keeps variety.
PHOTO_TAGS = {
    "beach-dunes.jpg":       {"beach"},
    "beach-umbrella.jpg":    {"beach", "sunset"},
    "cape-beach-grass.jpg":  {"beach", "gem"},
    "cape-sunset-heart.jpg": {"sunset", "question"},
    "coastal-cottage.jpg":   {"town", "gem", "question"},
    "kids-at-shore.jpg":     {"beach", "family"},
    "oysters.jpg":           {"food", "events", "question"},
    "pier-sunset.jpg":       {"beach", "sunset"},
    "sunset-water.jpg":      {"sunset", "events"},
    "whale-watch-fluke.jpg": {"gem", "events", "family"},
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

def events_on(date_iso: str) -> list[dict]:
    """All events (scraped + curated) starting on the given ET date."""
    out, seen = [], set()
    for fname in ("events.json", "curated.json"):
        for e in (load(fname) or {}).get("events") or []:
            if (e.get("start") or "")[:10] == date_iso and e.get("id") not in seen:
                seen.add(e.get("id"))
                out.append(e)
    out.sort(key=lambda e: (0 if e.get("pinned") else 1, e.get("start") or ""))
    return out

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
    return [BASE_TAGS[wk % 4], BASE_TAGS[(wk + 1) % 4]]

def fmt_fireworks(evs: list[dict]):
    lines = [rotate(["🎆 Fireworks on the Cape TONIGHT — here's where:",
                     "🎆 Tonight's the night — Cape Cod fireworks lineup:",
                     "🎆 Grab a blanket. Fireworks tonight at:"]), ""]
    towns = []
    for e in evs[:6]:
        lines.append(ev_line(e))
        if e.get("town"):
            towns.append(e["town"])
    lines += ["", "Tag who you're taking. 🇺🇸"]
    tags = base_tags() + ["#Fireworks", "#CapeCodEvents"] + [hashtag(t) for t in towns[:2]]
    return lines, FIREWORKS_IMG, "fireworks", tags

def fmt_beach_pick():
    beaches = (load("beaches.json") or {}).get("beaches") or []
    opens = sorted([b for b in beaches if b.get("status") == "open"],
                   key=lambda b: b.get("crowd", 3))
    if not opens:
        return fmt_tonight()  # nothing open (off-season) — fall through
    cond = (load("conditions.json") or {}).get("today") or {}
    water = cond.get("water_temp_f")
    b = opens[0]
    hook = rotate([f"Locals' move today: {b.get('name')}.",
                   f"If you only hit one beach today, make it {b.get('name')}.",
                   f"Skip the circling — {b.get('name')} has room right now."])
    lines = [f"🏖️ {hook}", ""]
    detail = (b.get("town") or "") + (f" · {b.get('spots_text')}" if b.get("spots_text") else "")
    if detail.strip():
        lines.append(detail)
    if water:
        lines.append(f"🌊 Water's {water}° today.")
    if len(opens) > 1:
        lines.append(f"Backup: {opens[1].get('name')}, {opens[1].get('town','')}.")
    lines += ["", "Live lot status for all 27 beaches on the app — check before you drive."]
    tags = base_tags() + ["#CapeCodBeaches", hashtag(b.get("town", "CapeCod"))]
    return lines, photo_for("beach"), "beach_pick", tags

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

def fmt_question():
    q, kind = rotate(QUESTIONS)
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
    opens = [b for b in beaches if b.get("status") == "open"][:2]
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
        lines.append(f"🏖️ Still room at {names} for a late-day swim.")
    if sset:
        lines.append(f"🌅 Sunset {sset}.")
    lines += ["", "Live events + beach lots on the app."]
    tags = base_tags() + ["#CapeCodTonight"] + [hashtag(t) for t in dict.fromkeys(towns)][:2]
    return lines, photo_for("sunset", salt=1), "evening", tags

# ------------------------------------------------------------------ compose ---
MORNING_FORMATS = {0: fmt_beach_pick, 1: fmt_tonight, 2: fmt_question,
                   3: fmt_gem, 4: fmt_weekend, 5: fmt_spotlight, 6: fmt_sunset}

def compose(mode: str):
    """Return (fb_message, ig_caption, image_url, campaign)."""
    today = now_et().strftime("%Y-%m-%d")
    fireworks = [e for e in events_on(today) if "FIREWORK" in (e.get("tag") or "").upper()]
    if mode == "evening":
        lines, img, campaign, tags = fmt_evening()
    elif fireworks:
        lines, img, campaign, tags = fmt_fireworks(fireworks)
    else:
        lines, img, campaign, tags = MORNING_FORMATS[weekday_et()]()

    body = "\n".join(lines).rstrip()
    tagline = " ".join(dict.fromkeys(tags))          # dedupe, keep order
    fb_message = f"{body}\n\n{tagline}"
    ig_caption = f"{body}\n\n🔗 totallycapecod.com\n\n{tagline}"
    return fb_message, ig_caption, img, campaign

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
    p = requests.post(f"{GRAPH}/{IG_USER_ID}/media_publish",
                      data={"creation_id": cid, "access_token": TOKEN}, timeout=60)
    if not p.ok:
        raise RuntimeError(f"IG publish {p.status_code}: {p.text[:400]}")
    return p.json().get("id", "")

def main() -> None:
    mode = os.environ.get("MODE", "").strip() or ("evening" if now_et().hour >= 15 else "morning")
    fb_message, ig_caption, image, campaign = compose(mode)
    today_iso = now_et().strftime("%Y-%m-%d")
    state_key = "last_posted_date" if mode == "morning" else "last_posted_evening_date"
    link = tracked_link(campaign)
    link_comment = f"📍 Live beach parking, bridge delays & tonight's events → {link}"

    if DRY_RUN:
        targets = "Facebook" + (" + Instagram" if IG_USER_ID else "")
        print(f"--- DRY RUN [{mode} · {campaign}] (to {targets}, image={image}) ---")
        print(fb_message)
        print(f"--- first comment ---\n{link_comment}")
        return

    if not PAGE_ID or not TOKEN:
        print("ERROR: FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}
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
                comment(ig_id, f"Live beach parking + tonight's events → {link}")
            except Exception as e:
                print(f"[ig] ✗ {e}", file=sys.stderr)

    state.update({state_key: today_iso,
                  f"last_{mode}_post_id": pid,
                  f"last_{mode}_ig_post_id": ig_id,
                  f"last_{mode}_campaign": campaign})
    STATE.write_text(json.dumps(state, indent=2) + "\n")

if __name__ == "__main__":
    main()
