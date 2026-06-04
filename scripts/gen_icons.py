"""One-shot icon/favicon/OG generator for Totally Cape Cod.
Run: python scripts/gen_icons.py
Source: ../image.jpg.jpg (1024x1024 logo on white)
"""
import os
from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"C:\Users\908 Bistro\Downloads\image.jpg.jpg"
BG = (255, 255, 255)  # white — matches the logo's native background (no seam)

def load_trimmed(src):
    im = Image.open(src).convert("RGB")
    # Build a near-white reference and diff to find real content bbox
    white = Image.new("RGB", im.size, (255, 255, 255))
    diff = ImageChops.difference(im, white).convert("L")
    # Binarize: anything more than ~12/255 away from white counts as content
    mask = diff.point(lambda p: 255 if p > 12 else 0)
    bbox = mask.getbbox()
    if bbox:
        im = im.crop(bbox)
    return im

def square_canvas(clam, size, fill_ratio, bg=BG):
    """Place trimmed clam centered on a square `size`x`size` canvas at fill_ratio."""
    canvas = Image.new("RGB", (size, size), bg)
    target = int(size * fill_ratio)
    w, h = clam.size
    scale = min(target / w, target / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = clam.resize((nw, nh), Image.LANCZOS)
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2))
    return canvas

def out(name):
    return os.path.join(ROOT, name)

clam = load_trimmed(SRC)
print("trimmed clam size:", clam.size)

# PWA icons (purpose: any) — generous fill on cream
square_canvas(clam, 192, 0.90).save(out("icon-192.png"))
square_canvas(clam, 512, 0.90).save(out("icon-512.png"))
# Maskable — clam in the center ~72% safe zone, full-bleed cream
square_canvas(clam, 512, 0.72).save(out("icon-maskable-512.png"))
# Apple touch icon (iOS applies its own rounded mask)
square_canvas(clam, 180, 0.86).save(out("apple-touch-icon.png"))
# Favicons
square_canvas(clam, 32, 0.94).save(out("favicon-32.png"))
square_canvas(clam, 16, 0.94).save(out("favicon-16.png"))
ico_base = square_canvas(clam, 256, 0.94)
ico_base.save(out("favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])

# OG / social share image 1200x630, clam centered on cream
og = Image.new("RGB", (1200, 630), BG)
w, h = clam.size
scale = min((1200 * 0.62) / w, (630 * 0.78) / h)
nw, nh = int(w * scale), int(h * scale)
resized = clam.resize((nw, nh), Image.LANCZOS)
og.paste(resized, ((1200 - nw) // 2, (630 - nh) // 2))
og.save(out("og-image.png"))

print("done:", [n for n in (
    "icon-192.png", "icon-512.png", "icon-maskable-512.png",
    "apple-touch-icon.png", "favicon-32.png", "favicon-16.png",
    "favicon.ico", "og-image.png")])
