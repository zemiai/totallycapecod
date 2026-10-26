#!/usr/bin/env python3
"""Nightly business metrics — one file the whole cockpit reads.

Collects into data/metrics.json (data-only commit → no Netlify rebuild):
  meta_ads   — per-ad spend/clicks/CTR/CPC last 7d + WASTE FLAGS   (FB_ADS_TOKEN)
  stripe     — sales count + revenue, last 30d                     (STRIPE_REPORTING_KEY)
  ga4        — sessions/users last 7d + by campaign + purchases    (Google creds; property auto-found)
  gsc        — ranking movement: 28d vs prior 28d, top queries/pages, tracked keywords,
               sitemap status; daily snapshot in data/gsc_history.json

Google credentials: keyless workload identity in ads-auto.yml (service account
tcc-metrics@totally-capecod.iam.gserviceaccount.com), or a GOOGLE_SA_KEY secret.

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


def _has_google() -> bool:
    """Either a service-account key (GOOGLE_SA_KEY) or keyless workload-identity credentials
    from google-github-actions/auth (GOOGLE_APPLICATION_CREDENTIALS)."""
    return bool(os.environ.get("GOOGLE_SA_KEY", "").strip() or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip())


def _google_token(scopes):
    from google.auth.transport.requests import Request
    raw = os.environ.get("GOOGLE_SA_KEY", "").strip()
    if raw:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
        import google.auth
        creds, _ = google.auth.default(scopes=scopes)
    else:
        return None
    creds.refresh(Request())
    return creds.token


GA4_MEASUREMENT_ID = "G-Q0YM9WQLWK"      # the site's gtag ID; used to find the GA4 property


def _ga4_property(token):
    """GA4_PROPERTY_ID if set, else find the property whose web stream uses GA4_MEASUREMENT_ID
    among the properties this account can see (Analytics Admin API)."""
    prop = os.environ.get("GA4_PROPERTY_ID", "").strip()
    if prop:
        return prop
    H = {"Authorization": f"Bearer {token}"}
    r = requests.get("https://analyticsadmin.googleapis.com/v1beta/accountSummaries", headers=H,
                     params={"pageSize": 200}, timeout=60)
    if not r.ok:
        return None
    for acct in r.json().get("accountSummaries", []):
        for ps in acct.get("propertySummaries", []):
            pid = ps["property"].split("/")[-1]
            st = requests.get(f"https://analyticsadmin.googleapis.com/v1beta/properties/{pid}/dataStreams",
                              headers=H, timeout=60)
            for ds in (st.json().get("dataStreams", []) if st.ok else []):
                if (ds.get("webStreamData") or {}).get("measurementId") == GA4_MEASUREMENT_ID:
                    return pid
    return None


def collect_ga4():
    if not _has_google():
        return {"skipped": "no Google credentials (workload identity or GOOGLE_SA_KEY)"}
    try:
        token = _google_token(["https://www.googleapis.com/auth/analytics.readonly"])
    except Exception as e:
        return {"error": f"auth: {e}"}
    prop = _ga4_property(token)
    if not prop:
        return {"error": f"no GA4 property with stream {GA4_MEASUREMENT_ID} visible — add "
                         "tcc-metrics@totally-capecod.iam.gserviceaccount.com as a Viewer in GA4"}
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


# Core searches we care about, on top of every keyword in content/plan.json.
CORE_KEYWORDS = ["totally cape cod", "sagamore bridge traffic", "bourne bridge traffic",
                 "cape cod bridge traffic", "cape cod water temperature", "cape cod beach conditions",
                 "cape cod events this weekend", "things to do on cape cod", "cape cod beaches"]
GSC_HISTORY = DATA / "gsc_history.json"


def _tracked_keywords():
    kws = list(CORE_KEYWORDS)
    try:
        plan = json.loads((DATA.parent / "content" / "plan.json").read_text(encoding="utf-8"))
        for t in plan.get("topics", []):
            kws += t.get("keywords", [])
    except Exception:
        pass
    out, seen = [], set()
    for k in kws:
        k = k.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:80]


def collect_gsc():
    """Search Console via the API (service account in GOOGLE_SA_KEY, added as a user on the
    property). Reports ranking MOVEMENT: last 28 days vs the 28 before (GSC data lags ~3 days),
    top queries/pages with position change, our tracked keywords, sitemap status. Also appends a
    daily snapshot to data/gsc_history.json so the trend builds up over weeks."""
    if not _has_google():
        return {"skipped": "no Google credentials (workload identity or GOOGLE_SA_KEY)"}
    try:
        token = _google_token(["https://www.googleapis.com/auth/webmasters"])
    except Exception as e:
        return {"error": f"auth: {e}"}
    API = "https://searchconsole.googleapis.com/webmasters/v3"
    H = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/sites", headers=H, timeout=60)
    if not r.ok:
        return {"error": f"sites.list {r.status_code}: {r.text[:200]}"}
    mine = [x for x in r.json().get("siteEntry", []) if "totallycapecod" in x.get("siteUrl", "")
            and x.get("permissionLevel") != "siteUnverifiedUser"]
    if not mine:
        return {"error": "no accessible totallycapecod.com property — add "
                         "tcc-metrics@totally-capecod.iam.gserviceaccount.com as a Full user in Search Console "
                         "(Settings → Users and permissions)"}
    mine.sort(key=lambda x: (not x["siteUrl"].startswith("sc-domain:"), x["siteUrl"]))
    site, perm = mine[0]["siteUrl"], mine[0].get("permissionLevel")
    base = f"{API}/sites/{requests.utils.quote(site, safe='')}"

    def query(start, end, dims=None, limit=1000):
        body = {"startDate": str(start), "endDate": str(end), "rowLimit": limit}
        if dims:
            body["dimensions"] = dims
        q = requests.post(f"{base}/searchAnalytics/query", headers=H, json=body, timeout=60)
        q.raise_for_status()
        return q.json().get("rows", [])

    end = datetime.now(timezone.utc).date() - timedelta(days=3)          # GSC data lag
    cur = (end - timedelta(days=27), end)
    prev = (end - timedelta(days=55), end - timedelta(days=28))

    def totals(win):
        rows = query(*win)
        x = rows[0] if rows else {}
        return {"from": str(win[0]), "to": str(win[1]), "clicks": x.get("clicks", 0),
                "impressions": x.get("impressions", 0), "ctr": round(x.get("ctr", 0) * 100, 2),
                "avg_position": round(x.get("position", 0), 1) if x else None}

    def fmt(row, before):
        b = before.get(row["keys"][0])
        pos, bpos = round(row["position"], 1), (round(b["position"], 1) if b else None)
        return {"key": row["keys"][0], "clicks": row["clicks"], "impressions": row["impressions"],
                "position": pos, "position_before": bpos,
                "moved_up_by": (round(bpos - pos, 1) if bpos is not None else None)}   # + = better

    out = {"site": site, "permission": perm, "window": "28d vs previous 28d (data lags ~3 days)",
           "current": totals(cur), "previous": totals(prev)}
    cq, pq = query(*cur, ["query"]), query(*prev, ["query"])
    pmap = {r["keys"][0]: r for r in pq}
    cq.sort(key=lambda r: -r["impressions"])
    out["top_queries"] = [fmt(r, pmap) for r in cq[:30]]
    cmap = {r["keys"][0]: r for r in cq}
    out["tracked_keywords"] = []
    for kw in _tracked_keywords():
        c, p = cmap.get(kw), pmap.get(kw)
        out["tracked_keywords"].append({
            "keyword": kw,
            "position": round(c["position"], 1) if c else None,
            "position_before": round(p["position"], 1) if p else None,
            "impressions": c["impressions"] if c else 0, "clicks": c["clicks"] if c else 0})
    cp, pp = query(*cur, ["page"], 50), query(*prev, ["page"], 200)
    ppmap = {r["keys"][0]: r for r in pp}
    cp.sort(key=lambda r: -r["impressions"])
    out["top_pages"] = [fmt(r, ppmap) for r in cp[:25]]
    # last-7-day query list kept for the /admin dashboard
    wk = query(end - timedelta(days=6), end, ["query"], 10)
    out["queries"] = [{"q": x["keys"][0], "clicks": x["clicks"], "impressions": x["impressions"],
                       "position": round(x["position"], 1)} for x in wk]
    # sitemap: report status; submit it if missing and we have Full/Owner access
    try:
        sm = requests.get(f"{base}/sitemaps", headers=H, timeout=60).json().get("sitemap", [])
        want = "https://totallycapecod.com/sitemap.xml"
        if not any(x.get("path") == want for x in sm) and perm in ("siteOwner", "siteFullUser"):
            put = requests.put(f"{base}/sitemaps/{requests.utils.quote(want, safe='')}", headers=H, timeout=60)
            out["sitemap_submitted_now"] = put.ok
            sm = requests.get(f"{base}/sitemaps", headers=H, timeout=60).json().get("sitemap", [])
        out["sitemaps"] = [{"path": x.get("path"), "last_submitted": x.get("lastSubmitted"),
                            "last_downloaded": x.get("lastDownloaded"), "errors": x.get("errors"),
                            "warnings": x.get("warnings"),
                            "submitted_urls": sum(int(c.get("submitted", 0)) for c in x.get("contents", []))}
                           for x in sm]
    except Exception as e:
        out["sitemaps_error"] = str(e)[:200]
    # daily snapshot → history (trend over weeks)
    try:
        hist = json.loads(GSC_HISTORY.read_text()) if GSC_HISTORY.exists() else []
    except Exception:
        hist = []
    snap = {"date": str(datetime.now(timezone.utc).date()), **{k: out["current"][k] for k in
            ("clicks", "impressions", "ctr", "avg_position")},
            "tracked": {k["keyword"]: k["position"] for k in out["tracked_keywords"] if k["position"]}}
    hist = [h for h in hist if h.get("date") != snap["date"]] + [snap]
    GSC_HISTORY.write_text(json.dumps(hist[-180:], indent=1) + "\n")
    return out


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
