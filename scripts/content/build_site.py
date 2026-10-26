#!/usr/bin/env python3
"""Build Totally Cape Cod's guide articles from content/articles/*.md.

Each article is Markdown with YAML front matter. Facts carry numbered citations like
[1] or [1, 3] that must match an entry in the front-matter `sources` list — the build
fails on a citation with no source, so nothing unsourced can ship.

Outputs (all static, served by Netlify):
  guides/<slug>/index.html      one page per article (Article + Breadcrumb + FAQ schema)
  guides/index.html             the guides hub
  guides/standards/index.html   editorial + fact-checking standards
  guides/feed.xml               RSS feed
  authors/<id>/index.html       author page (Person schema)
  sitemap.xml                   regenerated: existing pages + every guide

Run:  python scripts/content/build_site.py           (build)
      python scripts/content/build_site.py --check   (validate only, non-zero exit on errors)
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import markdown
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "content"
ARTICLES = CONTENT / "articles"
SITE = "https://totallycapecod.com"
GA_ID = "G-Q0YM9WQLWK"
CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\](?!\()")


# ----------------------------------------------------------------- loading ---
def load_authors() -> dict:
    return json.loads((CONTENT / "authors.json").read_text(encoding="utf-8"))


def parse_article_text(text: str, name: str = "article") -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{name}: missing YAML front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    for k in ("date", "updated"):
        if isinstance(meta.get(k), (date, datetime)):
            meta[k] = meta[k].isoformat()[:10]
    meta.setdefault("updated", meta.get("date"))
    for s in meta.get("sources") or []:
        if isinstance(s.get("accessed"), (date, datetime)):
            s["accessed"] = s["accessed"].isoformat()[:10]
    return meta, m.group(2)


def parse_article(path: Path) -> tuple[dict, str]:
    meta, body = parse_article_text(path.read_text(encoding="utf-8"), path.name)
    meta.setdefault("slug", path.stem)
    return meta, body


def load_articles() -> list[tuple[dict, str]]:
    out = []
    for p in sorted(ARTICLES.glob("*.md")):
        meta, body = parse_article(p)
        if meta.get("status", "published") != "published":
            continue
        out.append((meta, body))
    out.sort(key=lambda mb: (mb[0].get("updated") or "", mb[0].get("date") or ""), reverse=True)
    return out


# -------------------------------------------------------------- validation ---
REQUIRED = ("title", "slug", "description", "date", "author", "sources")


def validate(meta: dict, body: str, authors: dict) -> list[str]:
    errs = []
    name = meta.get("slug", "?")
    for k in REQUIRED:
        if not meta.get(k):
            errs.append(f"{name}: front matter missing '{k}'")
    if meta.get("author") and meta["author"] not in authors:
        errs.append(f"{name}: unknown author '{meta['author']}'")
    if len(meta.get("description", "")) > 165:
        errs.append(f"{name}: description is {len(meta['description'])} chars (max 165)")
    ids = set()
    for s in meta.get("sources") or []:
        sid = s.get("id")
        if not isinstance(sid, int):
            errs.append(f"{name}: source without integer id: {s}")
            continue
        if sid in ids:
            errs.append(f"{name}: duplicate source id {sid}")
        ids.add(sid)
        if not re.match(r"^https?://", str(s.get("url", ""))):
            errs.append(f"{name}: source {sid} has no http(s) url")
        for k in ("title", "publisher", "accessed"):
            if not s.get(k):
                errs.append(f"{name}: source {sid} missing '{k}'")
    cited = set()
    texts = [body] + [f"{q.get('q','')} {q.get('a','')}" for q in meta.get("faq") or []]
    for t in texts:
        for m in CITE_RE.finditer(t):
            for n in m.group(1).split(","):
                cited.add(int(n))
    for n in sorted(cited - ids):
        errs.append(f"{name}: citation [{n}] has no matching source")
    for n in sorted(ids - cited):
        errs.append(f"{name}: source {n} is never cited")
    for q in meta.get("faq") or []:
        if not CITE_RE.search(q.get("a", "")):
            errs.append(f"{name}: FAQ answer without a citation: {q.get('q','')[:60]}")
    # Every paragraph/list item that states a number, date or price must carry a citation.
    lines_to_check = []
    for block in re.split(r"\n\s*\n|\n(?=\s*[-*] )", body):
        b = block.strip()
        if b.startswith("|"):
            rows = [r for r in b.splitlines() if r.strip().startswith("|")]
            lines_to_check += [r for r in rows[2:]]          # skip header + separator
        else:
            lines_to_check.append(b)
    for b in lines_to_check:
        if not b or b.startswith(("#", "<!--", "{{")):
            continue
        has_fact = re.search(r"\$\d|\b\d{1,2}(:\d{2})?\s?(AM|PM|a\.m\.|p\.m\.)|\b(19|20)\d{2}\b|\b\d+(\.\d+)?\s?(°|%|miles?|mi\b|feet|ft\b|minutes?|hours?)|"
                             r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b", b)
        if has_fact and not CITE_RE.search(b) and "data-live" not in b and "<!-- nocite -->" not in b:
            errs.append(f"{name}: factual block without a citation: {b[:90]!r}")
    return errs


# --------------------------------------------------------------- rendering ---
def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def pretty_date(iso: str) -> str:
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return d.strftime("%B %-d, %Y")


def cite_html(text: str, slug: str) -> str:
    def rep(m):
        nums = [n.strip() for n in m.group(1).split(",")]
        links = ",".join(f'<a href="#src-{n}" aria-label="Source {n}">{n}</a>' for n in nums)
        return f'<sup class="cite">[{links}]</sup>'
    return CITE_RE.sub(rep, text)


def md_to_html(md: str, slug: str) -> str:
    # {{events ...}} shortcode → live, sourced events widget (js/live-events.js)
    def events_widget(m):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        parts = ['data-live-events']
        for k in ("match", "from", "to", "town", "limit", "group"):
            if attrs.get(k):
                parts.append(f'data-{k}="{esc(attrs[k])}"')
        return (f'<div class="live-events-embed" {" ".join(parts)}>'
                f'<p class="muted">Loading upcoming events…</p></div>')
    md = re.sub(r"\{\{\s*events\s*(.*?)\}\}", events_widget, md)
    out = markdown.markdown(md, extensions=["tables", "sane_lists", "attr_list", "toc"],
                            extension_configs={"toc": {"permalink": False}})
    out = cite_html(out, slug)
    # external links open in a new tab, internal stay put
    out = re.sub(r'<a href="(https?://(?!totallycapecod\.com)[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', out)
    return out


NAV = ('<nav class="site-nav" id="siteNav"><div class="nav-inner"><a href="/" class="nav-logo">Totally Cape Cod</a>'
       '<div class="nav-links"><a href="/feed.html">📍 Near You</a><a href="/beaches.html">Beaches</a><a href="/eats.html">Eats</a>'
       '<a href="/events.html">Events</a><a href="/guides/">Guides</a><a href="/app/">📱 App</a></div>'
       '<button class="nav-mobile-toggle" onclick="toggleMobileMenu()">☰</button></div></nav>'
       '<div class="mobile-menu" id="mobileMenu" onclick="toggleMobileMenu()"><div class="mobile-menu-panel" onclick="event.stopPropagation()">'
       '<a href="/">Home</a><a href="/feed.html">📍 Near You</a><a href="/beaches.html">Beaches</a><a href="/eats.html">Eats</a>'
       '<a href="/events.html">Events</a><a href="/guides/">Guides</a><a href="/app/">📱 Open the App</a></div></div>')

FOOTER = ('<footer class="site-footer"><div class="footer-inner"><div><div class="footer-brand">Totally Cape Cod</div>'
          '<p class="footer-desc">The unofficial guide to the best of Cape Cod.</p></div>'
          '<div class="footer-links"><div class="footer-heading">Explore</div><a href="/beaches.html">Beaches</a><a href="/eats.html">Restaurants</a>'
          '<a href="/events.html">Events</a><a href="/experiences.html">Experiences</a></div>'
          '<div class="footer-links"><div class="footer-heading">Guides</div><a href="/guides/">All guides</a>'
          '<a href="/guides/standards/">How we fact-check</a><a href="/contact.html">Report an error</a></div></div>'
          '<div class="footer-bottom">© 2026 Totally Cape Cod. Affiliate links help keep this guide free.</div></footer>'
          '<script>function toggleMobileMenu(){document.getElementById("mobileMenu").classList.toggle("show");}</script>')

STYLE = """
<style>
  .g-wrap{max-width:760px;margin:0 auto;padding:96px 20px 64px;}
  .g-crumbs{font-size:13px;color:var(--text-secondary);margin-bottom:14px;}
  .g-crumbs a{color:inherit;}
  .g-kicker{display:inline-block;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--sea-deep);margin-bottom:8px;}
  .g-title{font-family:'Fraunces',Georgia,serif;font-weight:900;font-size:clamp(30px,5vw,44px);line-height:1.12;color:var(--warm-brown);margin:0 0 12px;}
  .g-dek{font-size:18px;line-height:1.55;color:var(--text);margin:0 0 16px;}
  .g-byline{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:14px;color:var(--text-secondary);padding:12px 0;border-top:1px solid var(--divider);border-bottom:1px solid var(--divider);margin-bottom:26px;}
  .g-byline a{color:var(--warm-brown);font-weight:700;text-decoration:none;}
  .g-body{font-size:17px;line-height:1.75;color:var(--text);}
  .g-body h2{font-family:'Fraunces',Georgia,serif;font-size:26px;line-height:1.25;color:var(--warm-brown);margin:38px 0 10px;}
  .g-body h3{font-size:19px;margin:26px 0 6px;color:var(--warm-brown);}
  .g-body a{color:var(--sea-deep);}
  .g-body ul,.g-body ol{padding-left:22px;}
  .g-body li{margin:6px 0;}
  .g-body table{width:100%;border-collapse:collapse;font-size:15px;margin:18px 0;display:block;overflow-x:auto;}
  .g-body th,.g-body td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--divider);vertical-align:top;}
  .g-body th{background:var(--sand-cream);font-weight:800;}
  .g-body blockquote{margin:18px 0;padding:12px 16px;background:var(--sand-cream);border-left:4px solid var(--sand-warm);border-radius:8px;}
  sup.cite{font-size:11px;line-height:0;margin-left:1px;white-space:nowrap;}
  sup.cite a{text-decoration:none;font-weight:700;color:var(--sea-deep);}
  .g-note{font-size:14px;line-height:1.55;background:#F3F8FA;border:1px solid #D7E8EE;border-radius:12px;padding:12px 14px;margin:22px 0;color:#2E4A55;}
  .g-faq{margin-top:36px;}
  .g-faq details{border-bottom:1px solid var(--divider);padding:12px 0;}
  .g-faq summary{font-weight:800;cursor:pointer;color:var(--warm-brown);}
  .g-faq p{margin:8px 0 0;}
  .g-sources{margin-top:38px;font-size:14px;line-height:1.55;}
  .g-sources h2{font-family:'Fraunces',Georgia,serif;font-size:22px;color:var(--warm-brown);}
  .g-sources ol{padding-left:22px;}
  .g-sources li{margin:6px 0;word-break:break-word;}
  .g-sources li:target{background:#FFF6D6;border-radius:6px;}
  .g-related{margin-top:36px;}
  .g-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;}
  .g-card{display:block;background:#fff;border:1px solid var(--divider);border-radius:14px;padding:16px;text-decoration:none;color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.04);}
  .g-card b{display:block;font-family:'Fraunces',Georgia,serif;font-size:18px;color:var(--warm-brown);margin:6px 0;line-height:1.25;}
  .g-card span{font-size:13px;color:var(--text-secondary);}
  .muted{color:var(--text-secondary);}
  .live-events-embed{margin:16px 0;}
  .live-events-embed .grid-3{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;}
  .live-events-embed .section{padding:10px 0;}
  .live-events-embed .section-title{font-size:18px;margin:8px 0;}
  @media(max-width:600px){.g-wrap{padding-top:84px;}.g-body{font-size:16px;}}
</style>
"""


def head(title: str, description: str, url: str, jsonld: list, og_type="article", extra="") -> str:
    ld = "\n".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in jsonld)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="theme-color" content="#1A3A6C" />
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}" />
<link rel="canonical" href="{esc(url)}" />
<meta property="og:title" content="{esc(title)}" />
<meta property="og:description" content="{esc(description)}" />
<meta property="og:type" content="{og_type}" />
<meta property="og:url" content="{esc(url)}" />
<meta property="og:image" content="{SITE}/og-image.png" />
<meta property="og:site_name" content="Totally Cape Cod" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{esc(title)}" />
<meta name="twitter:description" content="{esc(description)}" />
<meta name="twitter:image" content="{SITE}/og-image.png" />
<link rel="alternate" type="application/rss+xml" title="Totally Cape Cod Guides" href="{SITE}/guides/feed.xml" />
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','{GA_ID}');</script>
<script src="/js/pixel.js" defer></script>
<script src="/js/season.js"></script>
<link rel="stylesheet" href="/css/tcc.css" />
<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
{STYLE}{extra}
{ld}
</head>
<body>
{NAV}
"""


def publisher_ld() -> dict:
    return {"@type": "Organization", "name": "Totally Cape Cod", "url": SITE + "/",
            "logo": {"@type": "ImageObject", "url": SITE + "/icon-512.png"}}


def author_ld(aid: str, a: dict) -> dict:
    d = {"@type": "Person", "name": a["name"], "url": f"{SITE}/authors/{aid}/"}
    if a.get("job_title"):
        d["jobTitle"] = a["job_title"]
    if a.get("same_as"):
        d["sameAs"] = a["same_as"]
    return d


def plain(text: str) -> str:
    """Strip citations/markdown for schema + meta text."""
    t = CITE_RE.sub("", text)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"[*_`]", "", t).strip()


def card(meta: dict) -> str:
    return (f'<a class="g-card" href="/guides/{esc(meta["slug"])}/"><span>{esc(meta.get("kicker") or "Guide")}</span>'
            f'<b>{esc(meta["title"])}</b><span>Updated {esc(pretty_date(meta["updated"]))}</span></a>')


def render_article(meta: dict, body: str, authors: dict, all_articles: list) -> str:
    slug = meta["slug"]
    url = f"{SITE}/guides/{slug}/"
    a = authors[meta["author"]]
    body_html = md_to_html(body, slug)
    sources = sorted(meta.get("sources") or [], key=lambda s: s["id"])
    faq = meta.get("faq") or []

    ld = [{
        "@context": "https://schema.org", "@type": "Article",
        "headline": meta["title"][:110], "description": meta["description"],
        "datePublished": meta["date"], "dateModified": meta["updated"],
        "author": author_ld(meta["author"], a), "publisher": publisher_ld(),
        "mainEntityOfPage": url, "image": [f"{SITE}/og-image.png"],
        "citation": [s["url"] for s in sources],
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Guides", "item": SITE + "/guides/"},
            {"@type": "ListItem", "position": 3, "name": meta["title"], "item": url},
        ],
    }]
    if faq:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": plain(q["q"]),
             "acceptedAnswer": {"@type": "Answer", "text": plain(q["a"])}} for q in faq]})

    updated = ""
    if meta["updated"] != meta["date"]:
        updated = f' · Updated <time datetime="{meta["updated"]}">{pretty_date(meta["updated"])}</time>'
    byline = (f'<div class="g-byline"><span>By <a href="/authors/{esc(meta["author"])}/" rel="author">{esc(a["name"])}</a></span>'
              f'<span>Published <time datetime="{meta["date"]}">{pretty_date(meta["date"])}</time>{updated}</span>'
              f'<span><a href="/guides/standards/">How we fact-check</a></span></div>')
    faq_html = ""
    if faq:
        items = "".join(f'<details><summary>{esc(q["q"])}</summary><p>{cite_html(markdown.markdown(q["a"])[3:-4], slug)}</p></details>' for q in faq)
        faq_html = f'<section class="g-faq"><h2 class="g-title" style="font-size:26px;">Quick answers</h2>{items}</section>'
    src_items = "".join(
        f'<li id="src-{s["id"]}">{esc(s["publisher"])}: <a href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s["title"])}</a>'
        f'{(" — " + esc(s["note"])) if s.get("note") else ""} <span class="muted">(accessed {esc(pretty_date(str(s["accessed"])))})</span></li>'
        for s in sources)
    disclosure = meta.get("disclosure") or ("This guide was researched with the help of AI tools and checked line by line "
                                            "against the sources listed below before publishing.")
    related = [m for (m, _) in all_articles if m["slug"] != slug][:3]
    related_html = ""
    if related:
        related_html = f'<section class="g-related"><h2 class="g-title" style="font-size:24px;">More Cape Cod guides</h2><div class="g-cards">{"".join(card(m) for m in related)}</div></section>'
    needs_events = 'data-live-events' in body_html
    scripts = '<script src="/js/live-events.js" defer></script>' if needs_events else ""

    return (head(f'{meta.get("seo_title") or meta["title"]} | Totally Cape Cod', meta["description"], url, ld)
            + f"""<main class="g-wrap">
<div class="g-crumbs"><a href="/">Home</a> › <a href="/guides/">Guides</a></div>
<div class="g-kicker">{esc(meta.get("kicker") or "Guide")}</div>
<h1 class="g-title">{esc(meta["title"])}</h1>
<p class="g-dek">{esc(meta["description"])}</p>
{byline}
<article class="g-body">
{body_html}
</article>
{faq_html}
<div class="g-note">📝 {esc(disclosure)} Spot something out of date? <a href="/contact.html">Tell us</a> and we'll fix it.</div>
<section class="g-sources"><h2>Sources</h2><ol>{src_items}</ol></section>
{related_html}
</main>
{FOOTER}
{scripts}
</body>
</html>
""")


def render_hub(articles: list) -> str:
    url = f"{SITE}/guides/"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "Cape Cod Guides", "url": url,
           "description": "Researched, source-cited guides to Cape Cod — events, seasons, beaches, wildlife and travel planning.",
           "hasPart": [{"@type": "Article", "headline": m["title"], "url": f"{SITE}/guides/{m['slug']}/"} for m, _ in articles]}]
    cards = "".join(card(m) for m, _ in articles) or '<p class="muted">Guides are on the way.</p>'
    return (head("Cape Cod Guides — Researched, Source-Cited Local Guides | Totally Cape Cod",
                 "Cape Cod guides you can trust: events, seasons, beaches, wildlife and trip planning — every fact linked to its source.",
                 url, ld, og_type="website")
            + f"""<main class="g-wrap" style="max-width:1000px;">
<div class="g-crumbs"><a href="/">Home</a> › Guides</div>
<h1 class="g-title">Cape Cod Guides</h1>
<p class="g-dek">Local guides to Cape Cod's events, seasons, beaches and wildlife. Every fact is linked to the source it came from — <a href="/guides/standards/">here's how we check</a>.</p>
<div class="g-cards" style="margin-top:22px;">{cards}</div>
</main>
{FOOTER}
</body>
</html>
""")


def render_author(aid: str, a: dict, articles: list) -> str:
    url = f"{SITE}/authors/{aid}/"
    mine = [m for m, _ in articles if m["author"] == aid]
    ld = [{"@context": "https://schema.org", "@type": "ProfilePage", "url": url, "mainEntity": author_ld(aid, a)}]
    cards = "".join(card(m) for m in mine) or '<p class="muted">No guides yet.</p>'
    return (head(f'{a["name"]} — {a.get("job_title", "Author")} | Totally Cape Cod', a["bio"][:160], url, ld, og_type="profile")
            + f"""<main class="g-wrap">
<div class="g-crumbs"><a href="/">Home</a> › <a href="/guides/">Guides</a> › Authors</div>
<h1 class="g-title">{esc(a["name"])}</h1>
<p class="g-dek">{esc(a["bio"])}</p>
<h2 class="g-title" style="font-size:24px;margin-top:30px;">Guides by {esc(a["name"].split()[0])}</h2>
<div class="g-cards">{cards}</div>
</main>
{FOOTER}
</body>
</html>
""")


STANDARDS_MD = """
Totally Cape Cod publishes guides people use to plan real days on the Cape, so accuracy comes first. These are the rules every guide follows.

## Every fact has a source

Dates, times, prices, rules, seasons, counts and descriptions of places are linked to the source they came from, shown as numbered citations like this: [1]. The full list of sources sits at the bottom of each guide, with the date we checked it.

We prefer primary sources: the organizer's own listing for an event, the town, state or National Park Service for rules and seasons, and the business itself for hours.

## Credit where it's due

Events and photos are credited to the people and organizations behind them, with a link back to the original. We only use a photographer's work with their permission.

## How guides are made

Guides are researched with the help of AI tools. Before anything is published, each factual claim is checked against the text of its cited source; anything we can't confirm is cut, not guessed. Guides are updated when plans change — the "Updated" date shows the last check.

## When we get something wrong

Plans change and mistakes happen. If you spot something wrong or out of date, [tell us](/contact.html) and we'll correct it.

## Independence

Events, places and businesses are never included because someone paid for it.
"""


def render_standards() -> str:
    url = f"{SITE}/guides/standards/"
    body = markdown.markdown(STANDARDS_MD.strip()).replace(
        "[1]", '<sup class="cite">[1]</sup>')
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": "Editorial and fact-checking standards", "url": url,
           "publisher": publisher_ld()}]
    return (head("How We Fact-Check Our Cape Cod Guides | Totally Cape Cod",
                 "How Totally Cape Cod researches, sources, credits and corrects its Cape Cod guides.", url, ld, og_type="website")
            + f"""<main class="g-wrap">
<div class="g-crumbs"><a href="/">Home</a> › <a href="/guides/">Guides</a> › Standards</div>
<h1 class="g-title">How we fact-check</h1>
<article class="g-body">{body}</article>
</main>
{FOOTER}
</body>
</html>
""")


def render_rss(articles: list, authors: dict) -> str:
    items = []
    for m, _ in articles[:30]:
        link = f"{SITE}/guides/{m['slug']}/"
        pub = datetime.strptime(m["date"], "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items.append(f"<item><title>{xml_escape(m['title'])}</title><link>{link}</link><guid>{link}</guid>"
                     f"<pubDate>{pub}</pubDate><description>{xml_escape(m['description'])}</description>"
                     f"<author>noreply@totallycapecod.com ({xml_escape(authors[m['author']]['name'])})</author></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            f"<title>Totally Cape Cod Guides</title><link>{SITE}/guides/</link>"
            "<description>Researched, source-cited Cape Cod guides.</description><language>en-us</language>"
            + "".join(items) + "</channel></rss>\n")


# ----------------------------------------------------------------- sitemap ---
def git_lastmod(path: Path) -> str | None:
    try:
        shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip()
        if shallow == "true":
            return None
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", str(path)], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
        return out or None
    except Exception:
        return None


def build_sitemap(articles: list, authors: dict) -> str:
    sm = ROOT / "sitemap.xml"
    existing = []
    if sm.exists():
        for m in re.finditer(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?(?:\s*<changefreq>([^<]+)</changefreq>)?(?:\s*<priority>([^<]+)</priority>)?\s*</url>",
                             sm.read_text(encoding="utf-8")):
            existing.append(dict(loc=m.group(1), lastmod=m.group(2), changefreq=m.group(3), priority=m.group(4)))
    entries = {e["loc"]: e for e in existing if "/guides/" not in e["loc"] and "/authors/" not in e["loc"]}
    # static pages: refresh lastmod from git when history is available; pages edited in the
    # working tree (built locally before committing) get today's date
    try:
        dirty = set(re.findall(r"^.. (.+)$", subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                                               capture_output=True, text=True).stdout, re.M))
    except Exception:
        dirty = set()
    for loc, e in entries.items():
        rel = loc.replace(SITE + "/", "")
        fname = "app/index.html" if rel in ("", "app/") else rel
        f = ROOT / fname
        lm = git_lastmod(f) if f.exists() else None
        if fname in dirty:
            lm = date.today().isoformat()
        if lm:
            e["lastmod"] = lm
    newest = max([m["updated"] for m, _ in articles] or [date.today().isoformat()])
    entries[f"{SITE}/guides/"] = dict(loc=f"{SITE}/guides/", lastmod=newest, changefreq="weekly", priority="0.8")
    entries[f"{SITE}/guides/standards/"] = dict(loc=f"{SITE}/guides/standards/", lastmod="2026-10-26", changefreq="yearly", priority="0.3")
    for aid in authors:
        entries[f"{SITE}/authors/{aid}/"] = dict(loc=f"{SITE}/authors/{aid}/", lastmod=newest, changefreq="monthly", priority="0.4")
    for m, _ in articles:
        loc = f"{SITE}/guides/{m['slug']}/"
        entries[loc] = dict(loc=loc, lastmod=m["updated"], changefreq=m.get("changefreq", "weekly"), priority=str(m.get("priority", "0.8")))
    rows = []
    for e in entries.values():
        rows.append("  <url>\n    <loc>{}</loc>\n{}{}{}  </url>".format(
            e["loc"],
            f"    <lastmod>{e['lastmod']}</lastmod>\n" if e.get("lastmod") else "",
            f"    <changefreq>{e['changefreq']}</changefreq>\n" if e.get("changefreq") else "",
            f"    <priority>{e['priority']}</priority>\n" if e.get("priority") else ""))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


# -------------------------------------------------------------------- main ---
def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    return main_build(check_only="--check" in sys.argv)


def main_build(check_only: bool = False) -> int:
    authors = load_authors()
    articles = load_articles()
    errors = []
    for meta, body in articles:
        errors += validate(meta, body, authors)
    slugs = [m["slug"] for m, _ in articles]
    for s in set(slugs):
        if slugs.count(s) > 1:
            errors.append(f"duplicate slug: {s}")
    if errors:
        print("❌ Content validation failed:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    print(f"✓ {len(articles)} article(s) valid")
    if check_only:
        return 0
    for meta, body in articles:
        write(ROOT / "guides" / meta["slug"] / "index.html", render_article(meta, body, authors, articles))
    write(ROOT / "guides" / "index.html", render_hub(articles))
    write(ROOT / "guides" / "standards" / "index.html", render_standards())
    write(ROOT / "guides" / "feed.xml", render_rss(articles, authors))
    for aid, a in authors.items():
        write(ROOT / "authors" / aid / "index.html", render_author(aid, a, articles))
    write(ROOT / "sitemap.xml", build_sitemap(articles, authors))
    print(f"✓ built {len(articles)} guide page(s), hub, standards, RSS, author page(s), sitemap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
