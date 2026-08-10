#!/usr/bin/env python3
"""Daily Meta ads report — pulls last-7-day performance for every ad in the
account and writes data/.ads_report.json (+ a readable table to the run log).

Runs from .github/workflows/ads-auto.yml. Skips cleanly until the secrets
exist, so the workflow can ship before the token does.

Env: FB_ADS_TOKEN (long-lived user token w/ ads_read), FB_AD_ACCOUNT_ID (act_…)
"""
import json, os, sys, time
from pathlib import Path
import requests

GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ.get("FB_ADS_TOKEN", "").strip()
ACCOUNT = os.environ.get("FB_AD_ACCOUNT_ID", "").strip()
OUT = Path(__file__).parent.parent / "data" / ".ads_report.json"

if not TOKEN:
    print("[ads] FB_ADS_TOKEN not set — skipping (add the secret to activate)")
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

# Token sanity first: a dead token should fail loudly (red run → GitHub emails you).
me = requests.get(f"{GRAPH}/me", params={"access_token": TOKEN}, timeout=30)
if not me.ok:
    print(f"[ads] TOKEN INVALID/EXPIRED — regenerate per SETUP_FACEBOOK.md Steps 2-4.\n{me.text[:300]}",
          file=sys.stderr)
    sys.exit(1)

r = requests.get(f"{GRAPH}/{ACCOUNT}/insights", params={
    "level": "ad",
    "date_preset": "last_7d",
    "fields": "campaign_name,adset_name,ad_name,spend,impressions,reach,clicks,ctr,cpc,actions",
    "limit": 50,
    "access_token": TOKEN,
}, timeout=60)
if not r.ok:
    print(f"[ads] insights failed: {r.status_code} {r.text[:300]}", file=sys.stderr)
    sys.exit(1)

rows = r.json().get("data", [])
report = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "window": "last_7d", "ads": rows}
OUT.write_text(json.dumps(report, indent=2) + "\n")

if not rows:
    print("[ads] no active ads with delivery in the last 7 days")
else:
    print(f"[ads] last 7 days — {len(rows)} ad(s):")
    print(f"{'ad':38} {'spend':>8} {'impr':>8} {'clicks':>7} {'ctr':>6} {'cpc':>6}")
    for a in rows:
        print(f"{a.get('ad_name','?')[:38]:38} ${float(a.get('spend',0)):>7.2f} "
              f"{a.get('impressions','0'):>8} {a.get('clicks','0'):>7} "
              f"{float(a.get('ctr',0)):>5.2f}% ${float(a.get('cpc',0) or 0):>5.2f}")
