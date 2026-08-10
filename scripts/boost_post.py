#!/usr/bin/env python3
"""Friday auto-boost: turn the morning weekend-roundup post into a $5/day,
3-day engagement ad targeted at the Cape + approach corridor.

Safety model: by default the campaign is created PAUSED — you get it fully
configured in Ads Manager and flip one switch to spend. Set repo secret/var
AUTO_BOOST_LIVE=1 to let it go ACTIVE on its own (real money, hands-free).

Reads the post id from data/.fb_state.json (written by post_facebook.py).
Skips cleanly when secrets are missing, when today's morning post wasn't the
weekend format, or when a boost for this post already exists.

Env: FB_ADS_TOKEN (ads_management), FB_AD_ACCOUNT_ID, FB_PAGE_ID, AUTO_BOOST_LIVE
"""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ.get("FB_ADS_TOKEN", "").strip()
ACCOUNT = os.environ.get("FB_AD_ACCOUNT_ID", "").strip()
PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
LIVE = os.environ.get("AUTO_BOOST_LIVE", "") == "1"
DATA = Path(__file__).parent.parent / "data"

DAILY_BUDGET_CENTS = 500          # $5/day
DURATION_DAYS = 3
# Mid-Cape 30-mile radius: covers the whole Cape + the bridge approach.
TARGETING = {
    "geo_locations": {"custom_locations": [
        {"latitude": 41.68, "longitude": -70.30, "radius": 30, "distance_unit": "mile"}]},
    "age_min": 25, "age_max": 65,
}

if not TOKEN or not PAGE_ID:
    print("[boost] FB_ADS_TOKEN not set — skipping (add the secret to activate)")
    sys.exit(0)
def resolve_account(token, account):
    """Use the configured act_… id, else auto-discover the token's first ad account."""
    if account:
        return account
    r = requests.get(f"{GRAPH}/me/adaccounts",
                     params={"fields": "account_id,name", "access_token": token}, timeout=30)
    accts = r.json().get("data", []) if r.ok else []
    if not accts:
        print("[ads] no ad account found for this token — set FB_AD_ACCOUNT_ID", file=sys.stderr)
        sys.exit(1)
    aid = "act_" + accts[0]["account_id"]
    print(f"[ads] auto-discovered ad account {aid} ({accts[0].get('name','')})")
    return aid
ACCOUNT = resolve_account(TOKEN, ACCOUNT)

state = json.loads((DATA / ".fb_state.json").read_text()) if (DATA / ".fb_state.json").exists() else {}
if state.get("last_morning_campaign") != "weekend":
    print(f"[boost] this morning's post was '{state.get('last_morning_campaign')}' — only the "
          "weekend roundup gets boosted. Skipping.")
    sys.exit(0)
post_id = state.get("last_morning_post_id", "")
if not post_id:
    print("[boost] no morning post id recorded — skipping")
    sys.exit(0)
# /photos returns "id"; ensure the page-scoped story id form PAGEID_POSTID
story_id = post_id if "_" in post_id else f"{PAGE_ID}_{post_id}"

def post(path, data):
    r = requests.post(f"{GRAPH}/{path}", data={**data, "access_token": TOKEN}, timeout=60)
    if not r.ok:
        print(f"[boost] {path} failed: {r.status_code} {r.text[:400]}", file=sys.stderr)
        sys.exit(1)
    return r.json()

# Idempotence: one boost per post — look for an existing campaign named after it.
name = f"TCC auto-boost {story_id[-12:]} {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
existing = requests.get(f"{GRAPH}/{ACCOUNT}/campaigns",
                        params={"fields": "name", "limit": 100, "access_token": TOKEN},
                        timeout=60).json().get("data", [])
if any(c.get("name", "").endswith(story_id[-12:] + f" {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
       or story_id[-12:] in c.get("name", "") for c in existing):
    print(f"[boost] a boost for this post already exists — skipping")
    sys.exit(0)

status = "ACTIVE" if LIVE else "PAUSED"
camp = post(f"{ACCOUNT}/campaigns", {
    "name": name, "objective": "OUTCOME_ENGAGEMENT",
    "status": status, "special_ad_categories": "[]",
})
start = datetime.now(timezone.utc)
adset = post(f"{ACCOUNT}/adsets", {
    "name": name + " · adset", "campaign_id": camp["id"],
    "daily_budget": DAILY_BUDGET_CENTS,
    "billing_event": "IMPRESSIONS", "optimization_goal": "POST_ENGAGEMENT",
    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    "targeting": json.dumps(TARGETING),
    "start_time": start.isoformat(),
    "end_time": (start + timedelta(days=DURATION_DAYS)).isoformat(),
    "status": status,
})
ad = post(f"{ACCOUNT}/ads", {
    "name": name + " · ad", "adset_id": adset["id"],
    "creative": json.dumps({"object_story_id": story_id}),
    "status": status,
})
mode = "LIVE — spending now" if LIVE else "PAUSED — flip it on in Ads Manager to spend"
print(f"[boost] ✓ created boost for {story_id}: campaign {camp['id']} / ad {ad['id']} ({mode})")
print(f"[boost] ${DAILY_BUDGET_CENTS/100:.2f}/day for {DURATION_DAYS} days, 30mi radius mid-Cape, 25-65")
