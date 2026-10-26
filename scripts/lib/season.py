"""Season switch for scripts — same rules as js/season.js.

data/season.json:
  mode: "auto" | "summer" | "offseason"
  auto_summer_start / auto_summer_end: "MM-DD" (used when mode == "auto")
Override for testing: TCC_SEASON=summer|offseason
"""
from __future__ import annotations
import json, os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parent.parent.parent / "data"
ET = ZoneInfo("America/New_York")
DEF_START, DEF_END = "05-22", "09-14"


def _md(s: str, fallback: str) -> int:
    try:
        m, d = (int(x) for x in str(s).split("-"))
        return m * 100 + d
    except Exception:
        return _md(fallback, "01-01") if fallback != s else 101


def season_mode(now: datetime | None = None) -> str:
    forced = os.environ.get("TCC_SEASON", "").strip().lower()
    if forced in ("summer", "offseason"):
        return forced
    try:
        cfg = json.loads((DATA / "season.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    mode = cfg.get("mode")
    if mode in ("summer", "offseason"):
        return mode
    now = (now or datetime.now(ET)).astimezone(ET)
    x = now.month * 100 + now.day
    a = _md(cfg.get("auto_summer_start", DEF_START), DEF_START)
    b = _md(cfg.get("auto_summer_end", DEF_END), DEF_END)
    return "summer" if a <= x <= b else "offseason"


def is_offseason(now: datetime | None = None) -> bool:
    return season_mode(now) == "offseason"


def season_hashtag(now: datetime | None = None) -> str:
    """#CapeCodSummer in summer mode; otherwise the calendar season."""
    now = (now or datetime.now(ET)).astimezone(ET)
    if season_mode(now) == "summer":
        return "#CapeCodSummer"
    m = now.month
    return "#CapeCodFall" if m in (9, 10, 11) else "#CapeCodWinter" if m in (12, 1, 2) else "#CapeCodSpring"
