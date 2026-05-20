# Totally Cape Cod — Launch in 60 Minutes

You have a complete, working MVP. All 8 features functional. $0/month to host. Here's how to make it live and take real money today.

---

## What you have

```
totallycapecod/
├── index.html              ← The full PWA, all 8 features
├── manifest.json           ← Makes it installable on iPhone
├── HERMES.md               ← How to wire your cron jobs
├── DEPLOY.md               ← This file
├── data/
│   ├── stamps.json         ← 100 passport locations
│   ├── beaches.json        ← 28 Cape beaches
│   ├── today.json          ← Daily events (Hermes overwrites)
│   ├── conditions.json     ← Tides/sun/weather (Hermes overwrites)
│   ├── bridges.json        ← Traffic (Hermes overwrites)
│   ├── whales.json         ← Sightings (Hermes overwrites)
│   ├── lighthouses.json    ← 12 audio tour scripts
│   └── ai-knowledge.json   ← AI Concierge response patterns
└── Totally_Cape_Cod_Technical_Spec.docx   ← Full dev spec
```

All 8 features work end-to-end with seed data. Hermes plugs in by overwriting the JSON files on a schedule.

---

## Step 1 — Deploy to Netlify (10 min, free)

### Option A: Drag & Drop (no account needed initially)

1. Go to https://app.netlify.com/drop
2. Sign up with email or Google
3. Drag the entire `totallycapecod` folder onto the page
4. You'll get a URL like `https://random-name-123.netlify.app`
5. Site settings → Change site name → `totallycapecod` → URL becomes `https://totallycapecod.netlify.app`

### Option B: Git-connected (recommended for Hermes integration)

1. Create a private GitHub repo, push this folder to it
2. Netlify → "Add new site" → "Import from Git" → connect GitHub → select repo
3. Build settings: leave everything blank (no build step needed)
4. Click Deploy. Done.
5. Now Hermes can push to GitHub → Netlify auto-deploys in 30s

### Custom domain ($12/year)

1. Buy `totallycapecod.com` on Cloudflare Registrar (cheapest) or Namecheap
2. Netlify → Domain settings → Add custom domain → follow DNS instructions
3. Free HTTPS auto-provisioned

---

## Step 2 — Stripe ($9.99 in-app purchases) — 15 min

1. Sign up at https://stripe.com (5 min, need a bank account)
2. Verify identity (driver's license photo or similar)
3. Dashboard → **Products** → **+ Add product**
   - Name: `Cape Cod Pro - Lifetime`
   - Price: `$9.99 USD`, one-time
4. On the product page, click **Create payment link**
5. Payment link options:
   - After payment → **Redirect to a custom URL**
   - URL: `https://YOUR-NETLIFY-URL.netlify.app/?success=true`
6. Copy the Stripe Payment Link URL (looks like `https://buy.stripe.com/abc123`)
7. Open `index.html`, find this near the top of the `<script>` block:
   ```javascript
   const STRIPE_LINK = 'https://buy.stripe.com/test_REPLACE_WITH_YOUR_LINK';
   ```
8. Replace with your live link
9. Re-deploy (drag folder again, or `git push`)

Test with Stripe's test card: `4242 4242 4242 4242`, any future date, any CVC. Then switch the Payment Link from test mode to live mode in the Stripe dashboard.

---

## Step 3 — Test it on your iPhone (5 min)

1. Open Safari on your iPhone
2. Navigate to your Netlify URL
3. Tap the Share button (square with up-arrow at the bottom)
4. Scroll down → **Add to Home Screen**
5. Tap **Add**
6. Open from your home screen — it'll be full-screen, no Safari chrome, looks exactly like a native app

---

## Step 4 — Wire up Hermes (when ready)

See `HERMES.md` for the complete integration guide. Quick summary:

1. Hermes scrapes/fetches → writes a fresh JSON to `data/<file>.json`
2. Hermes commits to GitHub (or POSTs to Netlify file API)
3. Netlify rebuilds within 30s
4. App's 5-min cache expires → fresh data appears for users

Suggested first cron jobs:
- `today.json` — daily at 5am ET
- `bridges.json` — every hour, 6am-11pm
- `conditions.json` — daily at 4am ET
- `beaches.json` — every 20 min during summer
- `whales.json` — every 30 min during summer

---

## Step 5 — Tell people (launch day)

1. Post in **r/CapeCod** — "Built a free Cape Cod app, would love feedback" (don't pitch the paid tier — let them discover it)
2. Post in **Cape Cod Facebook groups** (Cape Cod Locals, Cape Cod Tourists & Visitors, etc.)
3. **Generate a QR code** of your URL (qr-code-generator.com is free) — print it on cards, leave them at coffee shops and Cape businesses
4. **Instagram + TikTok** — make a 15-second video tapping through the app
5. Email **Cape Cod Times** local desk — they love covering local apps

---

## What works right now (everything)

✅ **Today screen** — date, conditions, tide, bridge status, top events, nearest beaches
✅ **What's Happening feed** — 15 events with category filters, free shows 3, Pro shows all
✅ **Live Beach Intel** — 28 beaches with parking/crowd/temp, map view, free shows 3 nearest, Pro shows all + lets you submit updates
✅ **Cape Cod Passport** — 100 stamps, GPS-validated check-in, persistent across reloads
✅ **AI Concierge** — pattern-matched smart responses to 15+ Cape Cod question types, 1/day free, Pro unlimited
✅ **Bridge Oracle** — current delays, 24-hour forecast, Pro unlocks 7-day forecast + best times to leave
✅ **Tides & Conditions** — today's tides/sun/weather, Pro unlocks 7-day forecast
✅ **Whale & Seal Spotter** — recent sightings map, user can submit new sightings
✅ **Lighthouse Audio Tours** — 12 tours with browser text-to-speech (zero hosting cost), map view, free shows 1, Pro shows all 12
✅ **Pro paywall** — $9.99 Stripe checkout, persistent unlock via localStorage
✅ **Install banner** — auto-prompts iPhone users to add to home screen
✅ **Offline-ish** — all features work with the data already loaded

---

## What this costs

| Item | Cost |
|---|---|
| Netlify hosting | **$0** (free tier covers 100GB/month bandwidth = ~100k users) |
| Domain (optional) | $12/year |
| Stripe | 2.9% + $0.30 per transaction |
| Google Maps API (for Hermes bridges job) | ~$5/month |
| Claude API (if you enable live AI later) | ~$30-80/month |
| **Total to launch** | **$0** |
| **First month all-in** | **~$50** |

---

## What's next (when you're ready)

### Short-term (this season)
- Wire Hermes to all 7 data files
- Replace the Stripe Payment Link with your live one
- Set `window.TCC_AI_ENDPOINT` to a Claude proxy URL for live AI responses
- Record real lighthouse audio with ElevenLabs ($11/mo) → upload to Supabase storage → set `audio_url` in `lighthouses.json` (the app already supports this)

### Medium-term (next 4-8 weeks)
- Add Supabase Auth so stamps + Pro sync across devices
- Build admin panel for manually adding events when Hermes misses them
- Add display ads to free tier (Google AdSense)
- Push notifications for Pro whale alerts (use Web Push)

### Long-term (next 3-6 months)
- Wrap the same PWA in **Capacitor** to ship a real iOS App Store app
- Switch the paywall from Stripe to Apple StoreKit IAP (required for iOS)
- Add Android (Capacitor builds both)
- See `Totally_Cape_Cod_Technical_Spec.docx` for the full native path

---

## Troubleshooting

**Data files not loading?**
Browsers block `fetch()` from `file://` URLs. The app must be served via http/https. Either deploy to Netlify, or run a local server: `cd totallycapecod && python3 -m http.server 8000` then visit `http://localhost:8000`.

**Pro purchase opens demo unlock?**
You haven't replaced the placeholder Stripe link. See Step 2 above.

**Beach map blank?**
The Leaflet CDN is loading — give it a few seconds, or check your network.

**AI gives generic answers?**
The free version pattern-matches against `data/ai-knowledge.json`. To get real Claude responses, set `window.TCC_AI_ENDPOINT` to a Cloudflare Worker that proxies to the Anthropic API.

---

**You have a real product. Ship it tonight.**
