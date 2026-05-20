# Setup — From zero to live in ~45 minutes

You have everything you need. Follow these steps in order. Each is short.

---

## 1. Push to GitHub (5 min)

```bash
cd "C:/Users/908 Bistro/Downloads/totallycapecod"
git init
git add .
git commit -m "initial commit"
git branch -M main
```

Create a new **private** repo at https://github.com/new (don't initialize with README/license). Then:

```bash
git remote add origin https://github.com/<your-username>/totallycapecod.git
git push -u origin main
```

---

## 2. Deploy to Netlify (5 min)

1. Go to https://app.netlify.com → "Add new site" → "Import an existing project" → GitHub
2. Authorize Netlify, pick the `totallycapecod` repo
3. Build settings: leave everything blank (it's static — no build step)
4. Click **Deploy**
5. You'll get a URL like `https://serene-pony-abc123.netlify.app`
6. (Optional) Site settings → Change site name → `totallycapecod` → URL becomes `https://totallycapecod.netlify.app`

Every push to `main` now auto-deploys in ~30 seconds.

---

## 3. Wire up Stripe (10 min)

See [DEPLOY.md](DEPLOY.md) §"Step 2 — Stripe" for the detailed walkthrough. The short version:

1. https://stripe.com → create account → verify identity
2. Products → Add product → name "Cape Cod Pro - Lifetime", price $9.99 one-time
3. Create payment link → success redirect to `https://<your-netlify-url>/?success=true`
4. Copy the live payment link URL
5. Edit `index.html`, find `const STRIPE_LINK = 'https://buy.stripe.com/test_REPLACE_WITH_YOUR_LINK';`, paste your link
6. Commit & push

---

## 4. Add secrets to GitHub (5 min)

GitHub repo → Settings → Secrets and variables → Actions → **New repository secret**.

### Required for the bridges cron

1. Get a Google Maps key:
   - https://console.cloud.google.com → create a project → APIs & Services → enable **Distance Matrix API**
   - Credentials → Create credentials → API key
   - Click the key → "Restrict key" → API restrictions → select only "Distance Matrix API"
2. Add secret:
   - Name: `GOOGLE_MAPS_KEY`
   - Value: the key you just made

### Optional — only if you want LLM event extraction (today.json)

1. https://console.anthropic.com → API keys → Create key
2. Add secret:
   - Name: `ANTHROPIC_API_KEY`
   - Value: the key
3. Edit `scripts/update_today.py` and add real Cape event URLs to the `SOURCES` list

Without these secrets the workflows will still run — bridges will fail (skip it), today.json will skip itself.

---

## 5. Enable Actions (1 min)

GitHub repo → Actions tab → "I understand my workflows, go ahead and enable them"

You should now see 5 workflows: `[hermes] conditions`, `bridges`, `beaches`, `whales`, `today`.

---

## 6. Smoke-test (10 min)

Manually trigger each workflow to make sure it works before scheduled runs start:

GitHub → Actions → pick a workflow → "Run workflow" → main → Run.

Watch the run. Green ✅ = success, red ❌ = check the logs. Expected results:

| Workflow | What to expect on first run |
|---|---|
| `[hermes] conditions` | Green. New commit `[hermes] conditions.json update ...` appears in main. |
| `[hermes] bridges` | Green if `GOOGLE_MAPS_KEY` is set. Otherwise red — that's fine, just don't trigger it. |
| `[hermes] beaches` | Green. Bumps `updated_at` and water_temp. |
| `[hermes] whales` | Green. "pruned 0 sightings" is normal. |
| `[hermes] today` | Skips (exit 0) if no `ANTHROPIC_API_KEY` or no `SOURCES`. Fine. |

---

## 7. Verify on the live site (2 min)

Open your Netlify URL in your phone's Safari. Check:

- [ ] Today screen shows today's date
- [ ] Tides match NOAA (https://tidesandcurrents.noaa.gov/stationhome.html?id=8447435)
- [ ] Tap "Add to Home Screen" — installs as PWA
- [ ] Click a beach → "Report" → it persists on reload (localStorage)

---

## After setup — what runs when

Once enabled, you do nothing. The crons run on this schedule (all UTC):

```
[hermes] conditions  08:00 daily          (4 AM ET, daily)
[hermes] bridges     10:00–23:00, 00:00–03:00 hourly  (6 AM–11 PM ET)
[hermes] beaches     */20 May–Oct         (every 20 min, summer only)
[hermes] whales      */30 May–Oct         (every 30 min, summer only)
[hermes] today       09:30 + 15:00 daily  (5:30 AM + 11 AM ET)
```

GitHub Actions free tier: 2,000 minutes/month on private repos. Estimated usage above: ~600 min/month. Plenty of headroom.

---

## Next steps you might want

- **Make beach reports actually crowd-sourced.** See [HERMES.md](HERMES.md) §"User submissions back to Hermes". Need a webhook endpoint — Cloudflare Worker or Netlify Function — that ingests POSTs and writes to a KV store. Then `update_beaches.py` reads from KV and merges into `beaches.json`.
- **Real lighthouse audio.** Browser TTS is robotic. Record with ElevenLabs ($11/mo), upload mp3s to Cloudflare R2, set `audio_url` on each entry in `data/lighthouses.json`. The app already supports it.
- **AI Concierge → real Claude.** Set `window.TCC_AI_ENDPOINT` in `index.html` to a Cloudflare Worker that proxies to the Anthropic API. Workers free tier = 100k requests/day.
- **Native iOS app.** Wrap the PWA in Capacitor when you're ready. The data pipeline doesn't change. See `Totally_Cape_Cod_Technical_Spec.docx`.

---

## Where to look when something breaks

[`HERMES_MEMORY.md`](HERMES_MEMORY.md) — the runbook. Has a "When things break" table mapping symptoms to fixes. Update it when you learn something new.
