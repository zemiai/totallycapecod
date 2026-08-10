#!/usr/bin/env python3
"""One-shot: create the 3-ad acquisition campaign via the Marketing API.

Creates (all PAUSED — review in Ads Manager, then flip the campaign ACTIVE):
  Campaign "TCC — August acquisition" (Traffic)
   └─ Ad set $15/day · Cape 30mi + Boston 40mi · 25-65 · FB/IG feeds+stories
       ├─ Ad: Parking  (ad-parking-know-before-4x5.jpg → utm ad_parking)
       ├─ Ad: Bridge   (ad-bridge-beat-4x5.jpg        → utm ad_bridge)
       └─ Ad: Tonight  (ad-tonight-sorted-4x5.jpg     → utm ad_tonight)

Idempotent: if the campaign name already exists, exits without touching it.
Env: FB_ADS_TOKEN, FB_PAGE_ID, optional FB_AD_ACCOUNT_ID (auto-discovered).
"""
import base64, json, os, sys
from pathlib import Path
import requests

GRAPH = "https://graph.facebook.com/v21.0"
ROOT = Path(__file__).parent.parent
SITE = "https://totallycapecod.com"
TOKEN = os.environ.get("FB_ADS_TOKEN", "").strip()
ACCOUNT = os.environ.get("FB_AD_ACCOUNT_ID", "").strip()
PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
CAMPAIGN_NAME = "TCC — August acquisition"

ADS = [
    {"key": "ad_parking", "name": "Parking — Know before you drive",
     "image": "img/ads/ad-parking-know-before-4x5.jpg",
     "headline": "Live Cape Cod beach parking",
     "description": "Free · 27 beaches · updated every few minutes",
     "message": ("It's August on the Cape. Half the beach lots are full by 10 AM — and you "
                 "find out after you've driven 40 minutes. 🏖️ Totally Cape Cod shows live "
                 "parking for 27 beach lots, bridge delays, water temps & tonight's events. "
                 "Free, works on any phone.")},
    {"key": "ad_bridge", "name": "Bridge — Beat the bridge",
     "image": "img/ads/ad-bridge-beat-4x5.jpg",
     "headline": "Live Sagamore & Bourne delays",
     "description": "Know when to cross · free · no app store",
     "message": ("Everyone on the Cape knows the feeling: you hit the Sagamore at exactly the "
                 "wrong hour. 🌉 We watch both bridges live — real delays, real speeds, and "
                 "when to actually leave. Plus beach parking, water temps & tonight's events. Free.")},
    {"key": "ad_tonight", "name": "Events — Tonight sorted",
     "image": "img/ads/ad-tonight-sorted-4x5.jpg",
     "headline": "100+ Cape Cod events, live",
     "description": "Every town, every night · free",
     "message": ("\"There's nothing to do tonight\" — said no one with this app. 🎟️ 100+ live "
                 "Cape Cod events, every town, every night: concerts at the Melody Tent, live "
                 "music at the wineries and clam shacks, festivals, markets. Plus beach parking "
                 "& bridge delays. Free.")},
]

TARGETING = {
    "geo_locations": {"custom_locations": [
        {"latitude": 41.68, "longitude": -70.30, "radius": 30, "distance_unit": "mile"},
        {"latitude": 42.36, "longitude": -71.06, "radius": 40, "distance_unit": "mile"}]},
    "age_min": 25, "age_max": 65,
    "publisher_platforms": ["facebook", "instagram"],
    "facebook_positions": ["feed", "story"],
    "instagram_positions": ["stream", "story"],
}

if not TOKEN or not PAGE_ID:
    print("[launch] FB_ADS_TOKEN / FB_PAGE_ID not set — nothing to do")
    sys.exit(0)

def api(method, path, **data):
    r = getattr(requests, method)(f"{GRAPH}/{path}",
        **({"params": {**data, "access_token": TOKEN}} if method == "get"
           else {"data": {**data, "access_token": TOKEN}}), timeout=90)
    if not r.ok:
        print(f"[launch] {method.upper()} {path} failed: {r.status_code} {r.text[:500]}",
              file=sys.stderr)
        sys.exit(1)
    return r.json()

if not ACCOUNT:
    accts = api("get", "me/adaccounts", fields="account_id,name").get("data", [])
    if not accts:
        print("[launch] no ad account on this token", file=sys.stderr); sys.exit(1)
    ACCOUNT = "act_" + accts[0]["account_id"]
    print(f"[launch] using ad account {ACCOUNT} ({accts[0].get('name','')})")

# Resume-safe: reuse the campaign/ad set/ads that already exist, create the rest.
existing = api("get", f"{ACCOUNT}/campaigns", fields="name", limit=100).get("data", [])
camp = next((c for c in existing if c.get("name") == CAMPAIGN_NAME), None)
if camp:
    print(f"[launch] reusing existing campaign {camp['id']}")
else:
    camp = api("post", f"{ACCOUNT}/campaigns",
               name=CAMPAIGN_NAME, objective="OUTCOME_TRAFFIC",
               status="PAUSED", special_ad_categories="[]",
               is_adset_budget_sharing_enabled="false")
    print(f"[launch] campaign {camp['id']} created (PAUSED)")

adsets = api("get", f"{camp['id']}/adsets", fields="name", limit=10).get("data", [])
adset = adsets[0] if adsets else None
if adset:
    print(f"[launch] reusing existing ad set {adset['id']}")
else:
    adset = api("post", f"{ACCOUNT}/adsets",
                name="Cape + Boston · all placements", campaign_id=camp["id"],
                daily_budget=1500, billing_event="IMPRESSIONS",
                optimization_goal="LINK_CLICKS", bid_strategy="LOWEST_COST_WITHOUT_CAP",
                targeting=json.dumps(TARGETING), status="PAUSED")
    print(f"[launch] ad set {adset['id']} created ($15/day, PAUSED)")

have_ads = {a.get("name") for a in
            api("get", f"{adset['id']}/ads", fields="name", limit=50).get("data", [])}
for ad in ADS:
    if ad["name"] in have_ads:
        print(f"[launch] ad '{ad['name']}' already exists — skipping")
        continue
    img_b64 = base64.b64encode((ROOT / ad["image"]).read_bytes()).decode()
    up = api("post", f"{ACCOUNT}/adimages", bytes=img_b64)
    image_hash = list(up["images"].values())[0]["hash"]
    link = f"{SITE}/?utm_source=facebook&utm_medium=paid&utm_campaign={ad['key']}"
    creative = api("post", f"{ACCOUNT}/adcreatives",
        name=f"TCC {ad['key']} creative",
        object_story_spec=json.dumps({
            "page_id": PAGE_ID,
            "link_data": {
                "image_hash": image_hash, "link": link,
                "message": ad["message"], "name": ad["headline"],
                "description": ad["description"],
                "call_to_action": {"type": "LEARN_MORE", "value": {"link": link}},
            }}))
    created = api("post", f"{ACCOUNT}/ads",
                  name=ad["name"], adset_id=adset["id"],
                  creative=json.dumps({"creative_id": creative["id"]}), status="PAUSED")
    print(f"[launch] ad '{ad['name']}' -> {created['id']} (PAUSED)")

print("[launch] ✓ all created PAUSED. Review in Ads Manager, then set the CAMPAIGN to Active — "
      "the ad set and ads inherit it.")
