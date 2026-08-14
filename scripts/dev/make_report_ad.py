#!/usr/bin/env python3
"""One-off: 'live lot reports' ad creative (4:5 + 1:1) into img/ads/.

Angle (Aug 14): community-powered live parking status. Unlike the earlier
'know before you drive' ad, the status rows here mirror what the app actually
shows — status label + a live-report chip — no invented spot counts.
Background: beach-umbrella.jpg (portrait, licensed — see STOCK_CREDITS.md).
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).parent.parent.parent
FONTS = ROOT / "assets" / "fonts"
OUT = ROOT / "img" / "ads"

CREAM = (247, 241, 225)
NAVY = (23, 58, 99)
SAND = (243, 205, 147)
GREEN = (31, 157, 99)
ORANGE = (217, 119, 6)
RED = (220, 38, 38)
INK = (28, 32, 38)
SUB = (110, 116, 125)

def F(sz, bold=True):
    return ImageFont.truetype(str(FONTS / ("Poppins-Bold.ttf" if bold else "Poppins-Regular.ttf")), sz)

def rounded(d, xy, r, fill):
    d.rounded_rectangle(xy, radius=r, fill=fill)

def build(w, h, out_name):
    # Background photo, cover-cropped, darkened toward the bottom for text
    ph = Image.open(ROOT / "img/social/beach-umbrella.jpg").convert("RGB")
    scale = max(w / ph.width, h / ph.height)
    ph = ph.resize((int(ph.width * scale) + 1, int(ph.height * scale) + 1))
    ph = ph.crop(((ph.width - w) // 2, 0, (ph.width - w) // 2 + w, h))
    ph = ImageEnhance.Brightness(ph).enhance(0.88)
    grad = Image.new("L", (1, h))
    for y in range(h):
        t = max(0, (y / h - 0.28)) / 0.72
        grad.putpixel((0, y), int(190 * (t ** 1.4)))
    shade = Image.new("RGB", (w, h), (10, 24, 44))
    ph = Image.composite(shade, ph, grad.resize((w, h)))
    img = ph
    d = ImageDraw.Draw(img)
    M = int(w * 0.065)

    # Badge
    bw, bh = int(w * 0.42), int(h * 0.052)
    rounded(d, (M, M, M + bw, M + bh), bh // 2, None)
    d.rounded_rectangle((M, M, M + bw, M + bh), radius=bh // 2, outline=CREAM, width=3)
    t = "TOTALLY CAPE COD"
    f = F(int(bh * 0.42))
    tw = d.textlength(t, font=f)
    d.text((M + (bw - tw) / 2, M + bh * 0.26), t, font=f, fill=CREAM)

    # Headline block sits in the darkened lower ~62%
    y = int(h * (0.36 if h > w else 0.26))
    f_big = F(int(w * 0.095))
    d.text((M, y), "Is the lot full", font=f_big, fill=CREAM)
    y += int(w * 0.105)
    d.text((M, y), "right now?", font=f_big, fill=SAND)
    y += int(w * 0.125)
    f_sub = F(int(w * 0.036), bold=False)
    d.text((M, y), "Beachgoers report parking live — check", font=f_sub, fill=CREAM)
    y += int(w * 0.048)
    d.text((M, y), "before you drive, tap to pay it forward.", font=f_sub, fill=CREAM)
    y += int(w * 0.075)

    # Status rows — mirrors the real app UI: dot, beach, status label, live chip
    rows = [
        (GREEN, "Nauset Beach", "Orleans", "Spots open", "LIVE · 14m ago"),
        (ORANGE, "Old Silver Beach", "Falmouth", "Filling up", "LIVE · 32m ago"),
        (RED, "Coast Guard Beach", "Eastham", "Lot full", "LIVE · 8m ago"),
    ][: 3 if h > w else 2]
    rh = int(h * (0.075 if h > w else 0.082))
    f_name = F(int(rh * 0.34))
    f_town = F(int(rh * 0.24), bold=False)
    f_chip = F(int(rh * 0.22))
    for color, name, town, status, chip in rows:
        rounded(d, (M, y, w - M, y + rh), int(rh * 0.28), CREAM)
        cx = M + int(rh * 0.5)
        cy = y + rh // 2
        r = int(rh * 0.14)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        d.text((cx + int(rh * 0.38), y + int(rh * 0.16)), name, font=f_name, fill=INK)
        d.text((cx + int(rh * 0.38), y + int(rh * 0.55)), town, font=f_town, fill=SUB)
        sw = d.textlength(status, font=f_name)
        d.text((w - M - int(rh * 0.4) - sw, y + int(rh * 0.16)), status, font=f_name, fill=color)
        cw = d.textlength(chip, font=f_chip)
        chx = w - M - int(rh * 0.4) - cw
        d.text((chx, y + int(rh * 0.58)), chip, font=f_chip, fill=SUB)
        lr = int(rh * 0.07)
        d.ellipse((chx - lr * 3.2, y + int(rh * 0.68), chx - lr * 3.2 + 2 * lr, y + int(rh * 0.68) + 2 * lr), fill=GREEN)
        y += rh + int(h * 0.014)

    # CTA bar
    y += int(h * 0.012)
    ch = int(h * 0.068)
    cw_bar = int(w * 0.62)
    rounded(d, (M, y, M + cw_bar, y + ch), ch // 2, SAND)
    t = "totallycapecod.com"
    f_cta = F(int(ch * 0.42))
    tw = d.textlength(t, font=f_cta)
    d.text((M + (cw_bar - tw) / 2, y + ch * 0.24), t, font=f_cta, fill=NAVY)
    f_free = F(int(ch * 0.30), bold=False)
    d.text((M + cw_bar + int(w * 0.03), y + ch * 0.32), "FREE · no app store", font=f_free, fill=CREAM)

    img.save(OUT / out_name, quality=92)
    print("wrote", OUT / out_name, img.size)

build(1080, 1350, "ad-live-lots-4x5.jpg")
build(1080, 1080, "ad-live-lots-1x1.jpg")
