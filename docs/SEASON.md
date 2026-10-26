# Season switch (summer ⇄ off-season)

One setting controls the season for the whole site: **`data/season.json`**.

```json
{ "mode": "auto", "auto_summer_start": "05-22", "auto_summer_end": "09-14" }
```

| `mode`      | What happens |
|-------------|--------------|
| `auto`      | Summer mode from `auto_summer_start` to `auto_summer_end` (MM-DD), off-season the rest of the year. Default. |
| `summer`    | Force summer mode. |
| `offseason` | Force off-season mode. |

The app, the guide pages and the Facebook/Instagram posts all read this file live from GitHub, so **changing it needs no deploy**. Edit it on github.com → commit to `main` and the site switches within a minute. To preview a mode without changing anything, add `?season=summer` or `?season=offseason` to any page URL.

## What changes

| Area | Summer | Off-season |
|---|---|---|
| App · Today screen | Beaches + bridge first | Off-season note; bridge, tonight and events first; beaches below |
| App · Beaches | Typical lot patterns, "tap to report parking" nudges | Gray "Off-season · quiet" status, no report nudges, "no lifeguards on duty" |
| Beach details | "Sticker required" | "Sticker/fee lot in summer · off-season: follow posted signs" |
| Lifeguard line | Date-aware either way: "on duty in season" between June 20 and Labor Day, otherwise "Lifeguarded late June–Labor Day · none on duty now" | same |
| Whale Spotter | — | Right-whale season note |
| AI concierge | — | Told it's the off-season: recommend only places marked open now |
| Copy (passport, Pro, intro, welcome page) | Summer wording | Off-season wording |
| Social posts | Beach pick (Mon), lot-report ask (Sat), summer questions, `#CapeCodSummer` | Beach walk + live water temp (Mon), "what's open all winter" ask (Sat), off-season questions, `#CapeCodFall/Winter/Spring` |
| Feeds | Water temps every 20 min, whales every 30 min | Water temps every 3 h, whales every 6 h (Nov–Apr) |

Markup hooks: `class="s-summer"` / `class="s-off"` show only in that mode; `data-season-label` gets "Summer 2027" / "Off-Season 2026–27". JS: `TCCSeason.isOff()`, `TCCSeason.pick(summer, off)`; `tcc:season` fires if the mode changes after load. Python: `scripts/lib/season.py` → `is_offseason()`.

## Honesty rules this enforces (both seasons)

- Lot status in `data/beaches.json` is a static **typical** pattern, never shown or posted as live. "Has room right now" only appears with a real beachgoer report from the last 3 hours.
- Water temps are only called "live" when the reading is under 6 hours old.
- Event cards always credit and link their source listing.

## Facts behind the off-season copy (checked Oct 26, 2026)

- Town lifeguards: mid/late June through Labor Day at most town beaches — [Barnstable County beach-sticker guide](https://capecod.gov/2024/05/24/barnstable-countys-guide-to-getting-beach-parking-stickers-on-cape-cod-a-breakdown-for-15-towns-and-the-cape-cod-national-seashore-2024).
- National Seashore: entrance fees "from late June through early September when lifeguards are on duty," plus weekends/holidays Memorial Day–end of September — [NPS](https://home.nps.gov/thingstodo/beachrelaxation.htm); fees page says fees are collected "in spring, summer, and fall" — [NPS fees](https://www.nps.gov/caco/planyourvisit/fees.htm). Rules vary, hence "follow posted signs."
- Sticker seasons vary by town (e.g. Brewster June 15–Labor Day weekend; Dennis Memorial Day weekend–Labor Day; Provincetown parking enforcement May 1–Oct 31) — county guide above and [Brewster](https://www.brewster-ma.gov/beach-information).
- Brewster lifeguards serve only at Long Pond, mid-July to mid-August — [Brewster](https://www.brewster-ma.gov/beach-information) (Breakwater Beach's lifeguard flag corrected to false).
- Right whales: in 2025–26, sightings in Cape Cod Bay ran late November to early May, peaking in March — [Mass. DMF](https://www.mass.gov/news/north-atlantic-right-whales-in-coastal-massachusetts-the-20252026-season).
- Orleans Farmers Market: Saturdays 9–12 at 19 Old Colony Way through Nov 28; winter market Saturdays 10–12 at 5 Namskaket Rd, Dec 5–Apr 24 — market listings on [MarketSpread](https://marketspread.com/market/9139/orleans-farmers-market-inc/) ([winter](https://marketspread.com/market/23653/orleans-farmers-market-winter-location/)).
