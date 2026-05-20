# Hermes Integration Guide

Totally Cape Cod is a static-first PWA. All live data lives in `/data/*.json` files. The app fetches them on each load with a 5-min cache. To keep data fresh, point your Hermes cron jobs at these files: overwrite them on a schedule, push to Netlify, and the app updates within 5 minutes — no rebuild, no server.

This guide spells out the schema for each file, the recommended update cadence, and three deployment patterns so you can pick whichever fits your existing Hermes setup.

---

## TL;DR — The 7 data files

| File | What it powers | Recommended cadence |
|---|---|---|
| `data/today.json` | "What's Happening Today" feed | **Daily at 5am ET** |
| `data/beaches.json` | Live beach intel (parking, water temp, crowd) | **Every 15-30 min** during summer |
| `data/conditions.json` | Tides, sunset, weather, 7-day forecast | **Daily at 5am ET** |
| `data/bridges.json` | Sagamore + Bourne traffic, forecasts | **Every hour** during peak season |
| `data/whales.json` | Recent marine wildlife sightings | **Every 30 min** during summer |
| `data/stamps.json` | 100 Cape passport locations | Rarely (annually) |
| `data/lighthouses.json` | 12 lighthouse audio tour scripts | Rarely (annually) |
| `data/ai-knowledge.json` | AI Concierge response patterns | Occasionally (monthly) |

**Total Hermes jobs needed:** 4 active crons (today, beaches, conditions, bridges) + 1 occasional (whales) = 5 jobs covers it.

---

## Schema reference

Every file starts with the same envelope:

```json
{
  "version": "1.0",
  "updated_at": "ISO 8601 timestamp",
  "_hermes_note": "Free-form notes for the cron operator",
  ... feature-specific keys ...
}
```

### 1. `today.json` — Daily events

```json
{
  "version": "1.0",
  "date": "2026-05-17",
  "updated_at": "2026-05-17T05:30:00Z",
  "events": [
    {
      "id": "unique-string",
      "tag": "🎵 LIVE MUSIC",
      "category": "music | happy_hour | free_event | family | food_deal | drive_in | farmers_market | trivia | art",
      "time": "9:00 PM",
      "title": "The Wailers at Beachcomber",
      "venue": "The Beachcomber",
      "town": "Wellfleet",
      "info": "Wellfleet · $25 cover · 21+",
      "price": "$25",
      "lat": 41.9314,
      "lng": -69.9692,
      "img": "https://...",
      "source_url": "https://thebeachcomber.com/calendar"
    }
  ]
}
```

**Source sites to scrape** (Hermes scraper checklist):
- Cape Cod Chamber events page
- Each of 15 town websites (Provincetown, Wellfleet, Truro, Eastham, Orleans, Brewster, Harwich, Chatham, Dennis, Yarmouth, Barnstable, Mashpee, Sandwich, Bourne, Falmouth)
- The Beachcomber, The Squire, The Mews, Cape Cod Beer, Truro Vineyards, Wellfleet Drive-In
- Cape Cod Times events feed
- Top 30 Cape restaurants for daily specials

**Pro tip:** Send raw scraped HTML through Claude API with this prompt to extract clean events:
> "You are an event extractor. Given this HTML, return a JSON array of events for date {date} with keys: title, venue, town, time, category, price, info. Category must be one of: music, happy_hour, free_event, family, food_deal, drive_in, farmers_market, trivia, art."

### 2. `beaches.json` — Live beach status

```json
{
  "version": "1.0",
  "updated_at": "2026-05-17T08:00:00Z",
  "beaches": [
    {
      "slug": "nauset-beach",
      "name": "Nauset Beach",
      "town": "Orleans",
      "region": "Outer Cape",
      "lat": 41.8014,
      "lng": -69.9492,
      "status": "open | mid | full",
      "spots_text": "23 spots open",
      "crowd": 2,
      "water_temp": 65,
      "sticker_required": true,
      "restrooms": true,
      "lifeguard": true,
      "updated": "2 min ago",
      "notes": ""
    }
  ]
}
```

**Data sources:**
- Crowdsourced (user reports) — Hermes can aggregate these from a webhook (see "User submissions" below)
- NOAA water temp API for the nearest buoy
- Town parking webcams where available
- Manual admin input by you each morning

### 3. `conditions.json` — Tides, sun, weather

```json
{
  "version": "1.0",
  "updated_at": "2026-05-17T05:00:00Z",
  "today": {
    "date": "2026-05-17",
    "weather": { "temp_high":72, "temp_low":58, "condition":"Sunny", "icon":"☀️", "wind_mph":8, "wind_dir":"SW", "humidity":65, "uv_index":7 },
    "sun": { "sunrise":"5:24 AM", "sunset":"8:02 PM", "civil_twilight_end":"8:32 PM", "best_sunset_spot":{"name":"Skaket Beach","town":"Orleans","reason":"..."} },
    "tides": [ { "time":"3:48 AM", "type":"high|low", "height_ft":9.2 } ],
    "water_temp_f": 64,
    "swell_height_ft": 2,
    "swell_period_sec": 8
  },
  "forecast_7day": [
    { "date":"2026-05-18", "day":"Mon", "temp_high":75, "temp_low":60, "condition":"Sunny", "icon":"☀️", "sunrise":"5:23 AM", "sunset":"8:03 PM", "low_tide":"10:48 AM", "high_tide":"4:56 PM", "water_temp":64 }
  ]
}
```

**Free APIs to pull from:**
- **Tides:** NOAA Tides & Currents — `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter` (station 8447435 for Chatham)
- **Weather + 7-day forecast:** weather.gov — `https://api.weather.gov/points/{lat},{lng}` then follow the forecast URL
- **Sunrise/sunset:** sunrise-sunset.org — `https://api.sunrise-sunset.org/json?lat=41.78&lng=-70.03`
- **Surf:** Surfline RSS feeds or NOAA wave buoys

All free, no API keys needed.

### 4. `bridges.json` — Traffic + forecast

```json
{
  "current": {
    "sagamore": {
      "name": "Sagamore Bridge",
      "current_delay_min": 12,
      "current_status": "light | moderate | heavy",
      "direction": "off_cape",
      "advice": "Leave by 5:42pm to beat the worst",
      "live_speed_mph": 35,
      "free_flow_mph": 55,
      "last_check": "2 min ago"
    },
    "bourne": { ... same shape ... }
  },
  "forecast_24h": [ { "hour":"9 AM", "sagamore_delay":8, "bourne_delay":4 } ],
  "forecast_7day": [ { "day":"Mon", "worst_hour":"5 PM", "worst_delay":42, "best_hour":"6 AM", "best_delay":2 } ],
  "best_times_to_leave": { "off_cape_sunday":"Before 8 AM or after 7 PM", ... }
}
```

**Data source:** Google Maps Distance Matrix API. Hit it every hour:
```
GET https://maps.googleapis.com/maps/api/distancematrix/json
?origins=41.7681,-70.5042
&destinations=42.0,-70.6
&departure_time=now
&key=YOUR_KEY
```

Then `current_delay_min = (duration_in_traffic - free_flow_duration) / 60`.

**Cost:** ~$5 per 1,000 calls. Hourly cron = 24/day × 30 days = 720/month = $3.60/month for Google. Cheap.

### 5. `whales.json` — Recent sightings

```json
{
  "recent_sightings": [
    {
      "id": "w001",
      "species": "humpback | fin | minke | seal | dolphin | shark",
      "count": 3,
      "lat": 42.18,
      "lng": -70.32,
      "location": "Stellwagen Bank North",
      "reported_by": "Provincetown Whale Watch",
      "reported_at": "2026-05-17T13:42:00Z",
      "time_ago": "48 min ago",
      "photo_url": "",
      "notes": "Mother + calf + escort"
    }
  ]
}
```

**Sources:**
- Set up a Twilio number, give it to 3-4 Cape whale watch operators. They text sightings → webhook parses → appends to `whales.json`.
- User submissions from the app (POST endpoint — see "User submissions" below)
- Public NOAA whale alert data

**Auto-prune:** drop entries older than 7 days each time you write the file.

### 6. `stamps.json` & `lighthouses.json`

Mostly static. Update annually (e.g., when you add a new stamp location, or rewrite a lighthouse script). Hermes doesn't usually touch these.

### 7. `ai-knowledge.json`

Pattern-matched responses for the AI Concierge. Hermes can optionally update this monthly with new seasonal patterns (e.g., add "cranberry harvest" responses for September). Or, if you want true live AI, set `window.TCC_AI_ENDPOINT` in `index.html` to a Claude API proxy URL (e.g., a Cloudflare Worker).

---

## Three deployment patterns

Pick the one that matches your existing Hermes setup.

### Pattern A — Git push (simplest)

Your Hermes job runs, generates a fresh JSON file, then:

```bash
cd /path/to/totallycapecod
echo "$NEW_JSON" > data/today.json
git add data/today.json
git commit -m "[hermes] today.json update $(date +%F-%H%M)"
git push origin main
```

Netlify auto-builds and deploys within 30-60 seconds. Done. Zero infrastructure, zero auth tokens, fully free.

**Pros:** Free, full git history of every data update.
**Cons:** 30-60s deploy delay; commit noise.

### Pattern B — Netlify Direct File Upload (faster)

Skip git and update files via Netlify's API:

```bash
curl -X PUT https://api.netlify.com/api/v1/sites/SITE_ID/files/data/today.json \
  -H "Authorization: Bearer NETLIFY_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @today.json
```

Files appear in seconds, no git noise. Get a token at https://app.netlify.com/user/applications.

**Pros:** Near-instant updates, clean git history.
**Cons:** Need to store a Netlify token securely in Hermes.

### Pattern C — Edge KV (most scalable)

Migrate the data layer to **Cloudflare KV** (or Vercel KV). The app fetches from `https://api.totallycapecod.com/data/today.json` instead of a local file. Hermes writes directly to KV via API. Free tier is generous (100k reads/day on Cloudflare).

```bash
curl -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/storage/kv/namespaces/$NAMESPACE_ID/values/today" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -H "Content-Type: application/json" \
  --data @today.json
```

Then in `index.html`, change `fetch('data/today.json')` to `fetch('https://api.totallycapecod.com/data/today')`.

**Pros:** Truly real-time, infinite scalability, separate concerns.
**Cons:** Slight added complexity, $0 today but eventually $5-25/mo at scale.

**Recommendation:** start with **Pattern A** (git push). Migrate to B or C once you hit ~5k daily active users.

---

## User submissions back to Hermes

Users submit beach updates and whale sightings via the app. Right now those write to `localStorage` (private to each user). To aggregate them, expose a webhook:

```javascript
// In index.html, find reportBeach() and submitSighting()
// Add a fetch() call after writing to localStorage:

fetch('https://hermes.totallycapecod.com/api/beach-report', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ slug: state.pendingBeach.slug, status, ts: Date.now() })
}).catch(() => {}); // Fire-and-forget; offline-tolerant
```

Hermes receives, deduplicates, runs spam filters, then writes the next `beaches.json` with the aggregated state.

---

## Recommended Hermes cron schedule

```
# Beaches — every 20 min during summer (May–Oct), every hour off-season
*/20 8-21 * 5-10 * job=update_beaches

# Today's events — daily at 5am ET, refresh at 11am if anything new
30 5 * * * job=scrape_todays_events
0 11 * * * job=refresh_todays_events

# Conditions (tides/sun/weather) — daily at 4am ET
0 4 * * * job=update_conditions

# Bridges — every hour from 6am-11pm
0 6-23 * * * job=update_bridges

# Whales — every 30 min during summer
*/30 6-20 * 5-10 * job=update_whales
```

---

## Monitoring & sanity checks

Every Hermes job should:

1. **Fetch the current `data/<file>.json`** before writing — bail if your new data is empty or smaller than half the previous size (likely a scraper failure).
2. **Update `updated_at`** to ISO 8601 UTC.
3. **Validate the JSON parses** before pushing.
4. **Log to a dashboard** (Hermes presumably has one).
5. **Alert on consecutive failures** — 3 failed runs in a row = page you.

Sample Python guard:
```python
import json, os
NEW = generate_new_data()  # your scraper
OLD = json.load(open('data/today.json'))
if len(NEW['events']) < len(OLD['events']) * 0.5:
    raise Exception("Scraper produced suspiciously few events; aborting")
NEW['updated_at'] = datetime.utcnow().isoformat() + "Z"
with open('data/today.json', 'w') as f:
    json.dump(NEW, f, indent=2)
```

---

## Cost summary (Year 1, all-in)

| Cost | Amount |
|---|---|
| Netlify hosting | $0 (free tier, up to 100GB/mo bandwidth) |
| Domain (totallycapecod.com) | $12/year |
| Stripe (per transaction) | 2.9% + $0.30 |
| Google Maps API (bridges) | ~$5/month |
| Anthropic Claude API (if you wire AI) | ~$30-80/month |
| Your Hermes cron infra | (whatever it costs today) |
| **Total launch + first month** | **~$50** |

That's it. You can launch and run this for under $100/month even at 10k daily users.

---

## When you're ready to go native (App Store)

Wrap the same PWA in **Capacitor** to ship as a real iOS app. The data layer doesn't change — Capacitor app fetches the same JSON files from Hermes-updated Netlify. Switch Stripe to Apple StoreKit IAP for the paywall (required by Apple). All other features work as-is.

See the Technical Spec doc (`Totally_Cape_Cod_Technical_Spec.docx`) for the full App Store path.
