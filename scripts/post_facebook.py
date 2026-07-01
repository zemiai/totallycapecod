"""Auto-post a daily "Cape Cod Today" update to a Facebook Page.

Reads the app's own live data (data/conditions.json, beaches.json, bridges.json,
events.json + the curated layer) and composes one human-sounding post, then
publishes it to a Facebook Page via the Graph API. On fireworks/holiday days it
leads with the pinned fireworks and attaches the branded image; otherwise it
posts a text + link so Facebook renders the totallycapecod.com preview card.

Idempotent: writes data/.fb_state.json with the date it last posted and refuses
to post twice for the same Eastern-time day (so a manual re-run or a retry won't
double-post). Set FORCE=1 to override, or DRY_RUN=1 to print the post without
sending it.

Secrets (GitHub Actions → repo settings → Secrets):
  FB_PAGE_ID            — numeric id of the Facebook Page
  FB_PAGE_ACCESS_TOKEN  — long-lived Page access token (see SETUP_FACEBOOK.md)

Run via .github/workflows/post-facebook.yml (daily), or locally:
  DRY_RUN=1 python scripts/post_facebook.py
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime
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

# Always-on tags, then per-town and per-category tags get added from the day's
# content so every post is discoverable by the right local + interest audiences.
BASE_TAGS = ["#CapeCod", "#CapeCodLife", "#CapeCodMA", "#CapeCodSummer"]
CATEGORY_TAGS = {
    "music": ["#LiveMusic", "#CapeCodMusic"],
    "food": ["#CapeCodEats", "#CapeCodFoodie"],
    "food_deal": ["#CapeCodEats"],
    "happy_hour": ["#HappyHour", "#CapeCodEats"],
    "family": ["#FamilyFun", "#CapeCodFamily"],
    "festival": ["#CapeCodEvents", "#Festival"],
    "art": ["#CapeCodArt", "#ArtsOnCape"],
    "farmers_market": ["#FarmersMarket", "#ShopLocal"],
    "theater": ["#CapeCodTheater"],
    "film": ["#CapeCodFilm"],
    "talk": ["#CapeCodEvents"],
    "event": ["#CapeCodEvents"],
}
FIREWORKS_TAGS = ["#Fireworks", "#FourthOfJuly", "#July4th", "#IndependenceDay"]
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")

PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
DRY_RUN = os.environ.get("DRY_RUN") == "1"
FORCE = os.environ.get("FORCE") == "1"


def load(name: str):
    try:
        return json.loads((DATA / name).read_text())
    except Exception:
        return None


def fmt_delay(b: dict | None) -> str:
    if not b:
        return ""
    d = b.get("current_delay_min")
    if d is None:
        return ""
    if d <= 2:
        return "no delays"
    return f"{d} min"


def events_today(today_iso: str) -> list[dict]:
    """All events (scraped + curated) starting on today's ET date."""
    out, seen = [], set()
    for fname, key in (("events.json", "events"), ("curated.json", "events")):
        d = load(fname) or {}
        for e in (d.get(key) or []):
            start = (e.get("start") or "")[:10]
            if start == today_iso and e.get("id") not in seen:
                seen.add(e.get("id"))
                out.append(e)
    # pinned (fireworks) first, then keep source order
    out.sort(key=lambda e: 0 if e.get("pinned") else 1)
    return out


def hashtag(word: str) -> str:
    """'West Dennis' -> '#WestDennis'."""
    parts = [p for p in "".join(c if c.isalnum() or c == " " else " " for c in word).split() if p]
    return "#" + "".join(p.capitalize() for p in parts)


def build_hashtags(towns, categories, is_fireworks: bool, has_beach: bool) -> list[str]:
    tags: list[str] = list(BASE_TAGS)
    if is_fireworks:
        tags += FIREWORKS_TAGS
    if has_beach:
        tags.append("#CapeCodBeaches")
    for c in categories:
        tags += CATEGORY_TAGS.get(c, [])
    for t in list(towns)[:4]:  # cap town tags so it doesn't read spammy
        if t:
            tags.append(hashtag(t))
    seen, out = set(), []
    for t in tags:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out[:14]


def pick_image(today_iso: str, is_fireworks: bool) -> str | None:
    """Pick the day's photo (returned as a public raw URL).

    Priority: a date-named file you drop in img/social/ (e.g. 2026-07-04.jpg) →
    fireworks image on fireworks days → a rotating branded image from img/social/
    → the branded default. Drop any picture in img/social/ and it goes into the
    rotation automatically.
    """
    if SOCIAL.exists():
        for ext in IMG_EXTS:
            f = SOCIAL / f"{today_iso}{ext}"
            if f.exists():
                return f"{RAW_BASE}/img/social/{f.name}"
    if is_fireworks:
        return FIREWORKS_IMG
    extras = []
    if SOCIAL.exists():
        extras = sorted(
            p.name for p in SOCIAL.iterdir()
            if p.suffix.lower() in IMG_EXTS and p.stem not in ("default",)
            and len(p.stem) != 10  # skip date-named files (handled above)
        )
    if extras:
        doy = datetime.strptime(today_iso, "%Y-%m-%d").timetuple().tm_yday
        return f"{RAW_BASE}/img/social/{extras[doy % len(extras)]}"
    if (SOCIAL / "default.png").exists():
        return f"{RAW_BASE}/img/social/default.png"
    return None


def compose() -> tuple[str, str | None]:
    """Return (message, image_url_or_None)."""
    now = datetime.now(ET)
    today_iso = now.strftime("%Y-%m-%d")
    nice_date = now.strftime("%A, %B %-d")

    cond = (load("conditions.json") or {}).get("today", {}) or {}
    wx = cond.get("weather", {}) or {}
    sun = cond.get("sun", {}) or {}
    bridges = (load("bridges.json") or {}).get("current", {}) or {}

    lines = [f"☀️ Cape Cod Today — {nice_date}", ""]

    # Weather + water
    bits = []
    water = cond.get("water_temp_f")
    if water:
        bits.append(f"🌊 Water {water}°")
    cn = wx.get("condition")
    hi = wx.get("temp_high")
    if cn and hi:
        bits.append(f"{wx.get('icon','')} {cn}, high {hi}°".strip())
    if bits:
        lines.append(" · ".join(bits))

    # Sunset + best spot
    sset = sun.get("sunset")
    spot = (sun.get("best_sunset_spot") or {})
    if sset:
        s = f"🌅 Sunset {sset}"
        if spot.get("name"):
            s += f" — best spot tonight: {spot['name']}"
            if spot.get("town"):
                s += f", {spot['town']}"
        lines.append(s)

    # Bridges
    sag = fmt_delay(bridges.get("sagamore"))
    bou = fmt_delay(bridges.get("bourne"))
    if sag or bou:
        parts = []
        if bou:
            parts.append(f"Bourne {bou}")
        if sag:
            parts.append(f"Sagamore {sag}")
        lines.append("🌉 " + " · ".join(parts))

    # Events / fireworks
    evs = events_today(today_iso)
    fireworks = [e for e in evs if "FIREWORK" in (e.get("tag") or "").upper()]
    is_fireworks = bool(fireworks)
    towns, categories = [], []
    if is_fireworks:
        lines.append("")
        lines.append("🎆 FIREWORKS TONIGHT:")
        for e in fireworks[:6]:
            t = e.get("time", "")
            town = e.get("town", "")
            lines.append(f"• {e.get('title')} — {town}" + (f" · {t.split('·')[-1].strip()}" if "·" in t else ""))
            if town:
                towns.append(town)
    else:
        highlights = [e for e in evs if e.get("time") and ("PM" in e["time"] or "AM" in e["time"])][:3]
        if highlights:
            lines.append("")
            lines.append("📅 Happening today:")
            for e in highlights:
                t = e["time"].split("·")[-1].strip()
                lines.append(f"• {e.get('title')} — {e.get('town','')} · {t}")
                if e.get("town"):
                    towns.append(e["town"])
    for e in evs:
        if e.get("category"):
            categories.append(e["category"])

    lines.append("")
    lines.append(f"Live beach parking, bridge traffic & today's events 👉 {SITE}")

    # keep town order but unique
    seen, uniq_towns = set(), []
    for t in towns:
        if t not in seen:
            seen.add(t)
            uniq_towns.append(t)
    tags = build_hashtags(uniq_towns, dict.fromkeys(categories), is_fireworks, has_beach=True)
    lines.append("")
    lines.append(" ".join(tags))

    img = pick_image(today_iso, is_fireworks)
    return "\n".join(lines), img


def post(message: str, image: str | None) -> str:
    if image:
        r = requests.post(
            f"{GRAPH}/{PAGE_ID}/photos",
            data={"url": image, "caption": message, "access_token": TOKEN},
            timeout=60,
        )
    else:
        r = requests.post(
            f"{GRAPH}/{PAGE_ID}/feed",
            data={"message": message, "link": SITE, "access_token": TOKEN},
            timeout=60,
        )
    if not r.ok:
        raise RuntimeError(f"Facebook API {r.status_code}: {r.text[:400]}")
    return (r.json().get("post_id") or r.json().get("id") or "")


def main() -> None:
    message, image = compose()
    today_iso = datetime.now(ET).strftime("%Y-%m-%d")

    if DRY_RUN:
        print(f"--- DRY RUN (would post, image={image}) ---\n{message}")
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
    if state.get("last_posted_date") == today_iso and not FORCE:
        print(f"[fb] already posted for {today_iso} — skipping (FORCE=1 to override)")
        return

    pid = post(message, image)
    STATE.write_text(json.dumps({"last_posted_date": today_iso, "last_post_id": pid}, indent=2) + "\n")
    print(f"[fb] ✓ posted {pid} for {today_iso}")


if __name__ == "__main__":
    main()
