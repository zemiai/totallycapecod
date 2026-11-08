#!/usr/bin/env python3
"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver, Yep) which pages changed.

    python scripts/indexnow.py URL [URL ...]               # submit these URLs
    python scripts/indexnow.py --changed FROM_SHA TO_SHA    # pages whose HTML changed between commits
    python scripts/indexnow.py --all                        # every URL in sitemap.xml
    add --wait to wait until the key file is live and the latest deploy has had time to finish

Only canonical URLs listed in sitemap.xml are sent. The key is public by design: it lives in
/<KEY>.txt at the site root, which is how the engines verify we own the host. Google doesn't
use IndexNow (it reads sitemap.xml), so this is purely for Bing and friends. The
.github/workflows/indexnow.yml workflow runs it on every push that changes a page.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://totallycapecod.com"
HOST = "totallycapecod.com"
KEY = "bd4c12d595bb167aa66f32215398f8f5"
KEY_URL = f"{SITE}/{KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"
UA = "TotallyCapeCod-IndexNow/1.0 (+https://totallycapecod.com)"


def locs(text: str) -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", text)


def sitemap_urls() -> list[str]:
    return locs((ROOT / "sitemap.xml").read_text(encoding="utf-8"))


def file_candidates(path: str) -> list[str]:
    """Possible canonical URLs for a changed file (the one in sitemap.xml wins)."""
    if path == "app/index.html":
        return [f"{SITE}/"]
    if path == "index.html":
        return [f"{SITE}/welcome"]
    if path.endswith("/index.html"):
        return [f"{SITE}/{path[: -len('index.html')]}"]
    return [f"{SITE}/{path}", f"{SITE}/{path[: -len('.html')]}"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def changed_urls(a: str, b: str) -> list[str]:
    if not a or set(a) == {"0"}:  # first push of a branch: compare with the parent commit
        a = f"{b}~1"
    try:
        names = git("diff", "--name-only", a, b).split()
    except subprocess.CalledProcessError:
        names = git("diff", "--name-only", f"{b}~1", b).split()
    in_map = set(sitemap_urls())
    out = []
    for n in names:
        if n.endswith(".html") and not n.startswith("data/"):
            out += [u for u in file_candidates(n) if u in in_map][:1]
    if "sitemap.xml" in names:  # pages newly added to the sitemap
        try:
            old = set(locs(git("show", f"{a}:sitemap.xml")))
        except subprocess.CalledProcessError:
            old = set()
        out += [u for u in sitemap_urls() if u not in old]
    return list(dict.fromkeys(out))


def fetch_ok(url: str, expect: str | None = None) -> bool:
    try:
        req = urllib.request.Request(f"{url}?t={int(time.time())}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status == 200 and (expect is None or expect in body)
    except Exception:
        return False


def wait_for_deploy(timeout: int = 300, settle: int = 60) -> None:
    end = time.time() + timeout
    while time.time() < end and not fetch_ok(KEY_URL, KEY):
        time.sleep(15)
    time.sleep(settle)  # let Netlify finish publishing the rest of the deploy


def submit(urls: list[str]) -> int:
    if not urls:
        print("IndexNow: no changed pages to submit")
        return 0
    body = json.dumps({"host": HOST, "key": KEY, "keyLocation": KEY_URL, "urlList": urls[:10000]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            # 200 = received; 202 = received, key validation still pending
            print(f"IndexNow: HTTP {r.status} for {len(urls)} URL(s)")
            for u in urls:
                print("  ", u)
            return 0
    except urllib.error.HTTPError as e:
        print(f"IndexNow: HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}")
        return 1
    except Exception as e:  # network trouble shouldn't fail a deploy
        print(f"IndexNow: {e}")
        return 1


def main(argv: list[str]) -> int:
    wait = "--wait" in argv
    argv = [a for a in argv if a != "--wait"]
    if argv[:1] == ["--all"]:
        urls = sitemap_urls()
    elif argv[:1] == ["--changed"] and len(argv) == 3:
        urls = changed_urls(argv[1], argv[2])
    elif argv and all(a.startswith(SITE) for a in argv):
        urls = argv
    else:
        print(__doc__)
        return 2
    if wait and urls:
        wait_for_deploy()
    return submit(urls)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
