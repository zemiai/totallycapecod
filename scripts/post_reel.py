#!/usr/bin/env python3
"""Publish the reel described by data/.reel_manifest.json (built by make_reel.py)
to the Facebook Page (video post) and Instagram (Reel, shared to feed).

Same Graph API pattern as the previously successful post_video.py: the mp4 must
already be pushed to main so Meta can fetch it from raw.githubusercontent.
Idempotent: skips if data/.reel_post_result.json already records this manifest's
date (FORCE=1 overrides). DRY_RUN=1 prints without posting.

Env: FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN, IG_USER_ID
"""
import json, os, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
GRAPH = "https://graph.facebook.com/v25.0"
RAW_BASE = "https://raw.githubusercontent.com/zemiai/totallycapecod/main"
SITE = "https://totallycapecod.com"

DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
FORCE = os.environ.get("FORCE", "") == "1"

manifest_path = DATA / ".reel_manifest.json"
if not manifest_path.exists():
    print("[reel] no manifest — make_reel.py skipped (thin day). Nothing to post.")
    sys.exit(0)
cfg = json.loads(manifest_path.read_text())
video_url = f"{RAW_BASE}/{cfg['video']}"
link = f"{SITE}/?utm_source=facebook&utm_medium=social&utm_campaign={cfg.get('campaign','reel')}"

if DRY_RUN:
    print(f"--- DRY RUN reel ({video_url}) ---")
    print(cfg["fb_caption"])
    sys.exit(0)

result_path = DATA / ".reel_post_result.json"
if result_path.exists() and not FORCE:
    try:
        if json.loads(result_path.read_text()).get("date") == cfg.get("date"):
            print(f"[reel] already posted for {cfg.get('date')} — skipping (FORCE=1 to override)")
            sys.exit(0)
    except Exception:
        pass

PAGE = os.environ["FB_PAGE_ID"]
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
IG = os.environ.get("IG_USER_ID", "").strip()

result = {"video": video_url, "date": cfg.get("date"),
          "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

def save_and_fail(stage, resp):
    result[stage] = {"error": resp.text[:500]}
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{stage} FAILED: {resp.status_code} {resp.text[:500]}", file=sys.stderr)
    sys.exit(1)

# ---- Facebook Page video ----
r = requests.post(f"{GRAPH}/{PAGE}/videos", data={
    "file_url": video_url, "description": cfg["fb_caption"], "access_token": TOKEN,
}, timeout=120)
if not r.ok:
    save_and_fail("facebook", r)
result["facebook"] = r.json()
fb_id = r.json().get("id", "")
print("[reel] FB video posted:", fb_id)
if fb_id:
    c = requests.post(f"{GRAPH}/{fb_id}/comments",
                      data={"message": f"📍 Full list, live → {link}", "access_token": TOKEN},
                      timeout=60)
    if not c.ok:
        print(f"[reel] FB comment failed (non-fatal): {c.text[:150]}", file=sys.stderr)

# ---- Instagram Reel ----
if IG:
    r = requests.post(f"{GRAPH}/{IG}/media", data={
        "media_type": "REELS", "video_url": video_url,
        "caption": cfg["ig_caption"], "share_to_feed": "true", "access_token": TOKEN,
    }, timeout=120)
    if not r.ok:
        save_and_fail("instagram_container", r)
    creation_id = r.json()["id"]
    print("[reel] IG container:", creation_id)

    for _ in range(60):  # Meta processes the video async — poll up to 10 min
        time.sleep(10)
        s = requests.get(f"{GRAPH}/{creation_id}",
                         params={"fields": "status_code", "access_token": TOKEN}, timeout=60)
        code = s.json().get("status_code")
        print("  status:", code)
        if code == "FINISHED":
            break
        if code == "ERROR":
            save_and_fail("instagram_processing", s)
    else:
        result["instagram"] = {"error": "processing timeout"}
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        sys.exit(1)

    r = requests.post(f"{GRAPH}/{IG}/media_publish",
                      data={"creation_id": creation_id, "access_token": TOKEN}, timeout=120)
    if not r.ok:
        save_and_fail("instagram_publish", r)
    result["instagram"] = r.json()
    print("[reel] IG posted:", r.json())

result_path.write_text(json.dumps(result, indent=2) + "\n")
print("[reel] done")
