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


EVIDENCE = CONTENT / "evidence"


def load_evidence(slug: str) -> dict:
    """Saved references for a guide: content/evidence/<slug>.json (see docs/CONTENT_PLAN.md)."""
    f = EVIDENCE / f"{slug}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {"_invalid": True}


def validate_evidence(meta: dict) -> list[str]:
    """Owner's rule: we're an intermediary — every source a guide cites must have saved,
    verbatim excerpts backing it, and no unresolved gaps, before the guide can be built."""
    slug = meta.get("slug", "?")
    ev = load_evidence(slug)
    if not ev:
        return [f"{slug}: no saved references — write content/evidence/{slug}.json"]
    if ev.get("_invalid"):
        return [f"{slug}: content/evidence/{slug}.json is not valid JSON"]
    errs = []
    by_id = {s.get("id"): s for s in ev.get("sources") or []}
    for s in meta.get("sources") or []:
        e = by_id.get(s.get("id"))
        if not e:
            errs.append(f"{slug}: source {s.get('id')} has no saved excerpts")
        elif str(e.get("url", "")).rstrip("/") != str(s.get("url", "")).rstrip("/"):
            errs.append(f"{slug}: saved excerpts for source {s.get('id')} point to a different url")
        elif not any(str(x.get("quote", "")).strip() for x in e.get("excerpts") or []):
            errs.append(f"{slug}: source {s.get('id')} has no excerpt text")
    for g in ev.get("gaps") or []:
        errs.append(f"{slug}: unresolved gap for source {g.get('source')}: {str(g.get('claim', ''))[:80]}")
    return errs


# --------------------------------------------------------------- rendering ---
def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def pretty_date(iso: str) -> str:
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return d.strftime("%B %-d, %Y")


def cite_html(text: str, slug: str, cite_base: str | None = None) -> str:
    """cite_base=None keeps the classic [n] markers linking to #src-n on the same page.
    A string (e.g. "/guides/<slug>/sources/") gives quiet superscripts linking to that page."""
    def rep(m):
        nums = [n.strip() for n in m.group(1).split(",")]
        if cite_base is not None:
            links = "".join(f'<a href="{cite_base}#src-{n}" aria-label="Source {n}">{n}</a>' for n in nums)
            return f'<sup class="cite cite-q">{links}</sup>'
        links = ",".join(f'<a href="#src-{n}" aria-label="Source {n}">{n}</a>' for n in nums)
        return f'<sup class="cite">[{links}]</sup>'
    return CITE_RE.sub(rep, text)


def md_to_html(md: str, slug: str, cite_base: str | None = None) -> str:
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
    out = cite_html(out, slug, cite_base)
    # external links open in a new tab, internal stay put
    out = re.sub(r'<a href="(https?://(?!totallycapecod\.com)[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', out)
    return out


NAV = ('<nav class="site-nav" id="siteNav"><div class="nav-inner"><a href="/" class="nav-logo">Totally Cape Cod</a>'
       '<div class="nav-links"><a href="/feed.html">📍 Near You</a><a href="/beaches.html">Beaches</a><a href="/eats.html">Eats</a>'
       '<a href="/stays.html">Stays</a><a href="/experiences.html">Experiences</a><a href="/events">Events</a><a href="/guides/">Guides</a><a href="/app/">📱 App</a></div>'
       '<button class="nav-mobile-toggle" type="button" aria-label="Menu" aria-controls="mobileMenu" onclick="toggleMobileMenu()">☰</button></div></nav>'
       '<div class="mobile-menu" id="mobileMenu" onclick="toggleMobileMenu()"><div class="mobile-menu-panel" onclick="event.stopPropagation()">'
       '<a href="/">Home</a><a href="/events">Events</a><a href="/beaches.html">Beaches</a><a href="/eats.html">Eats</a><a href="/stays.html">Stays</a><a href="/experiences.html">Experiences</a><a href="/feed.html">📍 Near You</a><a href="/itinerary.html">Plan a Trip</a><a href="/guides/">Guides</a><a href="/photos.html">Photos</a><a href="/about.html">About</a><a href="/app/">📱 Open the App</a></div></div>')

FOOTER = ('<footer class="site-footer"><div class="footer-inner"><div><div class="footer-brand">Totally Cape Cod</div>'
          '<p class="footer-desc">Cape Cod beaches, events and eats, linked to their sources.</p></div>'
          '<div class="footer-links"><div class="footer-heading">Explore</div><a href="/beaches.html">Beaches</a><a href="/eats.html">Restaurants</a>'
          '<a href="/events">Events</a><a href="/experiences.html">Experiences</a>'
          '<a href="/best-beaches-2026.html">Beaches by region</a><a href="/hidden-gems.html">Cape Cod detours</a><a href="/photos.html">Cape Cod photos</a></div>'
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
  .g-ev{margin:4px 0 2px;font-size:13px;}
  .g-ev summary{cursor:pointer;color:var(--text-secondary);}
  .g-ev ul{margin:6px 0;padding-left:18px;}
  .g-ev li{margin:4px 0;font-style:italic;}
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
  .g-toc{display:none;}
  @media(min-width:1260px){
    .g-toc{display:block;position:fixed;top:110px;left:calc(50% + 410px);width:210px;max-height:calc(100vh - 140px);overflow-y:auto;font-size:13.5px;line-height:1.4;border-left:2px solid var(--divider);padding-left:16px;}
    .g-toc-h{font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:10px;}
    .g-toc a{display:block;color:var(--text-secondary);text-decoration:none;padding:5px 0;}
    .g-toc a:hover{color:var(--warm-brown);}
    .g-body h2,.g-faq,.g-sources{scroll-margin-top:84px;}
  }
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


def article_ld(meta: dict, a: dict, url: str, sources: list, faq: list) -> list:
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
    return ld


def build_src_items(slug: str, sources: list) -> str:
    """The numbered reference <li>s (with saved evidence excerpts) used on article pages and sources pages."""
    ev_by_id = {e.get("id"): e for e in (load_evidence(slug).get("sources") or [])}

    def src_extra(s: dict) -> str:
        e = ev_by_id.get(s["id"]) or {}
        out = ""
        if e.get("archived"):
            out += f' · <a href="{esc(e["archived"])}" target="_blank" rel="noopener nofollow">archived copy</a>'
        quotes = [x for x in e.get("excerpts") or [] if str(x.get("quote", "")).strip()]
        if quotes:
            qs = "".join(f"<li>&ldquo;{esc(x['quote'].strip())}&rdquo;</li>" for x in quotes)
            via = f" ({esc(e['via'])})" if e.get("via") and e.get("via") != "live page" else ""
            out += (f'<details class="g-ev"><summary>What the source says</summary><ul>{qs}</ul>'
                    f'<p class="muted">Excerpts saved {esc(pretty_date(str(e.get("checked") or s["accessed"])))}{via}.</p></details>')
        return out

    return "".join(
        f'<li id="src-{s["id"]}">{esc(s["publisher"])}: <a href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s["title"])}</a>'
        f'{(" — " + esc(s["note"])) if s.get("note") else ""} <span class="muted">(accessed {esc(pretty_date(str(s["accessed"])))})</span>'
        f'{src_extra(s)}</li>'
        for s in sources)


def render_article(meta: dict, body: str, authors: dict, all_articles: list) -> str:
    slug = meta["slug"]
    if meta.get("layout") == "directory":
        return render_directory(meta, body, authors, all_articles)
    if (meta.get("layout") or "article") != "classic":
        return render_prose(meta, body, authors, all_articles)
    url = f"{SITE}/guides/{slug}/"
    a = authors[meta["author"]]
    sp = bool(meta.get("sources_page"))          # opt-in: references live on /guides/<slug>/sources/
    cb = f"/guides/{slug}/sources/" if sp else None
    body_html = md_to_html(body, slug, cb)
    # Desktop "On this page" sidebar, built from the article's H2s (ids come from the toc extension).
    heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body_html, flags=re.S)
    toc_html = ""
    if len(heads) >= 3:
        links = "".join(f'<a href="#{hid}">{re.sub(r"<[^>]+>", "", txt)}</a>' for hid, txt in heads)
        if meta.get("faq"):
            links += '<a href="#quick-answers">Quick answers</a>'
        links += '<a href="#sources">Sources</a>' if not sp else ""
        toc_html = f'<nav class="g-toc" aria-label="On this page"><div class="g-toc-h">On this page</div>{links}</nav>'
    sources = sorted(meta.get("sources") or [], key=lambda s: s["id"])
    faq = meta.get("faq") or []

    ld = article_ld(meta, a, url, sources, faq)

    updated = ""
    if meta["updated"] != meta["date"]:
        updated = f' · Updated <time datetime="{meta["updated"]}">{pretty_date(meta["updated"])}</time>'
    byline = (f'<div class="g-byline"><span>By <a href="/authors/{esc(meta["author"])}/" rel="author">{esc(a["name"])}</a></span>'
              f'<span>Published <time datetime="{meta["date"]}">{pretty_date(meta["date"])}</time>{updated}</span>'
              f'<span><a href="/guides/standards/">How we fact-check</a></span></div>')
    faq_html = ""
    if faq:
        items = "".join(f'<details><summary>{esc(q["q"])}</summary><p>{cite_html(markdown.markdown(q["a"])[3:-4], slug, cb)}</p></details>' for q in faq)
        faq_html = f'<section class="g-faq" id="quick-answers"><h2 class="g-title" style="font-size:26px;">Quick answers</h2>{items}</section>'
    src_items = build_src_items(slug, sources)
    sources_html = f'<section class="g-sources" id="sources"><h2>Sources</h2><ol>{src_items}</ol></section>'
    if sp:
        sources_html = f'<section class="g-sources" id="sources">{trust_box(meta, len(sources))}</section>'
    disclosure = meta.get("disclosure") or ("This guide was researched with the help of AI tools and checked line by line "
                                            "against the sources listed below before publishing.")
    if sp:
        disclosure = disclosure.replace("listed below", "listed on the sources page")
    related = [m for (m, _) in all_articles if m["slug"] != slug][:3]
    related_html = ""
    if related:
        related_html = f'<section class="g-related"><h2 class="g-title" style="font-size:24px;">More Cape Cod guides</h2><div class="g-cards">{"".join(card(m) for m in related)}</div></section>'
    needs_events = 'data-live-events' in body_html
    scripts = '<script src="/js/live-events.js" defer></script>' if needs_events else ""

    return (head(f'{meta.get("seo_title") or meta["title"]} | Totally Cape Cod', meta["description"], url, ld)
            + f"""{toc_html}<main class="g-wrap">
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
{sources_html}
{related_html}
</main>
{FOOTER}
{scripts}
</body>
</html>
""")


# ------------------------------------------------------------ live strip (guide-live.js) ---
# Optional front matter `towns: [Chatham, Orleans]` narrows the strip's events; directory guides
# derive their towns from the directory data. No towns means Cape-wide. Never used on `layout: classic`.
GL_CSS = """<style>
.gl{--paper:#FDF8F2;--ink:#4A4038;--mute:#625749;--navy:#1A3A6C;--kraft:#D4A574;--bay:#2F6B57;min-height:560px;margin:26px 0;padding:14px 0;border-top:2px dashed var(--kraft);border-bottom:2px dashed var(--kraft);font:16px/1.5 Inter,system-ui,sans-serif;color:var(--ink)}
.gl a{color:var(--navy)}.gl a:focus-visible{outline:3px solid var(--navy);outline-offset:2px;border-radius:4px}
.gl-static{margin:0}.gl-static a,.gl-all a,.gl-go{display:inline-flex;align-items:center;min-height:44px}
.gl-cols{display:flex;flex-direction:column}
.gl-col{padding:12px 0}.gl-col+.gl-col{border-top:2px dashed var(--kraft)}
.gl h3{font:800 19px/1.2 Fraunces,Georgia,serif;color:var(--navy);margin:0 0 8px}
.gl ul{list-style:none;margin:0;padding:0}
.gl p{margin:0}.gl-m{font-size:15px;color:var(--mute);margin:0 0 4px!important}
.gl a.gl-ev{display:block;min-height:44px;padding:4px 0;text-decoration:none}.ga-body>.gl{max-width:none}.gl-ev b{display:block;font-weight:600;text-decoration:underline;text-underline-offset:2px}
.gl-ev span{display:block;font-size:15px;color:var(--mute)}.gl-ev .gl-src{font-size:14px}
.gl-row{margin:0 0 2px}.gl-dim .gl-row,.gl-dim .gl-m{color:#766A5C}.gl-dim .gl-row b{font-weight:500}
.gl-all{margin:6px 0 0}
@media(min-width:700px){.gl{min-height:330px}.gl-cols{flex-direction:row;gap:0}.gl-col{flex:1 1 0;min-width:0;padding:6px 18px}.gl-col:first-child{padding-left:0;flex-grow:1.3}.gl-col:last-child{padding-right:0}.gl-col+.gl-col{border-top:0;border-left:2px dashed var(--kraft)}}
</style>
<noscript><style>.gl{min-height:0!important}</style></noscript>"""


def live_strip(meta: dict, towns: list | None = None) -> str:
    """The 'live strip' section: one static line that /js/guide-live.js replaces when data is available."""
    towns = [str(t) for t in (towns if towns is not None else (meta.get("towns") or []))]
    return (GL_CSS + f'<section class="gl" data-gl data-towns="{esc(json.dumps(towns))}" aria-label="Happening now on Cape Cod">'
            '<p class="gl-static">See <a href="/events">what is on this week</a> or check <a href="/cape-cod-bridge-traffic.html">bridge traffic</a>.</p>'
            '</section><script src="/js/guide-live.js" defer></script>')


def insert_live_strip(body_html: str, meta: dict) -> str:
    """Put the strip after the introduction: just before the first H2 of the body."""
    i = body_html.find("<h2")
    strip = live_strip(meta)
    return body_html + strip if i < 0 else body_html[:i] + strip + body_html[i:]


# ------------------------------------------------- directory layout + sources page ---
# Opt-in per article through front matter: `layout: directory` (needs content/directories/<slug>.json),
# `sources_page: true` (references move to /guides/<slug>/sources/). Other articles never touch this code.
DIRECTORIES = CONTENT / "directories"
KIND_ICON = {"candy": "candy", "gift shop": "gift", "candles": "candle", "jewelry": "ring", "pottery": "vase",
             "books": "book", "museum shop": "museum", "toys and kids": "blocks", "food": "wedge",
             "home and garden": "house", "other": "bag"}
KIND_GROUP = {"candy": ("candy", "Candy and sweets"), "gift shop": ("gifts", "Gifts and home"),
              "home and garden": ("gifts", "Gifts and home"), "candles": ("makers", "Makers and studios"),
              "jewelry": ("makers", "Makers and studios"), "pottery": ("makers", "Makers and studios")}
STATUS = {"hours_dated": ("Hours posted", "posted", "posted"), "hours_undated": ("Hours posted, no date given", "posted", "nodate"),
          "call": ("No hours published: call ahead", "call", "call"), "reopens": ("Reopens November 27", "call", "reopens")}
ICONS = {
    "candy": '<circle cx="12" cy="12" r="4"/><path d="M8.6 9.6 4 7v10l4.6-2.6M15.4 9.6 20 7v10l-4.6-2.6"/>',
    "gift": '<rect x="4" y="10" width="16" height="10" rx="1"/><path d="M3 7h18v3H3zM12 7v13M12 7C10 4 7 4 7 6s3 1 5 1zM12 7c2-3 5-3 5-1s-3 1-5 1z"/>',
    "candle": '<rect x="8" y="11" width="8" height="10" rx="1"/><path d="M12 3c2 2.5 2 4 0 5-2-1-2-2.5 0-5zM12 8v3"/>',
    "ring": '<circle cx="12" cy="15" r="5"/><path d="m9 7 3-4 3 4-3 3z"/>',
    "vase": '<path d="M9 3h6M10 3v4c-3 2-4 5-4 8a6 6 0 0 0 12 0c0-3-1-6-4-8V3"/>',
    "book": '<path d="M5 3h14v15H7a2 2 0 0 0-2 2zM5 20a2 2 0 0 0 2 1h12M9 7h6"/>',
    "museum": '<path d="m3 9 9-5 9 5zM5 9v8M9.5 9v8M14.5 9v8M19 9v8M3 20h18"/>',
    "blocks": '<rect x="3" y="13" width="8" height="8"/><rect x="13" y="13" width="8" height="8"/><rect x="8" y="4" width="8" height="8"/>',
    "wedge": '<path d="M3 18V9l18-4v13zM3 9l18 4"/>',
    "house": '<path d="m4 11 8-7 8 7M6 10v10h12V10M10 20v-5h4v5"/>',
    "bag": '<path d="M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2"/>',
    "heart": '<path d="M12 20S5 15.6 5 10a4 4 0 0 1 7-2.600A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
    "pin": '<path d="M12 21s-6-5.5-6-10a6 6 0 0 1 12 0c0 4.5-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>',
    "phone": '<path d="M5 4h4l2 5-2.5 1.500a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    "share": '<path d="M12 15V4M8 8l4-4 4 4M5 13v6h14v-6"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 3 3 5-6"/>',
}
SPRITE = ('<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>'
          + "".join(f'<symbol id="i-{k}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{v}</symbol>' for k, v in ICONS.items())
          + "</defs></svg>")


def icon(name: str, cls: str = "gd-i") -> str:
    return f'<svg class="{cls}" width="22" height="22" aria-hidden="true" focusable="false"><use href="#i-{name}"/></svg>'


def load_directory(slug: str) -> dict:
    f = DIRECTORIES / f"{slug}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def split_body(body: str) -> tuple[str, list]:
    parts = re.split(r"(?m)^## ", body)
    secs = []
    for p in parts[1:]:
        title, _, rest = p.partition("\n")
        secs.append((title.strip(), rest.strip()))
    return parts[0].strip(), secs


def split_shops(rest: str) -> list:
    """[(shop name, shop paragraph markdown, [aside markdown])] for one town section."""
    out = []
    for c in re.split(r"(?m)^### ", rest)[1:]:
        name, _, txt = c.partition("\n")
        paras = [x.strip() for x in re.split(r"\n\s*\n", txt.strip()) if x.strip()]
        main, asides = [], []
        for i, x in enumerate(paras):
            if i > 0 and x.endswith("<!-- nocite -->") and not CITE_RE.search(x):
                asides.append(x.replace("<!-- nocite -->", "").strip())
            else:
                main.append(x)
        out.append((name.strip(), "\n\n".join(main), asides))
    return out


def validate_directory(meta: dict, body: str) -> list[str]:
    slug = meta.get("slug", "?")
    if meta.get("layout") != "directory":
        return []
    d = (load_directory(slug).get("shops") or [])
    if not d:
        return [f"{slug}: layout 'directory' needs content/directories/{slug}.json"]
    _, secs = split_body(body)
    want = [(t, n) for t, rest in secs if "### " in rest for n, _, _ in split_shops(rest)]
    have = [(e.get("town"), e.get("name")) for e in d]
    errs = []
    if want != have:
        errs.append(f"{slug}: directory shops do not match the article's shop headings in order")
    for e in d:
        if e.get("status") not in STATUS:
            errs.append(f"{slug}: {e.get('name')}: unknown status {e.get('status')!r}")
        if e.get("kind") not in KIND_ICON:
            errs.append(f"{slug}: {e.get('name')}: unknown kind {e.get('kind')!r}")
        if not e.get("anchor") or not e.get("address") or not e.get("state_text"):
            errs.append(f"{slug}: {e.get('name')}: missing anchor, address or state_text")
        if not e.get("hours_line") and e.get("status") not in ("call",):
            errs.append(f"{slug}: {e.get('name')}: hours_line is empty but hours are posted")
    return errs


def trust_box(meta: dict, n_sources: int, with_icon: bool = False, default_line: bool = False, cls: str = "gd-trust") -> str:
    slug = meta["slug"]
    line = meta.get("trust_line") or (f"Last checked {pretty_date(str(meta['updated']))}." if default_line else None)
    lead = f"<strong>{esc(line)}</strong> " if line else ""
    ic = icon("check", "gd-i gd-tick") if with_icon else ""
    return (f'<div class="{cls}">{ic}<p>{lead}{n_sources} sources back this page. '
            f'<a href="/guides/{esc(slug)}/sources/">See sources and how we checked</a></p></div>')


def render_sources_page(meta: dict, body: str, authors: dict) -> str:
    slug = meta["slug"]
    url = f"{SITE}/guides/{slug}/sources/"
    main_url = f"{SITE}/guides/{slug}/"
    sources = sorted(meta.get("sources") or [], key=lambda s: s["id"])
    _, secs = split_body(body)
    method = [(t, r) for t, r in secs if t in METHOD_TITLES]
    method_html = "".join(md_to_html(f"## {t}\n\n{r}", slug) for t, r in method)
    disclosure = (meta.get("disclosure") or ("This guide was researched with the help of AI tools and checked line by line "
                  "against the sources listed below before publishing.")).replace("listed below", "listed on this page")
    title = f"Sources and method: {meta['title']}"
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url,
           "isPartOf": main_url, "publisher": publisher_ld()},
          {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
              {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
              {"@type": "ListItem", "position": 2, "name": "Guides", "item": SITE + "/guides/"},
              {"@type": "ListItem", "position": 3, "name": meta["title"], "item": main_url},
              {"@type": "ListItem", "position": 4, "name": "Sources and method", "item": url}]}]
    return (head(f"{title} | Totally Cape Cod",
                 "The method, the numbered sources and the saved excerpts behind this guide.", url, ld, og_type="website", extra=SRC_CSS)
            + f"""<main class="g-wrap">
<div class="g-crumbs"><a href="/">Home</a> › <a href="/guides/">Guides</a> › <a href="/guides/{esc(slug)}/">{esc(meta.get("kicker") or "Guide")}</a> › Sources</div>
<h1 class="g-title">Sources and method</h1>
<p class="g-dek">This page holds {"how the list was made, " if method else ""}the numbered sources and the saved excerpts behind <a href="/guides/{esc(slug)}/">{esc(meta["title"])}</a>.</p>
<p><a href="/guides/{esc(slug)}/">Back to the guide</a><br><a href="/guides/standards/">How we fact-check</a></p>
{('<article class="g-body">' + chr(10) + method_html + chr(10) + '</article>') if method_html else ""}
<section class="g-sources" id="sources"><h2>Sources</h2><ol>{build_src_items(slug, sources)}</ol></section>
<div class="g-note">📝 {esc(disclosure)} Spot something out of date? <a href="/contact.html">Tell us</a> and we'll fix it.</div>
<p><a href="/guides/{esc(slug)}/">Back to the guide</a><br><a href="/guides/standards/">Read our editorial and fact-checking standards</a></p>
</main>
{FOOTER}
</body>
</html>
""")


SRC_CSS = """<style>
.g-wrap a{color:#245F78}.g-wrap a:focus-visible,.g-wrap summary:focus-visible{outline:3px solid #1A3A6C;outline-offset:2px;border-radius:4px}
.g-sources{font-size:16px;line-height:1.6}.g-sources li{margin:10px 0}.g-ev{font-size:15px}.g-ev summary{display:flex;align-items:center;min-height:44px}
.g-body{line-height:1.7}.g-body li{margin:8px 0}.g-body,.g-dek{max-width:42rem}
</style>
"""

DIR_CSS = """<style>
.gd{--paper:#FDF8F2;--ink:#4A4038;--mute:#625749;--navy:#1A3A6C;--kraft:#D4A574;--kraftd:#9A6F3C;--sand:#F5E6D3;--tagbg:#EBD3AD;--cran:#9E2A3F;--bay:#2F6B57;--line:#E4D6C2;max-width:1120px;margin:0 auto;padding:78px 18px 56px;font-size:17px;line-height:1.6;color:var(--ink)}
.gd [hidden]{display:none!important}
.gd a{color:var(--navy)}
.gd a:focus-visible,.gd button:focus-visible,.gd summary:focus-visible{outline:3px solid var(--navy);outline-offset:2px;border-radius:6px}
.gd h1,.gd h2,.gd h3{font-family:'Fraunces',Georgia,serif;color:var(--navy);margin:0}
.gd .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.gd-i{flex:none;display:block}
.gd-crumbs{font-size:15px;color:var(--mute);margin-bottom:10px}
.gd-hero{display:grid;gap:18px;background:var(--sand);border-radius:20px;padding:22px 20px 24px}
.gd-hero h1{font-weight:900;line-height:1.02;letter-spacing:-.015em}
.gd-t1{display:block;font-size:clamp(34px,9vw,56px)}
.gd-t2{display:block;font-weight:400;font-size:clamp(19px,4.6vw,26px);line-height:1.2;margin-top:10px;letter-spacing:0}
.gd-hero .dek{font-size:18px;line-height:1.5;margin:14px 0 8px;max-width:34rem}
.gd-hero .chk{margin:0;font-size:16px;color:var(--mute)}
.gd-fig{margin:0}
.gd-fig img{width:100%;height:auto;aspect-ratio:16/9;object-fit:cover;border-radius:12px;background:#D9C8B0}
.gd-fig figcaption{font-size:15px;line-height:1.45;color:var(--mute);margin-top:7px}
.gd-twine ul{display:flex;flex-wrap:wrap;gap:0 14px;list-style:none;margin:0;padding:0}
.gd-twine li{position:relative;padding-top:24px;margin-bottom:6px}
.gd-twine li::before{content:"";position:absolute;top:0;left:-7px;right:-7px;height:2px;background:var(--kraftd);border-radius:1px}
.gd-hero .gd-twine ul{overflow-x:clip}
.gd-hero .gd-twine li::before{left:-100vw;right:-100vw;border-radius:0}
.gd-twine li:nth-child(odd){--tilt:-1.6deg}.gd-twine li:nth-child(even){--tilt:1.4deg}
.gd-tag{position:relative;display:block;text-decoration:none;transform-origin:50% -24px;transform:rotate(var(--tilt))}
.gd-tag::before{content:"";position:absolute;left:50%;top:-24px;height:24px;border-left:1.5px solid var(--kraftd)}
.gd-face{display:block;min-width:96px;padding:20px 14px 9px;background:var(--tagbg);color:var(--ink);clip-path:polygon(13px 0,calc(100% - 13px) 0,100% 13px,100% 100%,0 100%,0 13px);position:relative;line-height:1.2}
.gd-face::before{content:"";position:absolute;top:7px;left:50%;width:8px;height:8px;margin-left:-4px;border-radius:50%;background:var(--sand);box-shadow:inset 0 0 0 1.5px var(--kraftd)}
.gd-face strong{display:block;font:800 18px/1.15 'Fraunces',Georgia,serif;color:var(--navy)}
.gd-face span.n{font-size:15px;font-weight:600}
.gd-mark{position:absolute;top:-9px;right:-9px;z-index:2;min-width:24px;height:24px;padding:0 6px;border-radius:12px;background:var(--cran);color:#fff;font:700 14px/24px 'Inter',sans-serif;text-align:center}
.gd-trust{display:flex;gap:12px;align-items:flex-start;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:14px 0;margin:22px 0;font-size:17px;line-height:1.5}
.gd-trust p{margin:0}.gd-tick{margin-top:2px;color:var(--bay)}
.gd-prose{max-width:35rem}
.gd-prose p,.gd-prose li{margin:0 0 14px}.gd-prose ul{padding-left:22px}
.gd-prose h2,.gd-faq h2,.gd-plan h2{font-weight:900;font-size:30px;line-height:1.1;margin:0 0 12px}
.gd-prose a{text-decoration:underline;text-underline-offset:2px}
.gd-aside{font-family:'Fraunces',Georgia,serif;font-style:italic;color:var(--mute);border-left:1px solid var(--kraftd);padding:2px 0 2px 14px;margin:20px 0 0;max-width:35rem;font-size:18px;line-height:1.5}
.gd-shared{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin:0 0 18px;padding:12px 0;border-top:2px solid var(--cran);border-bottom:1px solid var(--line)}
.gd-shared p{margin:0;font-weight:600}
.gd-layout{margin-top:26px}
.gd-rail{display:none}
.gd-jump{position:sticky;top:73px;z-index:40;display:flex;align-items:center;gap:6px;background:var(--paper);border-bottom:1px solid var(--line);margin:0 -18px;padding:0 18px}
.gd-jump .lbl{flex:none;font-size:15px;color:var(--mute);padding-right:4px}
.gd-jump ul{display:flex;gap:2px;list-style:none;margin:0;padding:0;overflow-x:auto;scrollbar-width:thin}
.gd-jump a{display:flex;align-items:center;min-height:44px;padding:0 12px;white-space:nowrap;font-weight:600;font-size:16px;text-decoration:none;color:var(--ink);border-bottom:3px solid transparent}
.gd-jump a:hover{border-bottom-color:var(--navy)}
.gd-filters{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 6px;scroll-margin-top:130px}
.gd-chip{min-height:44px;padding:0 16px;border-radius:22px;border:1.5px solid var(--kraftd);background:#fff;color:var(--ink);font:600 16px/1 'Inter',sans-serif;cursor:pointer}
.gd-chip[aria-pressed=true]{background:var(--navy);border-color:var(--navy);color:#fff}
.gd-count{margin:0 0 4px;font-size:15px;color:var(--mute)}
.gd-empty{margin:18px 0;max-width:35rem;font-weight:600}
.gd-town{padding-top:30px;scroll-margin-top:130px}
.gd-town>h2{display:flex;align-items:baseline;gap:12px;font-weight:900;font-size:30px;line-height:1.1;margin-bottom:4px}
.gd-town>h2 small{font:600 15px 'Inter',sans-serif;color:var(--mute)}
.gd-shop{padding:20px 0;border-bottom:2px dashed var(--kraft);max-width:38rem;scroll-margin-top:130px}
.gd-shop:target{background:linear-gradient(90deg,rgba(212,165,116,.18),transparent)}
.gd-st{display:flex;align-items:flex-start;gap:10px}
.gd-st h3{flex:1;font-weight:800;font-size:22px;line-height:1.2;padding-top:3px}
.gd-st .gd-i{margin-top:5px;color:var(--kraftd)}
.gd-save{flex:none;display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 12px;border:1.5px solid var(--kraftd);border-radius:22px;background:#fff;color:var(--ink);font:600 15px/1 'Inter',sans-serif;cursor:pointer}
.gd-save[aria-pressed=true]{color:var(--cran);border-color:var(--cran);background:#FBEDEF}
.gd-save[aria-pressed=true] svg{fill:var(--cran)}
.gd-shop p{margin:0}
.gd-addr{margin-top:4px!important;font-size:17px}
.gd-addr em{display:block;font-style:normal;font-size:15px;color:var(--mute)}
.gd-quote{margin-top:8px!important;font-family:'Fraunces',Georgia,serif;font-style:italic;font-size:18px;line-height:1.45}
.gd-hours{margin-top:12px;border-left:3px solid var(--bar,#9A6F3C);padding-left:12px}
.gd-hl{font-weight:600;line-height:1.4}
.gd-state{font-size:15px;color:var(--sc,var(--mute))}
.s-posted{--bar:#2F6B57;--sc:#2F6B57}.s-nodate{--bar:#2F6B57;--sc:#2F6B57}.s-call{--bar:#9A6F3C;--sc:#625749}.s-reopens{--bar:#9E2A3F;--sc:#9E2A3F}
.s-nodate .gd-state,.s-reopens .gd-state{font-weight:600}
.gd-last{margin-top:8px!important;font-size:15px;color:var(--mute)}
.gd-act{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.gd-btn{display:inline-flex;align-items:center;gap:7px;min-height:44px;padding:0 14px;border:1.5px solid var(--navy);border-radius:22px;color:var(--navy);font:600 16px/1 'Inter',sans-serif;text-decoration:none;background:#fff;cursor:pointer}
.gd-btn:hover{background:var(--sand)}
.gd-full summary{display:flex;align-items:center;min-height:44px;margin-top:4px;font-weight:600;color:var(--navy);cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.gd-full>div{font-size:17px;line-height:1.6;padding:2px 0 6px}.gd-full>div p{margin:0}
sup.cite-q{font-size:.68em;line-height:0;margin-left:1px;white-space:nowrap}
sup.cite-q a{position:relative;color:#566A75;text-decoration:none;font-weight:600}
sup.cite-q a+a::before{content:","}
sup.cite-q a::after{content:"";position:absolute;inset:-14px -4px}
sup.cite-q a:hover{color:var(--navy);text-decoration:underline}
.gd-more{margin:34px 0 8px}
.gd-more>summary{display:inline-flex;align-items:center;min-height:48px;padding:0 18px;border:1.5px solid var(--navy);border-radius:24px;font-weight:600;color:var(--navy);cursor:pointer}
.gd-scroll{overflow-x:auto;margin-top:12px}
.gd-glance{font-weight:900;font-size:24px;margin:0 0 8px}
.gd-scroll table{border-collapse:collapse;font-size:15px;line-height:1.45;min-width:640px;width:100%}
.gd-scroll th,.gd-scroll td{text-align:left;padding:9px 10px;border-bottom:1px dashed var(--kraft);vertical-align:top}
.gd-scroll th{background:var(--sand)}
.gd-faq{margin-top:40px;max-width:35rem}
.gd-faq details{border-bottom:1px dashed var(--kraft);padding:4px 0}
.gd-faq summary{display:flex;align-items:center;min-height:48px;font-weight:600;color:var(--navy);cursor:pointer}
.gd-faq p{margin:4px 0 12px}
.gd-end{margin-top:34px}
.gd-plan{margin-top:38px}
.gd-share{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:16px}
.gd-share span{font-size:15px;color:var(--mute)}
.gd-note{font-size:15px;line-height:1.55;border-top:1px solid var(--line);padding-top:14px;margin:28px 0 0;color:var(--mute);max-width:35rem}
.gd-note a{color:var(--navy)}
.gd-bar{position:fixed;left:0;right:0;bottom:0;z-index:60;background:#fff;border-top:2px solid var(--cran);padding:8px 14px calc(8px + env(safe-area-inset-bottom))}
.gd-bar p{margin:0 0 6px;font-size:16px;line-height:1.35}
.gd-bar strong{color:var(--cran)}
.gd-barb{display:flex;flex-wrap:wrap;gap:6px}
.gd-barb .gd-btn{font-size:15px;padding:0 11px;border-color:var(--cran);color:var(--cran)}
.gd-baron body{padding-bottom:116px}
@media(min-width:1000px){
 .gd-hero{grid-template-columns:1fr 330px;grid-template-areas:"tx fg" "tw fg";gap:18px 36px;padding:34px 36px 30px;align-items:start}
 .gd-hero>div{grid-area:tx}.gd-hero .gd-twine{grid-area:tw}.gd-fig{grid-area:fg}.gd-fig img{aspect-ratio:4/5}
 .gd-layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:0 48px;align-items:start}
 .gd-rail{display:block;position:sticky;top:84px;padding-top:30px}
 .gd-jump{display:none}
 .gd-rail ul{list-style:none;margin:0;padding:0 0 0 14px;position:relative}
 .gd-rail ul::before{content:"";position:absolute;left:14px;top:-6px;bottom:6px;width:2px;background:var(--kraftd)}
 .gd-rail li{position:relative;padding:0 0 8px 22px}
 .gd-rail li::before{content:"";position:absolute;left:0;top:23px;width:22px;height:0;border-top:1.5px solid var(--kraftd)}
 .gd-rail .gd-tag{transform-origin:0 50%;transform:rotate(var(--rt,-1deg))}
 .gd-rail li:nth-child(even){--rt:1deg}
 .gd-rail .gd-tag::before{display:none}
 .gd-rail .gd-face{min-width:0;padding:11px 14px 11px 24px;clip-path:polygon(13px 0,100% 0,100% 100%,13px 100%,0 50%);display:flex;align-items:baseline;justify-content:space-between;gap:10px}
 .gd-rail .gd-face::before{top:50%;left:10px;margin:-4px 0 0}
 .gd-rail .gd-face strong{display:inline;font-size:17px}
 .gd-rail .gd-mark{top:-2px;right:-8px}
 .gd-railsum{margin:14px 0 0;font-weight:600;color:var(--cran);font-size:16px}
}
@media(max-width:999px){.gd-jump{top:61px}}
@media(max-width:768px){.gd-jump{top:73px}}
@media(max-width:480px){.gd-face{min-width:0;padding:18px 8px 7px}.gd-face strong{font-size:15px}.gd-face span.n{font-size:14px}.gd-twine ul{gap:0 9px}.gd-twine li{padding-top:20px}.gd-tag{transform-origin:50% -20px}.gd-tag::before{top:-20px;height:20px}.gd-fig img{aspect-ratio:21/9}.gd{padding-left:14px;padding-right:14px}.gd-jump{margin-left:-14px;margin-right:-14px;padding:0 14px}.gd-hero{padding:18px 16px 20px}}
@media(prefers-reduced-motion:no-preference){
 @keyframes gd-settle{from{transform:rotate(calc(var(--tilt)*-5))}55%{transform:rotate(calc(var(--tilt)*2))}to{transform:rotate(var(--tilt))}}
 .gd-hero .gd-tag{animation:gd-settle .9s ease-out both;animation-delay:calc(var(--i)*40ms)}
 .gd-chip,.gd-save{transition:background-color .12s,color .12s,border-color .12s}
}
</style>
"""

DIR_JS = """<script>
(function(){var d=document,root=d.documentElement,KEY='tcc-gift-shops-2026-list',saved=[],shared=[],cur='all';
try{saved=JSON.parse(localStorage.getItem(KEY)||'[]')||[]}catch(e){saved=[]}
if(!Array.isArray(saved))saved=[];
function $(s,r){return[].slice.call((r||d).querySelectorAll(s))}
var cards=$('.gd-shop'),ids=cards.map(function(c){return c.id});
saved=saved.filter(function(i){return ids.indexOf(i)>-1});
function store(){try{localStorage.setItem(KEY,JSON.stringify(saved))}catch(e){}}
function inOrder(l){return cards.filter(function(c){return l.indexOf(c.id)>-1})}
function match(c){if(cur==='all')return true;if(cur==='saved')return saved.indexOf(c.id)>-1;if(cur==='shared')return shared.indexOf(c.id)>-1;return c.dataset.hours===cur||c.dataset.group===cur}
var f=d.getElementById('gd-filters'),cnt=d.getElementById('gd-count'),empty=d.getElementById('gd-empty'),bar=d.getElementById('gd-bar'),bt=d.getElementById('gd-bartext'),lim=d.getElementById('gd-maplimit'),msg=d.getElementById('gd-barmsg'),map=d.getElementById('gd-map'),rs=d.getElementById('gd-railsum');
function enc(s){return encodeURIComponent(s)}
function mapsUrl(){var l=inOrder(saved).slice(0,10);if(!l.length)return'';var last=l[l.length-1],w=l.slice(0,-1).map(function(c){return enc(c.dataset.q)});
return'https://www.google.com/maps/dir/?api=1&destination='+enc(last.dataset.q)+(w.length?'&waypoints='+w.join('%7C'):'')}
function listUrl(){var c=d.querySelector('link[rel=canonical]');return(c?c.href:location.href.split('#')[0])+'#list='+inOrder(saved).map(function(x){return x.id}).join(',')}
function paint(){var n=0,s=saved.length;
cards.forEach(function(c){var v=match(c);c.hidden=!v;if(v)n++;var b=$('.gd-save',c)[0];if(b){var on=saved.indexOf(c.id)>-1;b.setAttribute('aria-pressed',on);b.lastElementChild.textContent=on?'On my list':'Add to my list'}});
$('.gd-town').forEach(function(t){var any=$('.gd-shop',t).some(function(c){return!c.hidden});t.hidden=!any;
$('.gd-jump a[href="#'+t.id+'"],.gd-rail a[href="#'+t.id+'"]').forEach(function(a){a.parentNode.hidden=!any})});
$('.gd-mark').forEach(function(m){var k=cards.filter(function(c){return c.dataset.town===m.dataset.town&&saved.indexOf(c.id)>-1}).length;m.hidden=!k;m.firstChild.nodeValue=k});
$('.gd-chip').forEach(function(b){b.setAttribute('aria-pressed',b.dataset.f===cur)});
cnt.textContent='Showing '+n+' of '+cards.length+' shops';
empty.hidden=!(cur==='saved'&&!s);
var t='My list: '+s+(s===1?' shop':' shops');bt.textContent=t;rs.textContent=t;rs.hidden=!s;bar.hidden=!s;root.classList.toggle('gd-baron',!!s);
if(s)map.href=mapsUrl();lim.textContent=s>10?'Maps shows the first 10 of '+s+' shops.':''}
f.hidden=false;cnt.hidden=false;
$('.gd-chip').forEach(function(b){b.addEventListener('click',function(){cur=b.dataset.f;paint()})});
$('.gd-save').forEach(function(b){b.hidden=false;b.addEventListener('click',function(){var id=b.closest('.gd-shop').id,i=saved.indexOf(id);if(i>-1)saved.splice(i,1);else saved.push(id);store();paint()})});
function toList(){cur='saved';paint();f.scrollIntoView()}
d.getElementById('gd-show').addEventListener('click',toList);
d.getElementById('gd-listshare').addEventListener('click',function(){var u=listUrl();
function say(t){msg.textContent=t}
if(navigator.share){navigator.share({title:'My Cape Cod gift shop list',url:u}).catch(function(){})}
else if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(u).then(function(){say('Link copied')},function(){say('Copy this link: '+u)})}
else say('Copy this link: '+u)});
var m=/^#list=([a-z0-9,-]+)$/.exec(location.hash),sn=d.getElementById('gd-shared');
if(m){shared=m[1].split(',').filter(function(i){return ids.indexOf(i)>-1});
if(shared.length){d.getElementById('gd-sharedtext').textContent='Someone shared a list with you: '+shared.length+(shared.length===1?' shop':' shops');sn.hidden=false;
d.getElementById('gd-sshow').addEventListener('click',function(){cur='shared';paint();f.scrollIntoView()});
d.getElementById('gd-sadd').addEventListener('click',function(){shared.forEach(function(i){if(saved.indexOf(i)<0)saved.push(i)});store();sn.hidden=true;toList()})}}
paint();
var sb=d.getElementById('gd-share'),sm=d.getElementById('gd-sharemsg');
if(sb){sb.hidden=false;sb.addEventListener('click',function(){var c=d.querySelector('link[rel=canonical]'),u=c?c.href:location.href.split('#')[0];
function say(t){sm.textContent=t}
if(navigator.share){navigator.share({title:d.title,url:u}).catch(function(){})}
else if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(u).then(function(){say('Link copied')},function(){say('Copy this link: '+u)})}
else say('Copy this link: '+u)})}
})();
</script>"""


def render_directory(meta: dict, body: str, authors: dict, all_articles: list) -> str:
    from urllib.parse import quote
    slug = meta["slug"]
    url = f"{SITE}/guides/{slug}/"
    a = authors[meta["author"]]
    sources = sorted(meta.get("sources") or [], key=lambda s: s["id"])
    faq = meta.get("faq") or []
    cb = f"/guides/{slug}/sources/"
    shops = {e["name"]: e for e in load_directory(slug)["shops"]}
    intro, secs = split_body(body)
    towns = []                       # (town, [(name, para_md, asides)])
    glance_md, after = "", []        # sections other than method / glance / towns
    for title, rest in secs:
        if "### " in rest:
            towns.append((title, split_shops(rest)))
        elif title == "At a glance":
            glance_md = rest
        elif title != "How this list was made":
            after.append((title, rest))
    n_shops = sum(len(sh) for _, sh in towns)

    gcount: dict = {}
    for e in shops.values():
        g = KIND_GROUP.get(e["kind"])
        if g:
            gcount[g] = gcount.get(g, 0) + 1
    groups = [g for g, n in gcount.items() if n >= 3]

    def tid(t):
        return "town-" + re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")

    def shop_html(name, para_md, e):
        _, hours_f, cls = STATUS[e["status"]]
        g = KIND_GROUP.get(e["kind"])
        qtext = f'{e["name"]} {e["address"]}'
        q = quote(qtext, safe="")
        phone = e.get("phone")
        digits = re.sub(r"\D", "", phone or "")
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        act = (f'<a class="gd-btn" href="https://www.google.com/maps/search/?api=1&amp;query={q}" target="_blank" rel="noopener">'
               f'{icon("pin")}Directions<span class="sr"> to {esc(name)}</span></a>')
        if phone:
            act += f'<a class="gd-btn" href="tel:{digits}">{icon("phone")}Call {esc(phone)}<span class="sr"> {esc(name)}</span></a>'
        if e.get("latest_activity"):
            last = f'<p class="gd-last">Latest activity: {esc(pretty_date(e["latest_activity"]))}</p>'
        elif e.get("activity_note"):
            last = f'<p class="gd-last">{esc(e["activity_note"])}</p>'
        else:
            last = ""
        quote_html = f'<p class="gd-quote">&ldquo;{esc(e["sells_quote"])}&rdquo;</p>' if e.get("sells_quote") else ""
        note = f'<em>{esc(e["address_note"])}</em>' if e.get("address_note") else ""
        hl = f'<p class="gd-hl">{esc(e["hours_line"])}</p>' if e.get("hours_line") else ""
        full = md_to_html(para_md, slug, cb)
        grp = f' data-group="{g[0]}"' if g else ""
        return (f'<article class="gd-shop" id="{esc(e["anchor"])}" data-hours="{hours_f}" data-town="{tid(e["town"])}" data-q="{esc(qtext)}"{grp}>'
                f'<div class="gd-st">{icon(KIND_ICON[e["kind"]])}<h3>{esc(name)}</h3>'
                f'<button class="gd-save" type="button" aria-pressed="false" aria-label="Add to my list: {esc(name)}" hidden>{icon("heart")}<span>Add to my list</span></button></div>'
                f'<p class="gd-addr">{esc(e["address"])}{note}</p>'
                f'{quote_html}'
                f'<div class="gd-hours s-{cls}">{hl}<p class="gd-state">{esc(e["state_text"])}</p></div>'
                f'{last}'
                f'<div class="gd-act">{act}</div>'
                f'<details class="gd-full"><summary>Read the full entry<span class="sr"> for {esc(name)}</span></summary><div>{full}</div></details>'
                f'</article>')

    town_html, tags, rail, jump = [], [], [], []
    for i, (t, sh) in enumerate(towns):
        cards = "".join(shop_html(n, p, shops[n]) for n, p, _ in sh)
        asides = "".join(f'<p class="gd-aside">{esc(x)}</p>' for _, _, ax in sh for x in ax)
        cnt = len(sh)
        word = "shop" if cnt == 1 else "shops"
        town_html.append(f'<section class="gd-town" id="{tid(t)}"><h2>{esc(t)} <small>{cnt} {word}</small></h2>{cards}{asides}</section>')
        face = (f'<a class="gd-tag" href="#{tid(t)}"><span class="gd-face"><strong>{esc(t)}</strong><span class="n">{cnt}<span class="sr"> {word}</span></span></span>'
                f'<span class="gd-mark" data-town="{tid(t)}" hidden>0<span class="sr"> on my list</span></span></a>')
        tags.append(f'<li style="--i:{i}">{face}</li>')
        rail.append(f'<li>{face}</li>')
        jump.append(f'<li><a href="#{tid(t)}">{esc(t)}</a></li>')

    pj = json.loads((ROOT / "data" / "photos.json").read_text(encoding="utf-8"))
    ph = next(p for p in pj["photos"] if p["id"] == meta["hero_photo"])
    who = pj["photographers"][ph["photographer"]]
    credit = f'Photo: <a href="{esc(ph["source_url"])}" target="_blank" rel="noopener">{esc(who["name"])}</a>'
    t1, sep, t2 = meta["title"].partition(": ")
    h1 = (f'<span class="gd-t1">{esc(t1)}<span class="sr">:</span></span> <span class="gd-t2">{esc(t2)}</span>' if sep
          else f'<span class="gd-t1">{esc(meta["title"])}</span>')
    hero = (f'<header class="gd-hero"><div><h1>{h1}</h1><p class="dek">{esc(meta["description"])}</p>'
            f'<p class="chk">Checked {pretty_date(str(meta["updated"]))}</p></div>'
            f'<nav class="gd-twine" aria-label="Shops per town"><ul>{"".join(tags)}</ul></nav>'
            f'<figure class="gd-fig"><img src="/{esc(ph["file"])}" width="{ph["width"]}" height="{ph["height"]}" alt="{esc(ph["alt"])}" loading="lazy" decoding="async">'
            f'<figcaption>{esc(ph["title"])}, {esc(ph["place"])}. {credit}</figcaption></figure></header>')

    chips = ['<button class="gd-chip" type="button" data-f="all" aria-pressed="true">All</button>',
             '<button class="gd-chip" type="button" data-f="posted" aria-pressed="false">Hours posted</button>',
             '<button class="gd-chip" type="button" data-f="call" aria-pressed="false">Call ahead</button>']
    for (gk, gl) in groups:
        chips.append(f'<button class="gd-chip" type="button" data-f="{gk}" aria-pressed="false">{esc(gl)}</button>')
    chips.append('<button class="gd-chip" type="button" data-f="saved" aria-pressed="false">My list</button>')

    table = md_to_html(glance_md, slug, cb)
    table_html = (f'<details class="gd-more"><summary>See all {n_shops} in a table</summary>'
                  f'<div class="gd-scroll"><h2 class="gd-glance">At a glance</h2>{table}</div></details>')
    faq_html = ""
    if faq:
        items = "".join(f'<details><summary>{esc(q["q"])}</summary><p>{cite_html(markdown.markdown(q["a"])[3:-4], slug, cb)}</p></details>' for q in faq)
        faq_html = f'<section class="gd-faq" id="quick-answers"><h2>Quick answers</h2>{items}</section>'
    after_html = "".join(f'<section class="gd-prose gd-end">{md_to_html(f"## {t}" + chr(10) * 2 + r, slug, cb)}</section>'
                         for t, r in after)
    others = [m for (m, _) in all_articles if m["slug"] != slug]
    others.sort(key=lambda m: m["slug"] != "cape-cod-holiday-events-2026")
    plan = ('<section class="gd-plan"><h2>Keep planning</h2><div class="g-cards">' + "".join(card(m) for m in others)
            + '<a class="g-card" href="/app/"><span>Free app</span><b>Open the Totally Cape Cod app</b><span>Beaches, events and eats</span></a>'
            + '</div></section>')
    share = ('<div class="gd-share"><button class="gd-btn" id="gd-share" type="button" hidden>' + icon("share") + 'Share this guide</button>'
             '<span id="gd-sharemsg" role="status"></span></div>')
    disclosure = (meta.get("disclosure") or ("This guide was researched with the help of AI tools and checked line by line "
                  "against the sources listed below before publishing.")).replace("listed below", "listed on the sources page")
    intro_html = md_to_html(intro, slug, cb)
    ld = article_ld(meta, a, url, sources, faq)
    crumbs = '<div class="gd-crumbs"><a href="/">Home</a> › <a href="/guides/">Guides</a></div>'
    shared_html = ('<div class="gd-shared" id="gd-shared" hidden><p id="gd-sharedtext"></p>'
                   '<button class="gd-btn" id="gd-sshow" type="button">Show these shops</button>'
                   '<button class="gd-btn" id="gd-sadd" type="button">Add them to my list</button></div>')
    bar = ('<div class="gd-bar" id="gd-bar" hidden><p><strong id="gd-bartext">My list: 0 shops</strong> '
           '<span id="gd-barstatus" role="status"><span id="gd-maplimit"></span> <span id="gd-barmsg"></span></span></p>'
           '<div class="gd-barb"><button class="gd-btn" id="gd-show" type="button">Show my list</button>'
           '<a class="gd-btn" id="gd-map" href="#" target="_blank" rel="noopener">Map my list</a>'
           '<button class="gd-btn" id="gd-listshare" type="button">Share my list</button></div></div>')
    return (head(f'{meta.get("seo_title") or meta["title"]} | Totally Cape Cod', meta["description"], url, ld, extra=DIR_CSS + "<style>" + KR_CSS + "</style>")
            + f"""{SPRITE}<main class="gd">
{crumbs}
{hero}
{trust_box(meta, len(sources), True)}
{shared_html}
<div class="gd-prose">{intro_html}</div>
{live_strip(meta, sorted({v["town"] for v in shops.values()}))}
<div class="gd-layout">
<aside class="gd-rail"><nav class="gd-twine" aria-label="Jump to town, side list"><ul>{"".join(rail)}</ul></nav><p class="gd-railsum" id="gd-railsum" hidden></p></aside>
<div class="gd-listcol">
<nav class="gd-jump" aria-label="Jump to town"><span class="lbl">Jump to town</span><ul>{"".join(jump)}</ul></nav>
<div class="gd-filters" id="gd-filters" role="group" aria-label="Filter shops" hidden>{"".join(chips)}</div>
<p class="gd-count" id="gd-count" role="status" hidden></p>
<p class="gd-empty" id="gd-empty" hidden>Nothing is on your list yet. Choose &ldquo;Add to my list&rdquo; on a shop to start.</p>
{"".join(town_html)}
</div>
</div>
{table_html}
{faq_html}
{after_html}
{trust_box(meta, len(sources), True)}
{share}
{keep_reading(meta, all_articles)}
<div class="gd-note">📝 {esc(disclosure)} Spot something out of date? <a href="/contact.html">Tell us</a> and we'll fix it.</div>
{bar}
</main>
{FOOTER}
{DIR_JS}
</body>
</html>
""")


# ------------------------------------------------------- prose guide layout (default) ---
# Default for every article that is not `layout: directory` or `layout: classic`.
# `layout: classic` renders the original page exactly (used for the events guide until its season ends).
METHOD_TITLES = ("How this list was made", "How this guide was made")


def has_sources_page(meta: dict) -> bool:
    return (meta.get("layout") or "article") != "classic"


def photo_figure(photo_id: str, aspect: str = "16/9") -> str:
    pj = json.loads((ROOT / "data" / "photos.json").read_text(encoding="utf-8"))
    ph = next(p for p in pj["photos"] if p["id"] == photo_id)
    who = pj["photographers"][ph["photographer"]]
    if ph.get("credit"):
        credit = f'<a href="{esc(ph["source_url"])}" target="_blank" rel="noopener">{esc(ph["credit"])}</a>'
    else:
        credit = f'Photo: <a href="{esc(ph["source_url"])}" target="_blank" rel="noopener">{esc(who["name"])}</a>'
    return (f'<figure class="ga-fig"><img src="/{esc(ph["file"])}" width="{ph["width"]}" height="{ph["height"]}" alt="{esc(ph["alt"])}" '
            f'loading="lazy" decoding="async" style="aspect-ratio:{aspect}">'
            f'<figcaption>{esc(ph["title"])}, {esc(ph["place"])}. {credit}</figcaption></figure>')


def keep_reading(meta: dict, all_articles: list) -> str:
    """Up to three other guides (same cluster first, then newest), plus events and the app."""
    others = [m for (m, _) in all_articles if m["slug"] != meta["slug"]]     # already newest first
    same = [m for m in others if meta.get("cluster") and m.get("cluster") == meta.get("cluster")]
    pick = (same + [m for m in others if m not in same])[:3]
    rows = "".join(f'<li><a href="/guides/{esc(m["slug"])}/">{esc(m["title"])}</a><p>{esc(m["description"])}</p></li>' for m in pick)
    return (f'<section class="kr"><h2>Keep reading</h2><ul>{rows}</ul>'
            '<p class="more"><a class="kr-btn" href="/events">Browse Cape Cod events</a>'
            '<a class="kr-btn" href="/app/">Open the free app</a></p></section>')


KR_CSS = """
.kr{margin-top:44px}.kr h2{font-weight:900;font-size:30px;line-height:1.1;margin:0 0 6px}
.kr ul{list-style:none;margin:0;padding:0;max-width:35rem}.kr li{padding:16px 0;border-bottom:2px dashed var(--kraft)}
.kr li a{font:800 20px/1.25 'Fraunces',Georgia,serif;color:var(--navy);text-decoration:none}.kr li a:hover{text-decoration:underline}
.kr li p{margin:6px 0 0;font-size:16px;line-height:1.5;color:var(--mute)}
.kr .more{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0}
.kr-btn{display:inline-flex;align-items:center;min-height:44px;padding:0 16px;border:1.5px solid var(--navy);border-radius:22px;color:var(--navy);font:600 16px/1 'Inter',sans-serif;text-decoration:none;background:#fff}
.kr-btn:hover{background:var(--sand)}
"""

ART_CSS = """<style>
.ga{--paper:#FDF8F2;--ink:#4A4038;--mute:#625749;--navy:#1A3A6C;--kraft:#D4A574;--kraftd:#9A6F3C;--sand:#F5E6D3;--bay:#2F6B57;--line:#E4D6C2;max-width:720px;margin:0 auto;padding:78px 18px 56px;font-size:17px;line-height:1.65;color:var(--ink)}
.ga [hidden]{display:none!important}
.ga a{color:var(--navy)}
.ga a:focus-visible,.ga summary:focus-visible,.ga .ga-scroll:focus-visible{outline:3px solid var(--navy);outline-offset:2px;border-radius:6px}
.ga h1,.ga h2,.ga h3{font-family:'Fraunces',Georgia,serif;color:var(--navy);margin:0}
.ga .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.ga-crumbs{font-size:15px;color:var(--mute);margin-bottom:14px}
.ga-hero h1{font-weight:900;font-size:clamp(32px,8vw,48px);line-height:1.06;letter-spacing:-.015em;margin:0 0 14px}
.ga-hero .dek{font-size:19px;line-height:1.5;margin:0 0 14px;max-width:35rem}
.ga-by{display:flex;flex-wrap:wrap;gap:2px 20px;font-size:15px;color:var(--mute);padding:12px 0 14px;border-bottom:2px dashed var(--kraft)}
.ga-by a{color:var(--navy)}
.ga-fig{margin:18px 0 0}.ga-fig img{width:100%;height:auto;object-fit:cover;border-radius:12px;background:#D9C8B0}
.ga-fig figcaption{font-size:15px;line-height:1.45;color:var(--mute);margin-top:7px}
.ga-trust{display:flex;gap:12px;align-items:flex-start;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:14px 0;margin:22px 0;font-size:17px;line-height:1.5}
.ga-trust p{margin:0}.gd-i{flex:none;display:block}.gd-tick{margin-top:2px;color:var(--bay)}
.ga-jump{position:sticky;top:73px;z-index:40;display:flex;align-items:center;gap:6px;background:var(--paper);border-bottom:1px solid var(--line);margin:0 -18px;padding:0 18px}
.ga-jump .lbl{flex:none;font-size:15px;color:var(--mute);padding-right:4px}
.ga-jump ul{display:flex;gap:2px;list-style:none;margin:0;padding:0;overflow-x:auto;scrollbar-width:thin}
.ga-jump a{display:flex;align-items:center;min-height:44px;padding:0 12px;white-space:nowrap;font-weight:600;font-size:16px;text-decoration:none;color:var(--ink);border-bottom:3px solid transparent}
.ga-jump a:hover{border-bottom-color:var(--navy)}
.ga-body{padding-top:6px}
.ga-body>*{max-width:35rem}.ga-body>.ga-scroll{max-width:none}
.ga-body h2{font-weight:900;font-size:30px;line-height:1.12;margin:44px 0 12px;scroll-margin-top:130px}
.ga-body h3{font-weight:800;font-size:22px;line-height:1.2;margin:28px 0 8px;scroll-margin-top:130px}
.ga-body p{margin:0 0 14px}.ga-body ul,.ga-body ol{padding-left:22px;margin:0 0 14px}.ga-body li{margin:0 0 8px}
.ga-body a{text-decoration:underline;text-underline-offset:2px}
.ga-body blockquote{font-family:'Fraunces',Georgia,serif;font-style:italic;font-size:18px;line-height:1.5;color:var(--mute);border-left:1px solid var(--kraftd);padding:2px 0 2px 14px;margin:20px 0}
.ga-body hr{border:0;border-top:2px dashed var(--kraft);margin:28px 0}
.ga-scroll{overflow-x:auto;margin:18px 0}
.ga-scroll table{border-collapse:collapse;font-size:15px;line-height:1.45;width:100%}.ga-scroll table.wide{min-width:560px}
.ga-scroll th,.ga-scroll td{text-align:left;padding:9px 10px;border-bottom:1px dashed var(--kraft);vertical-align:top}
.ga-scroll th{background:var(--sand);color:var(--ink)}
.ga-faq{margin-top:44px;max-width:35rem}.ga-faq h2{font-weight:900;font-size:30px;line-height:1.1;margin:0 0 10px}
.ga-faq details{border-bottom:1px dashed var(--kraft);padding:4px 0}
.ga-faq summary{display:flex;align-items:center;min-height:48px;font-weight:600;color:var(--navy);cursor:pointer}
.ga-faq p{margin:4px 0 12px}
.ga-note{font-size:15px;line-height:1.55;border-top:1px solid var(--line);padding-top:14px;margin:30px 0 0;color:var(--mute);max-width:35rem}
sup.cite-q{font-size:.68em;line-height:0;margin-left:1px;white-space:nowrap}
sup.cite-q a{position:relative;color:#566A75!important;text-decoration:none!important;font-weight:600}
sup.cite-q a+a::before{content:","}
sup.cite-q a::after{content:"";position:absolute;inset:-14px -4px}
sup.cite-q a:hover{color:var(--navy)!important;text-decoration:underline!important}
.live-events-embed{margin:16px 0}
@media(min-width:700px){.ga-fig img{aspect-ratio:21/9!important}}
@media(max-width:999px){.ga-jump{top:61px}}
@media(max-width:768px){.ga-jump{top:73px}}
@media(max-width:480px){.ga{padding-left:14px;padding-right:14px}.ga-jump{margin-left:-14px;margin-right:-14px;padding:0 14px}}
</style>
"""


def render_prose(meta: dict, body: str, authors: dict, all_articles: list) -> str:
    slug = meta["slug"]
    url = f"{SITE}/guides/{slug}/"
    a = authors[meta["author"]]
    cb = f"/guides/{slug}/sources/"
    sources = sorted(meta.get("sources") or [], key=lambda s: s["id"])
    faq = meta.get("faq") or []
    main_body = body
    if any(re.search(rf"(?m)^## {re.escape(t)}\s*$", body) for t in METHOD_TITLES):
        intro, secs = split_body(body)
        main_body = intro + "".join(f"\n\n## {t}\n\n{r}" for t, r in secs if t not in METHOD_TITLES)
    body_html = md_to_html(main_body, slug, cb)
    body_html = re.sub(r"<table>(.*?)</table>",
                       lambda m: ('<div class="ga-scroll" tabindex="0" role="region" aria-label="Table, scrolls sideways"><table'
                                  + (' class="wide"' if len(re.findall(r"<th[ >]", m.group(1))) >= 3 else "") + ">" + m.group(1) + "</table></div>"),
                       body_html, flags=re.S)
    heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body_html, flags=re.S)
    jump = ""
    if len(heads) >= 3:
        links = "".join(f'<li><a href="#{hid}">{re.sub(r"<[^>]+>", "", txt)}</a></li>' for hid, txt in heads)
        jump = f'<nav class="ga-jump" aria-label="In this guide"><span class="lbl">In this guide</span><ul>{links}</ul></nav>'
    ld = article_ld(meta, a, url, sources, faq)
    byline = (f'<p class="ga-by"><span>By <a href="/authors/{esc(meta["author"])}/" rel="author">{esc(a["name"])}</a></span>'
              f'<span>Updated <time datetime="{meta["updated"]}">{pretty_date(meta["updated"])}</time></span>'
              f'<span><a href="/guides/standards/">How we fact-check</a></span></p>')
    fig = photo_figure(meta["hero_photo"]) if meta.get("hero_photo") else ""
    faq_html = ""
    if faq:
        items = "".join(f'<details><summary>{esc(q["q"])}</summary><p>{cite_html(markdown.markdown(q["a"])[3:-4], slug, cb)}</p></details>' for q in faq)
        faq_html = f'<section class="ga-faq" id="quick-answers"><h2>Quick answers</h2>{items}</section>'
    disclosure = (meta.get("disclosure") or ("This guide was researched with the help of AI tools and checked line by line "
                  "against the sources listed below before publishing.")).replace("listed below", "listed on the sources page")
    scripts = '<script src="/js/live-events.js" defer></script>' if "data-live-events" in body_html else ""
    return (head(f'{meta.get("seo_title") or meta["title"]} | Totally Cape Cod', meta["description"], url, ld, extra=ART_CSS + "<style>" + KR_CSS + "</style>")
            + f"""{SPRITE}<main class="ga">
<div class="ga-crumbs"><a href="/">Home</a> › <a href="/guides/">Guides</a></div>
<header class="ga-hero"><h1>{esc(meta["title"])}</h1><p class="dek">{esc(meta["description"])}</p>{byline}{fig}</header>
{trust_box(meta, len(sources), True, True, "ga-trust")}
{jump}
<article class="ga-body">
{insert_live_strip(body_html, meta)}
</article>
{faq_html}
{trust_box(meta, len(sources), True, True, "ga-trust")}
<div class="ga-note">📝 {esc(disclosure)} Spot something out of date? <a href="/contact.html">Tell us</a> and we'll fix it.</div>
{keep_reading(meta, all_articles)}
</main>
{FOOTER}
{scripts}
</body>
</html>
""")


CLUSTER_LABELS = {"holidays": "Holidays", "seasons": "Seasons", "bridges": "Getting around", "wildlife": "Wildlife"}


def render_hub(articles: list) -> str:
    url = f"{SITE}/guides/"
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "Cape Cod Guides", "url": url,
           "description": "Researched, source-cited guides to Cape Cod — events, seasons, beaches, wildlife and travel planning.",
           "hasPart": [{"@type": "Article", "headline": m["title"], "url": f"{SITE}/guides/{m['slug']}/"} for m, _ in articles]}]
    groups: dict = {}
    for m, _ in articles:                              # articles are newest first, so clusters sort by newest guide
        groups.setdefault(m.get("cluster") or "other", []).append(m)
    sections = ""
    for cl, ms in groups.items():
        rows = "".join(f'<li><a href="/guides/{esc(m["slug"])}/">{esc(m["title"])}</a><p>{esc(m["description"])}</p>'
                       f'<p class="when">Updated {esc(pretty_date(m["updated"]))}</p></li>' for m in ms)
        sections += f'<section class="hub-g"><h2>{esc(CLUSTER_LABELS.get(cl) or cl.replace("-", " ").capitalize())}</h2><ul>{rows}</ul></section>'
    if not sections:
        sections = '<p class="muted">Guides are on the way.</p>'
    return (head("Cape Cod Guides — Researched, Source-Cited Local Guides | Totally Cape Cod",
                 "Cape Cod guides you can trust: events, seasons, beaches, wildlife and trip planning — every fact linked to its source.",
                 url, ld, og_type="website", extra=ART_CSS + "<style>" + HUB_CSS + "</style>")
            + f"""<main class="ga">
<div class="ga-crumbs"><a href="/">Home</a> › Guides</div>
<header class="ga-hero"><h1>Cape Cod Guides</h1>
<p class="dek">Local guides to Cape Cod's events, seasons, beaches and wildlife. Every fact is linked to the source it came from — <a href="/guides/standards/">here's how we check</a>.</p></header>
{sections}
</main>
{FOOTER}
</body>
</html>
""")


HUB_CSS = """
.hub-g{margin-top:36px}.hub-g h2{font-weight:900;font-size:30px;line-height:1.1}
.hub-g ul{list-style:none;margin:8px 0 0;padding:0;max-width:38rem}
.hub-g li{padding:16px 0;border-bottom:2px dashed var(--kraft)}
.hub-g li a{font:800 21px/1.25 'Fraunces',Georgia,serif;color:var(--navy);text-decoration:none}.hub-g li a:hover{text-decoration:underline}
.hub-g li p{margin:6px 0 0;font-size:16px;line-height:1.5}.hub-g li .when{font-size:15px;color:var(--mute)}
"""


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

Under each source you can open "What the source says": the exact passages we checked the guide against. We keep those excerpts on file, along with an archived copy of the page where one can be made, so the record survives even if the original page changes.

We prefer primary sources: the organizer's own listing for an event, the town, state or National Park Service for rules and seasons, and the business itself for hours.

## We pass information along; we don't make it up

Totally Cape Cod is an intermediary. We don't invent facts, rankings, reviews or quotes. We research, confirm with the source, and then post. If we can't confirm something, we leave it out. Our social posts follow the same rule and name their sources.

## Credit where it's due

Events and photos are credited to the people and organizations behind them, with a link back to the original. We only use a photographer's work with their permission.

## How guides are made

Guides are researched with the help of AI tools. Before anything is published, a separate review checks each factual claim against the text of its cited source; anything we can't confirm is cut, not guessed. Guides are updated when plans change — the "Updated" date shows the last check.

## When we get something wrong

Plans change and mistakes happen. If you spot something wrong or out of date, [tell us](/contact.html) and we'll correct it.

## Independence

Nothing in our guides is there because someone paid for it. Paid listings elsewhere on the site are labeled "Sponsored."
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
        fname = "app/index.html" if rel in ("", "app/") else "index.html" if rel == "welcome" else rel
        if fname and not (ROOT / fname).is_file() and (ROOT / f"{fname}.html").is_file():
            fname = f"{fname}.html"  # extensionless canonical (e.g. /events) served from events.html
        f = ROOT / fname
        lm = git_lastmod(f) if f.exists() else None
        if fname in dirty:
            lm = date.today().isoformat()
        if lm:
            e["lastmod"] = lm
    newest = max([m["updated"] for m, _ in articles] or [date.today().isoformat()])
    entries[f"{SITE}/guides/"] = dict(loc=f"{SITE}/guides/", lastmod=newest, changefreq="weekly", priority="0.8")
    entries[f"{SITE}/guides/standards/"] = dict(loc=f"{SITE}/guides/standards/", lastmod="2026-11-08", changefreq="yearly", priority="0.3")
    for aid in authors:
        entries[f"{SITE}/authors/{aid}/"] = dict(loc=f"{SITE}/authors/{aid}/", lastmod=newest, changefreq="monthly", priority="0.4")
    for m, _ in articles:
        loc = f"{SITE}/guides/{m['slug']}/"
        entries[loc] = dict(loc=loc, lastmod=m["updated"], changefreq=m.get("changefreq", "weekly"), priority=str(m.get("priority", "0.8")))
        if has_sources_page(m):
            sloc = loc + "sources/"
            entries[sloc] = dict(loc=sloc, lastmod=m["updated"], changefreq="monthly", priority="0.4")
    rows = []
    for e in entries.values():
        rows.append("  <url>\n    <loc>{}</loc>\n{}{}{}  </url>".format(
            e["loc"],
            f"    <lastmod>{e['lastmod']}</lastmod>\n" if e.get("lastmod") else "",
            f"    <changefreq>{e['changefreq']}</changefreq>\n" if e.get("changefreq") else "",
            f"    <priority>{e['priority']}</priority>\n" if e.get("priority") else ""))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def render_knowledge(articles: list) -> str:
    """Fact-checked Q&A from every guide's FAQ, for the app's concierge. Each answer keeps the
    names of the sources it cites, so the concierge can credit them and link the guide."""
    out = []
    for meta, _ in articles:
        srcs = {s["id"]: s.get("publisher") or s.get("title") or "" for s in meta.get("sources") or []}
        facts = []
        for q in meta.get("faq") or []:
            ids = [int(n) for grp in CITE_RE.findall(q["a"]) for n in re.findall(r"\d+", grp if isinstance(grp, str) else " ".join(grp))]
            names = []
            for i in ids:
                if srcs.get(i) and srcs[i] not in names:
                    names.append(srcs[i])
            tidy = lambda t: re.sub(r"\s+([.,;:)])", r"\1", plain(t))
            facts.append({"q": tidy(q["q"]), "a": tidy(q["a"]), "sources": names})
        out.append({"slug": meta["slug"], "url": f"{SITE}/guides/{meta['slug']}/", "title": meta["title"],
                    "updated": str(meta["updated"]), "keywords": meta.get("keywords") or [], "facts": facts})
    return json.dumps({"about": "Fact-checked answers from Totally Cape Cod guides (each guide's FAQ), "
                                "with the sources each answer cites. Generated by scripts/content/build_site.py.",
                       "guides": out}, ensure_ascii=False, indent=1) + "\n"


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
        errors += validate_evidence(meta)
        errors += validate_directory(meta, body)
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
        if has_sources_page(meta):
            write(ROOT / "guides" / meta["slug"] / "sources" / "index.html", render_sources_page(meta, body, authors))
    write(ROOT / "guides" / "index.html", render_hub(articles))
    write(ROOT / "guides" / "standards" / "index.html", render_standards())
    write(ROOT / "guides" / "feed.xml", render_rss(articles, authors))
    write(ROOT / "guides" / "knowledge.json", render_knowledge(articles))
    for aid, a in authors.items():
        write(ROOT / "authors" / aid / "index.html", render_author(aid, a, articles))
    write(ROOT / "sitemap.xml", build_sitemap(articles, authors))
    print(f"✓ built {len(articles)} guide page(s), hub, standards, RSS, author page(s), sitemap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
