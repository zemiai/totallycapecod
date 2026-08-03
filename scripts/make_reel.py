#!/usr/bin/env python3
"""Build a 15-second vertical Reel (1080x1920 mp4) from the curated photo pool
plus live event data — no external assets, just ffmpeg + DejaVu.

Themes rotate by ET weekday:
  Tue (1): "TONIGHT ON THE CAPE"      — 3 evening events today
  Fri (4): "THIS WEEKEND ON CAPE COD" — 3 weekend picks (Sat+Sun)
  other:   falls back to tonight-style (so manual runs always work)

Slides: intro (title+date) → one per event (photo + text card) → outro (site).
Silent on purpose: we have no licensed music, and Meta lets viewers add audio.

Writes:  img/social/reel-YYYY-MM-DD.mp4
         data/.reel_manifest.json  {video, fb_caption, ig_caption, date}
scripts/post_reel.py publishes from the manifest after the mp4 is pushed.

Run: python scripts/make_reel.py   (needs ffmpeg; ubuntu-latest has it)
"""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from post_facebook import (SOCIAL, DATA, PHOTO_TAGS, now_et, weekday_et,
                           events_on, evening_events, plausible_time, clock_of)

W, H = 1080, 1920
SLIDE_S = 2.9
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def esc(s: str) -> str:
    """Escape text for ffmpeg drawtext."""
    return (s.replace("\\", "\\\\").replace("'", "’")
             .replace(":", "\\:").replace("%", "\\%").replace(",", "\\,"))


def wrap(s: str, width: int = 22, max_lines: int = 3) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:width - 1] + "…"
    return lines


def photos(n: int) -> list[Path]:
    pool = sorted(p for p in (SOCIAL / f for f in PHOTO_TAGS) if p.exists())
    if not pool:
        sys.exit("no photos in img/social — nothing to build a reel from")
    doy = now_et().timetuple().tm_yday
    return [pool[(doy + i) % len(pool)] for i in range(n)]


def slide(photo: Path, texts: list[tuple[str, int, int, str]], out: Path) -> None:
    """One slide: cover-cropped photo, dark scrim, stacked drawtext lines.
    texts: (line, size, y, font_path)."""
    draw = [f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
            "eq=brightness=-0.08",
            f"drawbox=x=0:y={H - 900}:w={W}:h=900:color=black@0.45:t=fill"]
    for line, size, y, font in texts:
        draw.append(
            f"drawtext=fontfile={font}:text='{esc(line)}':fontcolor=white:"
            f"fontsize={size}:x=(w-text_w)/2:y={y}:shadowcolor=black@0.6:shadowx=2:shadowy=2")
    draw.append(f"fade=t=in:st=0:d=0.35,fade=t=out:st={SLIDE_S - 0.35}:d=0.35")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", str(SLIDE_S),
         "-i", str(photo), "-vf", ",".join(draw),
         "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
         str(out)], check=True)


def event_slide_texts(e: dict) -> list[tuple[str, int, int, str]]:
    texts = []
    y = H - 780
    for ln in wrap(e.get("title", ""), 20, 3):
        texts.append((ln, 76, y, FONT))
        y += 96
    where = e.get("venue") or e.get("town") or ""
    sub = " · ".join(x for x in (where, clock_of(e)) if x)
    if sub:
        texts.append((sub[:44], 46, y + 24, FONT_REG))
    return texts


def main() -> None:
    now = now_et()
    date_iso = now.strftime("%Y-%m-%d")
    wd = weekday_et()

    if wd == 4:  # Friday — weekend picks
        title, tagline = "THIS WEEKEND", "ON CAPE COD"
        sat = (now + timedelta(days=(5 - now.weekday()) % 7)).strftime("%Y-%m-%d")
        sun = (now + timedelta(days=(6 - now.weekday()) % 7)).strftime("%Y-%m-%d")
        evs = ([e for e in events_on(sat) if plausible_time(e)][:2] +
               [e for e in events_on(sun) if plausible_time(e)][:1])
        campaign = "reel_weekend"
        hook = "This weekend on Cape Cod 🦞 Save this."
    else:        # default — tonight
        title, tagline = "TONIGHT", "ON THE CAPE"
        evs = evening_events(date_iso, 3)
        campaign = "reel_tonight"
        hook = "Tonight on the Cape 🌙 Don't say there's nothing to do."

    if len(evs) < 2:
        print("[reel] fewer than 2 events — skipping build")
        sys.exit(0)

    out_mp4 = SOCIAL / f"reel-{date_iso}.mp4"
    pics = photos(len(evs) + 2)
    tmp = Path(tempfile.mkdtemp(prefix="tcc-reel-"))
    parts = []
    try:
        intro = tmp / "s0.mp4"
        slide(pics[0], [(title, 130, H - 760, FONT),
                        (tagline, 130, H - 600, FONT),
                        (now.strftime("%A, %B %-d"), 48, H - 430, FONT_REG)], intro)
        parts.append(intro)
        for i, e in enumerate(evs, 1):
            p = tmp / f"s{i}.mp4"
            slide(pics[i], event_slide_texts(e), p)
            parts.append(p)
        outro = tmp / "s9.mp4"
        slide(pics[-1], [("totallycapecod.com", 72, H - 720, FONT),
                         ("live events · beach parking", 46, H - 610, FONT_REG),
                         ("bridge delays · free", 46, H - 540, FONT_REG)], outro)
        parts.append(outro)

        concat = tmp / "list.txt"
        concat.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", str(concat), "-c", "copy", str(out_mp4)],
                       check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    lines = [hook, ""] + [f"• {e.get('title','')[:60]} — {e.get('venue') or e.get('town','')}" for e in evs]
    tags = "#CapeCod #CapeCodLife #CapeCodEvents #ThingsToDoCapeCod"
    fb_caption = "\n".join(lines) + f"\n\nFull list on totallycapecod.com\n\n{tags}"
    ig_caption = "\n".join(lines) + f"\n\n🔗 totallycapecod.com\n\n{tags} #Reels"

    (DATA / ".reel_manifest.json").write_text(json.dumps({
        "video": f"img/social/{out_mp4.name}", "date": date_iso,
        "campaign": campaign, "fb_caption": fb_caption, "ig_caption": ig_caption,
    }, indent=2) + "\n")
    size = out_mp4.stat().st_size
    print(f"[reel] built {out_mp4.name} ({size//1024} KB, {len(parts)} slides)")


if __name__ == "__main__":
    main()
