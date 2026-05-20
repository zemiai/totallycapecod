# Hermes Soul — System Memory

This file is the **single source of truth** for the data pipeline. Anyone (human or LLM) reading this should immediately know: what the project is, what each cron does, what feeds it, what it writes, and what to do when it breaks.

Keep it current. If you change a script, update this file in the same commit.

---

## What this project is

**Totally Cape Cod** — a static PWA at `index.html` that reads 8 JSON files in `data/`. No backend. No database. The crons in `.github/workflows/` keep those JSON files fresh by fetching public APIs (NOAA, weather.gov, Google Maps) and pushing the updates straight to `main`. Netlify rebuilds on every push, ~30s deploy.

Architecture in one sentence: **GitHub Actions cron → writes `data/*.json` → commits to main → Netlify auto-deploys → app fetches with 5-min cache.**

---

## Cron jobs at a glance

| Workflow | Writes | Cadence | API used | Secret needed |
|---|---|---|---|---|
| `update-conditions.yml` | `data/conditions.json` | Daily 4:00 AM ET | NOAA Tides, weather.gov, sunrise-sunset.org | — |
| `update-bridges.yml` | `data/bridges.json` | Hourly 6 AM–11 PM ET | Google Maps Distance Matrix | `GOOGLE_MAPS_KEY` |
| `update-beaches.yml` | `data/beaches.json` | Every 20 min, summer | NOAA water temp + manual reports | — |
| `update-whales.yml` | `data/whales.json` | Every 30 min, summer | (prune old; webhook-driven later) | — |
| `update-today.yml` | `data/today.json` | Daily 5:30 AM ET, refresh 11 AM | LLM extraction from town/venue URLs | `ANTHROPIC_API_KEY` (optional) |

**`stamps.json`, `lighthouses.json`, `ai-knowledge.json` are static** — edited manually, not by cron.

---

## File schema rules

Every JSON file MUST have:

```json
{
  "version": "1.0",
  "updated_at": "ISO 8601 UTC, e.g. 2026-05-19T13:45:00Z",
  ...
}
```

`updated_at` is what the app reads to decide if its 5-min cache is stale. If you ever forget to bump it, users see stale data.

Full per-file schemas live in [`HERMES.md`](HERMES.md). Don't duplicate them here — keep this file lean.

---

## Operating conventions

1. **Validate before writing.** Each script calls `lib.io.safe_write(path, data, min_ratio=0.5)`. If the new data is empty or less than half the previous size, it aborts and exits non-zero. Scraper failures should NEVER silently overwrite good data.
2. **All timestamps in UTC.** Convert at render time for display. ISO 8601 with `Z` suffix.
3. **Commit messages:** `[hermes] <file>.json update YYYY-MM-DD HH:MM` — keeps git log filterable.
4. **Skip empty changes.** Workflows use `git diff --quiet` before committing; no commit if nothing changed.
5. **Workflow permissions:** every workflow needs `permissions: { contents: write }` to push.
6. **Concurrency:** each workflow uses `concurrency: { group: <name>, cancel-in-progress: true }` so overlapping runs don't fight each other.

---

## Secrets to configure in GitHub repo settings

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Used by | Where to get |
|---|---|---|
| `GOOGLE_MAPS_KEY` | bridges | console.cloud.google.com → APIs & Services → enable Distance Matrix → create key. Restrict to Distance Matrix API only. ~$5/mo at hourly cadence. |
| `ANTHROPIC_API_KEY` | today (optional) | console.anthropic.com → API keys. Only needed if you want LLM event extraction. |

No other secrets needed. NOAA, weather.gov, sunrise-sunset.org are all free + keyless.

---

## When things break — runbook

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow shows ❌ in Actions tab | API failed or validation rejected the new data | Open the run logs. `safe_write` aborts print the reason on stderr. |
| App shows stale data > 1 hour | Workflow ran but didn't commit (no diff), OR Netlify deploy failed | Check Actions tab for green checkmarks; check Netlify dashboard for deploy history. |
| Bridge delays look wrong | Google Maps returned `duration_in_traffic` differently than expected | `scripts/update_bridges.py` — check the parsing of `rows[0].elements[0]`. |
| `today.json` empty after 5:30 AM | LLM extraction failed or no source URLs returned events | Check `update-today.yml` log. Falls back to keeping yesterday's data via `safe_write`. |
| Costs creeping up | Bridges cron firing too often, or LLM token usage spiked | Drop bridge cadence to every 2h, or disable today.yml until you tune the prompt. |

---

## Adding a new cron job

1. Add a workflow at `.github/workflows/update-<name>.yml` (copy an existing one).
2. Add the script at `scripts/update_<name>.py`.
3. Use `lib.io.safe_write` to write the JSON.
4. Add a row to the "Cron jobs at a glance" table above.
5. Document the API source in the script's docstring AND in [`HERMES.md`](HERMES.md).

---

## What this system intentionally does NOT do

- **No image hosting.** If you need user-submitted photos, add Cloudflare R2 or Supabase storage separately.
- **No real-time user submission aggregation.** Beach/whale reports stay in each user's `localStorage`. To crowd-source, add a webhook endpoint (Cloudflare Worker → KV) and a fetch call in `reportBeach()` / `submitSighting()`.
- **No auth.** Pro unlock is `localStorage`-only. If revenue matters, layer in Supabase Auth and verify Stripe webhooks server-side.
- **No retries.** A failed cron run logs and exits. Next scheduled run tries fresh. Keep it simple; don't engineer for problems that haven't happened.

---

## Quick local test

Before pushing a script change, run it locally against the real APIs:

```bash
cd totallycapecod
python -m pip install -r scripts/requirements.txt
python scripts/update_conditions.py   # writes data/conditions.json
git diff data/conditions.json          # inspect the change
```

If `git diff` shows what you expect, commit and push. If it shows garbage, the API changed — fix the parser before the next scheduled run.
