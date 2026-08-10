#!/usr/bin/env python3
"""Nightly business metrics — one file the whole cockpit reads.

Collects into data/metrics.json (data-only commit → no Netlify rebuild):
  meta_ads   — per-ad spend/clicks/CTR/CPC last 7d + WASTE FLAGS   (FB_ADS_TOKEN)
  stripe     — sales count + revenue, last 30d                     (STRIPE_REPORTING_KEY)
  ga4        — sessions/users last 7d + by campaign + purchases    (GOOGLE_SA_KEY, GA4_PROPERTY_ID)
  gsc        — top search queries last 7d                          (GOOGLE_SA_KEY)

Each collector skips cleanly when its secret is absent and can't break the
others. The waste guard prints ::warning:: annotations for any ad with
spend >= $10 in 7d and either zero clicks or CPC > $1.50 — the "we're paying
for nothing" signal. It never pauses anything by itself.

Rendered by the /admin dashboard (Metrics section). Runs nightly via ads-auto.yml.
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

DATA = Path(__file__).parent.parent / "data"
OUT = DATA / "metrics.json"
GRAPH = "https://graph.facebook.com/v21.0"
CPC_FLAG = 1.50
SPEND_FLAG = 10.0

metrics = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def collect_meta_ads():
    token = os.environ.get("FB_ADS_TOKEN", "").strip()
    account = os.environ.get("FB_AD_ACCOUNT_ID", "").strip()
    if not token or not account:
        return {"skipped": "FB_ADS_TOKEN / FB_AD_ACCOUNT_ID not set"}
    r = requests.get(f"{GRAPH}/{account}/insights", params={
        "level": "ad", "date_preset": "last_7d",
        "fields": "campaign_name,ad_name,spend,impressions,reach,clicks,ctr,cpc",
        "limit": 50, "access_token": token}, timeout=60)
    if not r.ok:
        return {"error": r.text[:300]}
    ads, flags, total_spend, total_clicks = [], [], 0.0, 0
    for a in r.json().get("data", []):
        spend = float(a.get("spend", 0) or 0)
        clicks = int(a.get("clicks", 0) or 0)
        cpc = float(a.get("cpc", 0) or 0)
        total_spend += spend
        total_clicks += clicks
        ads.append({"ad": a.get("ad_name"), "campaign": a.get("campaign_name"),
                    "spend": round(spend, 2), "impressions": int(a.get("impressions", 0) or 0),
                    "clicks": clicks, "ctr": round(float(a.get("ctr", 0) or 0), 2),
                    "cpc": round(cpc, 2)})
        if spend >= SPEND_FLAG and (clicks == 0 or cpc > CPC_FLAG):
            why = "ZERO clicks" if clicks == 0 else f"CPC ${cpc:.2f} > ${CPC_FLAG:.2f}"
            flags.append(f"'{a.get('ad_name')}' spent ${spend:.2f} in 7d with {why} — consider pausing")
    for f in flags:
        print(f"::warning title=Ad spend flag::{f}")
    return {"window": "last_7d", "total_spend": round(total_spend, 2),
            "total_clicks": total_clicks, "ads": sorted(ads, key=lambda x: -x["spend"]),
            "flags": flags}


def collect_stripe():
    key = (os.environ.get("STRIPE_REPORTING_KEY", "").strip()
           or os.environ.get("STRIPE_SECRET_KEY", "").strip())
    if not key:
        return {"skipped": "STRIPE_REPORTING_KEY not set"}
    since = int(time.time()) - 30 * 86400
    r = requests.get("https://api.stripe.com/v1/charges",
                     params={"limit": 100, "created[gte]": since},
                     headers={"Authorization": f"Bearer {key}"}, timeout=60)
    if not r.ok:
        return {"error": r.text[:300]}
    charges = [c for c in r.json().get("data", []) if c.get("paid") and not c.get("refunded")]
    by_day, by_source = {}, {}
    for c in charges:
        d = datetime.fromtimestamp(c["created"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[d] = by_day.get(d, 0) + c["amount"]
        # client_reference_id carries the utm_campaign the buyer first arrived on
        src = (c.get("metadata") or {}).get("client_reference_id") or c.get("description") or "unknown"
        by_source[src] = by_source.get(src, 0) + 1
    return {"window": "last_30d", "sales": len(charges),
            "revenue": round(sum(c["amount"] for c in charges) / 100, 2),
            "by_day": {d: round(v / 100, 2) for d, v in sorted(by_day.items())},
            "by_source": by_source}


def _google_token(scopes):
    raw = os.environ.get("GOOGLE_SA_KEY", "").strip()
    if not raw:
        return None
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    creds.refresh(Request())
    return creds.token


def collect_ga4():
    prop = os.environ.get("GA4_PROPERTY_ID", "").strip()
    if not os.environ.get("GOOGLE_SA_KEY", "").strip() or not prop:
        return {"skipped": "GOOGLE_SA_KEY / GA4_PROPERTY_ID not set"}
    try:
        token = _google_token(["https://www.googleapis.com/auth/analytics.readonly"])
    except Exception as e:
        return {"error": f"auth: {e}"}
    def run(body):
        r = requests.post(
            f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport",
            headers={"Authorization": f"Bearer {token}"}, json=body, timeout=60)
        return r.json() if r.ok else {"error": r.text[:300]}
    week = {"dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}]}
    totals = run({**week, "metrics": [{"name": "sessions"}, {"name": "totalUsers"},
                                      {"name": "transactions"}]})
    by_camp = run({**week, "dimensions": [{"name": "sessionCampaignName"}],
                   "metrics": [{"name": "sessions"}], "limit": 20,
                   "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}]})
    out = {"window": "last_7d"}
    try:
        row = totals["rows"][0]["metricValues"]
        out.update({"sessions": int(row[0]["value"]), "users": int(row[1]["value"]),
                    "purchases": int(row[2]["value"])})
    except Exception:
        out["totals_raw"] = totals
    try:
        out["by_campaign"] = {(r["dimensionValues"][0]["value"] or "(direct)"):
                              int(r["metricValues"][0]["value"])
                              for r in by_camp.get("rows", [])}
    except Exception:
        pass
    return out


def collect_gsc():
    if not os.environ.get("GOOGLE_SA_KEY", "").strip():
        return {"skipped": "GOOGLE_SA_KEY not set"}
    try:
        token = _google_token(["https://www.googleapis.com/auth/webmasters.readonly"])
    except Exception as e:
        return {"error": f"auth: {e}"}
    end = datetime.now(timezone.utc).date()
    body = {"startDate": str(end - timedelta(days=7)), "endDate": str(end),
            "dimensions": ["query"], "rowLimit": 10}
    for site in ("sc-domain:totallycapecod.com", "https://totallycapecod.com/"):
        r = requests.post(
            "https://searchconsole.googleapis.com/webmasters/v3/sites/"
            f"{requests.utils.quote(site, safe='')}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {token}"}, json=body, timeout=60)
        if r.ok:
            rows = r.json().get("rows", [])
            return {"window": "last_7d", "site": site,
                    "queries": [{"q": x["keys"][0], "clicks": x["clicks"],
                                 "impressions": x["impressions"]} for x in rows]}
    return {"error": "no accessible Search Console property (add the service account as a user)"}


for name, fn in (("meta_ads", collect_meta_ads), ("stripe", collect_stripe),
                 ("ga4", collect_ga4), ("gsc", collect_gsc)):
    try:
        metrics[name] = fn()
    except Exception as e:
        metrics[name] = {"error": str(e)[:300]}
    state = ("skipped" if "skipped" in metrics[name] else
             "ERROR" if "error" in metrics[name] else "ok")
    detail = metrics[name].get("skipped") or metrics[name].get("error")
    print(f"[metrics] {name}: {state}" + (f" — {detail}" if detail else ""))

OUT.write_text(json.dumps(metrics, indent=1) + "\n")
ads = metrics.get("meta_ads", {})
if isinstance(ads.get("ads"), list):
    print(f"[metrics] ad spend 7d: ${ads['total_spend']:.2f} · {ads['total_clicks']} clicks"
          + (f" · {len(ads['flags'])} FLAG(S)" if ads.get("flags") else " · no waste flags"))
print(f"[metrics] wrote {OUT.name}")
