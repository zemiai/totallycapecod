#!/usr/bin/env python3
"""Generate the day's branded social image into img/social/YYYY-MM-DD.jpg.

Runs inside the post-facebook.yml workflow BEFORE scripts/post_facebook.py.
post_facebook.py's pick_image() prefers a date-named file in img/social/, so
committing this file makes the daily post use the fresh branded graphic.

Mode rotates by Eastern-time weekday:
  Mon/Thu/Sat -> beaches   (beach lot status)
  Tue/Fri     -> events    (what's on today, from events.json + curated.json)
  Wed/Sun     -> outlook   (weather + bridges)
Events mode falls back to outlook if fewer than 3 events today.

Data comes straight from the repo checkout (data/*.json) — always fresh because
the hermes crons commit hourly/daily. No network needed except a one-time font
fallback download.

Usage: python scripts/make_social_image.py [out_path]
       (default out: img/social/<today ET>.jpg)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
FONT_DIR = ROOT / "assets" / "fonts"
ET = ZoneInfo("America/New_York")

CREAM = (247, 241, 225)
CREAM2 = (240, 232, 210)
NAVY = (23, 58, 99)
SAND = (243, 205, 147)
GREEN = (67, 133, 91)
AMBER = (214, 151, 52)
RED = (196, 84, 72)
W, H = 1080, 1350

_FALLBACKS = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-{w}.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans{d}.ttf",
]


def font(sz: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = "Poppins-Bold.ttf" if bold else "Poppins-Regular.ttf"
    p = FONT_DIR / name
    if p.exists():
        return ImageFont.truetype(str(p), sz)
    for tpl in _FALLBACKS:
        cand = Path(tpl.format(w="Bold" if bold else "Regular", d="-Bold" if bold else ""))
        if cand.exists():
            return ImageFont.truetype(str(cand), sz)
    return ImageFont.load_default(sz)


def dot(d, x, y, r, color):
    d.ellipse((x - r, y - r, x + r, y + r), fill=color)


def load(name: str) -> dict:
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def now_et() -> datetime:
    return datetime.now(ET)


def today_str() -> str:
    return now_et().strftime("%A, %B %-d")


def base_canvas(title: str, subtitle: str):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    d.ellipse((-400, H - 320, W + 400, H + 340), fill=SAND)
    d.ellipse((-500, H - 260, W * 0.55, H + 300), fill=CREAM2)
    d.text((W / 2, 92), "T O T A L L Y   C A P E   C O D", font=font(30), fill=NAVY, anchor="mm")
    d.line((W / 2 - 160, 130, W / 2 + 160, 130), fill=SAND, width=5)
    d.text((W / 2, 205), title, font=font(74), fill=NAVY, anchor="mm")
    d.text((W / 2, 272), subtitle, font=font(32, bold=False), fill=NAVY, anchor="mm")
    d.text((W / 2, H - 72), "totallycapecod.com", font=font(38), fill=NAVY, anchor="mm")
    return img, d


def status_color(s):
    return {"open": GREEN, "mid": AMBER, "full": RED}.get(s, NAVY)


def status_label(s):
    return {"open": "OPEN", "mid": "FILLING", "full": "FULL"}.get(s, str(s).upper())


def make_beaches(out: Path) -> bool:
    beaches = load("beaches.json").get("beaches") or []
    if not beaches:
        return False
    fulls = [b for b in beaches if b.get("status") == "full"]
    mids = [b for b in beaches if b.get("status") == "mid"]
    opens = sorted([b for b in beaches if b.get("status") == "open"], key=lambda b: b.get("crowd", 3))
    rows = (fulls[:3] + mids[:2] + opens[:4])[:8]
    img, d = base_canvas("Beach Lot Status", today_str())
    y = 360
    for b in rows:
        c = status_color(b.get("status"))
        d.ellipse((90, y + 8, 122, y + 40), fill=c)
        d.text((150, y), b.get("name", ""), font=font(40), fill=NAVY)
        d.text((150, y + 48), f'{b.get("town", "")} · {b.get("spots_text", "")}', font=font(29, bold=False), fill=NAVY)
        d.text((990, y + 22), status_label(b.get("status")), font=font(34), fill=c, anchor="rm")
        y += 108
    d.text((W / 2, y + 28), "Live counts for 27 lots on the app", font=font(30, bold=False), fill=NAVY, anchor="mm")
    img.save(out, "JPEG", quality=90)
    return True


def events_today() -> list[dict]:
    """Events starting on today's ET date, from events.json + curated.json."""
    today_iso = now_et().strftime("%Y-%m-%d")
    out, seen = [], set()
    for fname in ("events.json", "curated.json"):
        for e in (load(fname).get("events") or []):
            start = (e.get("start") or "")[:10]
            if start == today_iso and e.get("id") not in seen:
                seen.add(e.get("id"))
                out.append(e)
    out.sort(key=lambda e: (0 if e.get("pinned") else 1, e.get("start") or ""))
    return out


def make_events(out: Path) -> bool:
    evs = events_today()
    if len(evs) < 3:
        return False  # thin day — caller falls back to outlook
    evs = evs[:6]
    img, d = base_canvas("On Cape Today", today_str())
    y = 360
    palette = [SAND, GREEN, AMBER, NAVY, RED]
    for i, e in enumerate(evs):
        title = e.get("title", "")
        title = title[:36] + ("…" if len(title) > 36 else "")
        where = e.get("venue") or e.get("town") or ""
        when = (e.get("time") or "").split("·")[-1].strip()
        dot(d, 106, y + 24, 14, palette[i % len(palette)])
        d.text((160, y), title, font=font(36), fill=NAVY)
        d.text((160, y + 48), f"{when} · {where}"[:58], font=font(27, bold=False), fill=NAVY)
        y += 112
    d.text((W / 2, y + 28), "Full list of 100+ events on the app", font=font(30, bold=False), fill=NAVY, anchor="mm")
    img.save(out, "JPEG", quality=90)
    return True


def make_outlook(out: Path) -> bool:
    cond = load("conditions.json").get("today") or {}
    br = load("bridges.json").get("current") or {}
    wx, sun = cond.get("weather") or {}, cond.get("sun") or {}
    if not wx:
        return False
    img, d = base_canvas("Beach Day Outlook", today_str())
    y = 370
    spot = sun.get("best_sunset_spot") or {}
    rows = [
        ("WEATHER", AMBER, f'{wx.get("condition", "")} · High {wx.get("temp_high", "?")}° / Low {wx.get("temp_low", "?")}°'),
        ("WIND", AMBER, f'{wx.get("wind_mph", "?")} mph {wx.get("wind_dir", "")} · UV index {wx.get("uv_index", "?")}'),
        ("SUN", AMBER, f'Rise {sun.get("sunrise", "?")} · Set {sun.get("sunset", "?")}'),
        ("SUNSET SPOT", AMBER, f'{spot.get("name", "Skaket Beach")}, {spot.get("town", "Orleans")}'),
    ]
    for key in ("sagamore", "bourne"):
        b = br.get(key) or {}
        delay = b.get("current_delay_min", 0) or 0
        c = GREEN if delay < 10 else (AMBER if delay < 25 else RED)
        rows.append((b.get("name", key.title()).upper(), c,
                     "No delays" if delay == 0 else f"{delay} min delay"))
    for label, c, txt in rows:
        dot(d, 106, y + 30, 14, c)
        d.text((160, y), label, font=font(26), fill=c)
        d.text((160, y + 34), txt[:44], font=font(38), fill=NAVY)
        y += 130
    img.save(out, "JPEG", quality=90)
    return True


MODE_BY_WEEKDAY = {0: "beaches", 1: "events", 2: "outlook", 3: "beaches", 4: "events", 5: "beaches", 6: "outlook"}
MAKERS = {"beaches": make_beaches, "events": make_events, "outlook": make_outlook}


def main() -> None:
    today_iso = now_et().strftime("%Y-%m-%d")
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "img" / "social" / f"{today_iso}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)

    mode = MODE_BY_WEEKDAY[now_et().weekday()]
    tried = [mode]
    ok = MAKERS[mode](out)
    if not ok and mode != "outlook":
        tried.append("outlook")
        ok = make_outlook(out)
    if not ok and "beaches" not in tried:
        tried.append("beaches")
        ok = make_beaches(out)

    if ok:
        print(f"[social-img] wrote {out} (mode: {tried[-1]})")
    else:
        # No image is not fatal — post_facebook.py falls back to img/social/default.png
        print("[social-img] no usable data for any mode — skipping (poster will use default image)", file=sys.stderr)


if __name__ == "__main__":
    main()
