"""Build /photos.html from data/photos.json — local photographers' work, used with permission.

Every photo is credited to the photographer, links to the original post, and the page
pushes visitors to the photographer's own page/portfolio. Run after editing photos.json:

    python scripts/build_photos_page.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://totallycapecod.com"


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def main() -> None:
    data = json.loads((ROOT / "data" / "photos.json").read_text(encoding="utf-8"))
    pgs = data["photographers"]
    sections, ld_images = [], []
    for pid, p in pgs.items():
        photos = [x for x in data["photos"] if x["photographer"] == pid and x.get("gallery", True)]
        if not photos:
            continue
        cards = []
        for x in photos:
            place = f'{esc(x["place"])} · ' if x.get("place") else ""
            note = f'<p class="ph-note">{esc(x["photographer_note"])}</p>' if x.get("photographer_note") else ""
            cards.append(
                f'<figure class="ph-card">'
                f'<a href="{esc(x["source_url"])}" target="_blank" rel="noopener" '
                f'onclick="gtag(\'event\',\'outbound_click\',{{type:\'photographer\',item:\'{esc(x["id"])}\',location:\'photos_page\'}})">'
                f'<img src="/{esc(x["file"])}" width="{x["width"]}" height="{x["height"]}" alt="{esc(x["alt"])}" loading="lazy" /></a>'
                f'<figcaption><strong>{esc(x["title"])}</strong><span>{place}📸 {esc(p["name"])}</span>{note}'
                f'<a class="ph-link" href="{esc(x["source_url"])}" target="_blank" rel="noopener">View the original →</a></figcaption></figure>')
            ld_images.append({
                "@type": "ImageObject",
                "contentUrl": f'{SITE}/{x["file"]}',
                "name": x["title"],
                "description": x["alt"],
                "creditText": p["name"],
                "creator": {"@type": "Organization", "name": p["name"], "url": p["facebook"]},
                "copyrightNotice": f'© {p["name"]}',
                "acquireLicensePage": p.get("portfolio") or p["facebook"],
            })
        links = [f'<a class="btn btn-navy btn-sm" href="{esc(p["facebook"])}" target="_blank" rel="noopener">See more on Facebook →</a>']
        if p.get("portfolio"):
            links.append(f'<a class="btn btn-sm ph-ghost" href="{esc(p["portfolio"])}" target="_blank" rel="noopener">Portfolio →</a>')
        sections.append(
            f'<section class="section"><div class="ph-head"><div><h2 class="section-title" style="margin:0;">{esc(p["name"])}</h2>'
            f'<p class="ph-about">{esc(p.get("about", ""))}</p></div><div class="ph-links">{"".join(links)}</div></div>'
            f'<div class="ph-grid">{"".join(cards)}</div></section>')

    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Cape Cod Through Local Lenses",
          "url": f"{SITE}/photos.html", "hasPart": ld_images}
    title = "Cape Cod Photos by Local Photographers | Totally Cape Cod"
    desc = "Cape Cod photos shared with permission by local photographers, each credited and linked so you can see more of their work."
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="theme-color" content="#1A3A6C" />
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{SITE}/photos.html" />
<meta property="og:title" content="{esc(title)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:type" content="website" />
<meta property="og:url" content="{SITE}/photos.html" />
<meta property="og:image" content="{SITE}/{esc(data['photos'][0]['file'])}" />
<meta name="twitter:card" content="summary_large_image" />
<script async src="https://www.googletagmanager.com/gtag/js?id=G-Q0YM9WQLWK"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','G-Q0YM9WQLWK');</script>
<script src="/js/pixel.js" defer></script>
<link rel="stylesheet" href="css/tcc.css" />
<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<style>
  .content-wrap{{max-width:1080px;margin:0 auto;padding:0 20px 64px;}}
  .ph-head{{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;flex-wrap:wrap;margin-bottom:16px;}}
  .ph-about{{margin:4px 0 0;color:var(--text-secondary);font-size:14px;}}
  .ph-links{{display:flex;gap:8px;flex-wrap:wrap;}}
  .ph-ghost{{border:1px solid var(--divider);background:white;}}
  .ph-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}}
  @media(max-width:768px){{.ph-grid{{grid-template-columns:repeat(2,1fr);}}}}
  @media(max-width:520px){{.ph-grid{{grid-template-columns:1fr;}}}}
  .ph-card{{margin:0;background:white;border-radius:var(--radius-md);overflow:hidden;box-shadow:var(--shadow-sm);}}
  .ph-card img{{display:block;width:100%;height:260px;object-fit:cover;}}
  .ph-card figcaption{{padding:12px 14px 14px;font-size:13px;color:var(--text-secondary);line-height:1.5;}}
  .ph-card figcaption strong{{display:block;font-size:15px;color:var(--cape-brown-dark);}}
  .ph-card figcaption span{{display:block;}}
  .ph-note{{margin:6px 0 0;font-style:italic;}}
  .ph-link{{display:inline-block;margin-top:6px;font-weight:700;}}
</style>
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
</head>
<body>
<nav class="site-nav" id="siteNav"><div class="nav-inner"><a href="/" class="nav-logo">Totally Cape Cod</a><div class="nav-links"><a href="/beaches.html">Beaches</a><a href="/eats.html">Eats</a><a href="/events.html">Events</a><a href="/guides/">Guides</a><a href="/app/">📱 App</a></div><button class="nav-mobile-toggle" onclick="toggleMobileMenu()">☰</button></div></nav>
<div class="mobile-menu" id="mobileMenu" onclick="toggleMobileMenu()"><div class="mobile-menu-panel" onclick="event.stopPropagation()"><a href="/">Home</a><a href="/beaches.html">Beaches</a><a href="/eats.html">Eats</a><a href="/events.html">Events</a><a href="/guides/">Guides</a><a href="/app/">📱 Open the App</a></div></div>

<section class="hero" style="min-height:40vh;"><div class="hero-overlay"></div><div class="hero-content" style="padding-top:84px;max-width:860px;"><div class="hero-badge">📸 Local Photographers</div><h1 class="hero-title">Cape Cod Through Local Lenses</h1><p class="hero-subtitle">Shared with the photographers' permission. Tap any photo to see the original, then go see more of their work.</p></div></section>

<div class="content-wrap">
{"".join(sections)}
<section class="section"><div class="card" style="padding:22px;text-align:center;"><h3 style="font-family:'Fraunces',serif;font-weight:900;margin:0 0 6px;">Photograph the Cape?</h3><p style="color:var(--text-secondary);margin:0 0 12px;">We feature local photographers with full credit and a link back, and only with your permission.</p><a class="btn btn-primary" href="/contact.html">Get in touch →</a></div></section>
</div>

<footer class="site-footer"><div class="footer-inner"><div><div class="footer-brand">Totally Cape Cod</div><p class="footer-desc">The unofficial guide to the best of Cape Cod.</p></div><div class="footer-links"><div class="footer-heading">Explore</div><a href="/beaches.html">Beaches</a><a href="/eats.html">Restaurants</a><a href="/events.html">Events</a><a href="/photos.html">Photos</a></div><div class="footer-links"><div class="footer-heading">Guides</div><a href="/guides/">All guides</a><a href="/guides/standards/">How we fact-check</a><a href="/contact.html">Report an error</a></div></div><div class="footer-bottom">© 2026 Totally Cape Cod. Photos © their photographers, used with permission.</div></footer>
<script>function toggleMobileMenu(){{document.getElementById('mobileMenu').classList.toggle('show');}}</script>
</body>
</html>
"""
    (ROOT / "photos.html").write_text(page, encoding="utf-8")
    print(f"✓ photos.html — {sum(1 for _ in data['photos'])} photo(s) from {len(pgs)} photographer(s)")


if __name__ == "__main__":
    main()
