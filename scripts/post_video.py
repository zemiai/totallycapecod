#!/usr/bin/env python3
"""One-shot video poster for the Totally Cape Cod FB Page + Instagram.

Reads data/manual_video_post.json:
    { "video": "img/social/foo.mp4", "fb_caption": "...", "ig_caption": "..." }

Posts the video to the Facebook Page (as a video post) and to Instagram
(as a Reel, shared to feed). Writes data/.video_post_result.json so the
outcome can be checked from the repo.

Env: FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN, IG_USER_ID
"""
import json, os, sys, time
import requests

GRAPH = "https://graph.facebook.com/v25.0"
RAW_BASE = "https://raw.githubusercontent.com/zemiai/totallycapecod/main"

PAGE = os.environ["FB_PAGE_ID"]
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
IG = os.environ["IG_USER_ID"]

cfg = json.load(open("data/manual_video_post.json"))
video_url = f"{RAW_BASE}/{cfg['video']}"
result = {"video": video_url, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

def fail(stage, resp):
    result[stage] = {"error": resp.text[:500]}
    json.dump(result, open("data/.video_post_result.json", "w"), indent=2)
    print(f"{stage} FAILED: {resp.status_code} {resp.text[:500]}", file=sys.stderr)
    sys.exit(1)

# ---- Facebook Page video ----
r = requests.post(f"{GRAPH}/{PAGE}/videos", data={
    "file_url": video_url,
    "description": cfg["fb_caption"],
    "access_token": TOKEN,
}, timeout=120)
if not r.ok:
    fail("facebook", r)
result["facebook"] = r.json()
print("FB video posted:", r.json())

# ---- Instagram Reel ----
r = requests.post(f"{GRAPH}/{IG}/media", data={
    "media_type": "REELS",
    "video_url": video_url,
    "caption": cfg["ig_caption"],
    "share_to_feed": "true",
    "access_token": TOKEN,
}, timeout=120)
if not r.ok:
    fail("instagram_container", r)
creation_id = r.json()["id"]
print("IG container:", creation_id)

# poll until Meta finishes processing the video
for i in range(60):
    time.sleep(10)
    s = requests.get(f"{GRAPH}/{creation_id}",
                     params={"fields": "status_code", "access_token": TOKEN},
                     timeout=60)
    code = s.json().get("status_code")
    print("  status:", code)
    if code == "FINISHED":
        break
    if code == "ERROR":
        fail("instagram_processing", s)
else:
    print("IG processing timed out", file=sys.stderr)
    result["instagram"] = {"error": "processing timeout"}
    json.dump(result, open("data/.video_post_result.json", "w"), indent=2)
    sys.exit(1)

r = requests.post(f"{GRAPH}/{IG}/media_publish", data={
    "creation_id": creation_id,
    "access_token": TOKEN,
}, timeout=120)
if not r.ok:
    fail("instagram_publish", r)
result["instagram"] = r.json()
print("IG posted:", r.json())

json.dump(result, open("data/.video_post_result.json", "w"), indent=2)
print("done")
