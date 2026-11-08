#!/usr/bin/env python3
"""Make Wayback Machine copies of the pages our guides cite, and record them.

For every content/evidence/<slug>.json, each source whose "archived" is empty is sent to the
Internet Archive's Save Page Now. The snapshot URL is written back to the evidence file, and
the guide's Sources list shows it as "archived copy" on the next site build. That way the
record of what a source said survives even if the original page changes or disappears.

    python scripts/content/archive_sources.py            # archive anything missing (max 30 per run)
    python scripts/content/archive_sources.py --limit 5

Runs in GitHub Actions (.github/workflows/archive-sources.yml); the Archive rate-limits
anonymous captures, so it paces itself and stops early on HTTP 429.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "content" / "evidence"
UA = "TotallyCapeCod-References/1.0 (+https://totallycapecod.com/guides/standards/)"
SKIP = re.compile(r"^https?://(www\.|m\.)?facebook\.com/", re.I)   # login wall: nothing useful to archive
PAUSE = 10


def snapshot_url(r: requests.Response, url: str) -> str | None:
    for h in ("Content-Location", "Location"):
        loc = r.headers.get(h, "")
        m = re.search(r"/web/(\d{14})/", loc)
        if m:
            return f"https://web.archive.org/web/{m.group(1)}/{url}"
    m = re.search(r"/web/(\d{14})/", r.url or "")
    return f"https://web.archive.org/web/{m.group(1)}/{url}" if m else None


def save(url: str) -> tuple[str | None, int]:
    try:
        r = requests.get(f"https://web.archive.org/save/{url}", headers={"User-Agent": UA},
                         timeout=180, allow_redirects=False)
    except requests.RequestException as e:
        print(f"  ! {url}: {e}")
        return None, 0
    return (snapshot_url(r, url) if r.status_code in (200, 301, 302) else None), r.status_code


def main(argv: list[str]) -> int:
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 30
    done = 0
    for f in sorted(EVIDENCE.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        changed = False
        for s in data.get("sources") or []:
            url = s.get("url") or ""
            if s.get("archived") or not url.startswith("http"):
                continue
            if SKIP.match(url):
                if s.get("archive_note") != "not archivable (login wall)":
                    s["archive_note"] = "not archivable (login wall)"
                    changed = True
                continue
            if done >= limit:
                break
            snap, code = save(url)
            done += 1
            print(f"  {code} {url} -> {snap or '-'}")
            if snap:
                s["archived"] = snap
                s.pop("archive_note", None)
                changed = True
            if code == 429:
                print("rate-limited by the Archive; stopping until the next run")
                limit = done
            time.sleep(PAUSE)
        if changed:
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"updated {f.relative_to(ROOT)}")
    print(f"archive requests this run: {done}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
