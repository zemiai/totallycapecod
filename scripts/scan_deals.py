"""One-off scan: visit each restaurant's OWN website and surface any deals /
specials / happy hours they're advertising. Public-site scraping only — never
touches Facebook/Instagram (blocked + ToS + account-ban risk).

Reads data/eats.json (website field from Google Places enrichment), fetches the
homepage plus up to 2 likely deal pages (specials / happy-hour / events / menu),
and extracts text lines that match deal signals. Writes data/eats-deals.json and
prints a human-readable report.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).parent.parent
EATS = ROOT / "data" / "eats.json"
OUT = ROOT / "data" / "eats-deals.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124 Safari/537.36"}
TIMEOUT = 15

DEAL_PATTERNS = [
    r"happy[\s-]?hour", r"early[\s-]?bird", r"early dining", r"prix[\s-]?fixe",
    r"fixed[\s-]price", r"\bb\.?o\.?g\.?o\b", r"buy one", r"two for", r"twofer",
    r"\$\d+\s*off", r"\d+%\s*off", r"half[\s-]?(?:price|off)", r"bottomless",
    r"all[\s-]you[\s-]can[\s-]eat", r"kids? eat free", r"kids? night",
    r"taco tuesday", r"\$\d+\s*(?:oyster|taco|burger|margarita|drink|beer|wine)",
    r"\bdollar\b.{0,12}(?:oyster|taco)", r"oyster (?:hour|night|special)",
    r"daily special", r"lunch special", r"dinner special", r"weekly special",
    r"drink special", r"food special", r"\bspecials?\b", r"early menu",
    r"sunset menu", r"raw bar special", r"wine[\s-]down", r"industry night",
    r"trivia night", r"\bdiscount\b", r"\bpromo(?:tion)?\b", r"\bdeal\b",
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day.{0,20}(?:special|night|\$|half)",
]
DEAL_RE = re.compile("|".join(DEAL_PATTERNS), re.I)
# pages worth following beyond the homepage
SUBPAGE_HINTS = re.compile(r"special|happy|deal|offer|event|menu|dining", re.I)
NOISE = re.compile(r"privacy|cookie|copyright|reserved|powered by|terms of", re.I)


def clean_url(u: str) -> str:
    return u.split("?")[0].rstrip("/") if u else u


def get_text(url: str):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            return None, r.status_code, ""
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        return soup, 200, soup.get_text("\n", strip=True)
    except Exception:
        return None, "ERR", ""


def scan_site(name: str, website: str) -> dict:
    base = clean_url(website)
    if not base.startswith("http"):
        base = "http://" + base
    domain = urlparse(base).netloc
    soup, status, text = get_text(base)
    pages = {base: text}
    if soup is not None:
        # follow up to 2 same-domain deal-ish subpages
        followed = 0
        for a in soup.find_all("a", href=True):
            if followed >= 2:
                break
            label = (a.get_text(" ", strip=True) + " " + a["href"])
            if not SUBPAGE_HINTS.search(label):
                continue
            href = urljoin(base, a["href"])
            if urlparse(href).netloc != domain or clean_url(href) in pages:
                continue
            _s, _st, sub = get_text(href)
            if sub:
                pages[clean_url(href)] = sub
                followed += 1

    deals, seen = [], set()
    for url, body in pages.items():
        if not body:
            continue
        for line in body.split("\n"):
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) < 6 or len(line) > 180 or NOISE.search(line):
                continue
            if DEAL_RE.search(line):
                key = line.lower()
                if key in seen:
                    continue
                seen.add(key)
                deals.append({"text": line, "page": url})
    total_text = sum(len(t) for t in pages.values())
    return {
        "name": name, "website": base, "status": status,
        "thin": total_text < 400,                 # likely JS-rendered / blocked
        "deals": deals[:8],
    }


def main():
    eats = json.load(open(EATS, encoding="utf-8"))["eats"]
    targets = [(r["name"], r["website"]) for r in eats if r.get("website")]
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(scan_site, n, w): n for n, w in targets}
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                results.append({"name": futs[f], "status": "ERR", "deals": [], "thin": True, "err": str(e)})
    results.sort(key=lambda r: (-len(r["deals"]), r["name"]))

    with_deals = [r for r in results if r["deals"]]
    thin = [r for r in results if not r["deals"] and r.get("thin")]
    nothing = [r for r in results if not r["deals"] and not r.get("thin")]

    json.dump({"scanned": len(results), "with_deals": len(with_deals),
               "results": results}, open(OUT, "w", encoding="utf-8"), indent=2)

    print(f"\nScanned {len(results)} restaurant sites — {len(with_deals)} advertise deals on their site.\n")
    print("=" * 70)
    for r in with_deals:
        print(f"\n🍴 {r['name']}")
        for d in r["deals"]:
            print(f"   • {d['text']}")
    print("\n" + "=" * 70)
    print(f"\n⚠ Site too JS-heavy / blocked to read statically ({len(thin)}) — would need a browser or a human glance:")
    print("   " + ", ".join(r["name"] for r in thin))
    print(f"\n— No deals found in static text ({len(nothing)}):")
    print("   " + ", ".join(r["name"] for r in nothing))


if __name__ == "__main__":
    main()
