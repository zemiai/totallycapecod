# Totally Cape Cod — SEO content pipeline

Goal: rank in the top 3 for the Cape Cod searches people actually make. To be realistic, broad
terms like "cape cod beaches" are held by big, old sites (TripAdvisor, the Cape Cod Chamber,
capecod.com, Cape Cod Life), and outranking them takes backlinks and time. Specific,
time-sensitive and live-data searches are winnable within months, and that's where the pipeline
aims first: "cape cod christmas events 2026", "sagamore bridge traffic", "cape cod in november",
"is cape cod worth visiting".

## How a guide gets made

1. **Plan.** `content/plan.json` is the topic queue: keywords, a brief, a season window
   (`MM-DD..MM-DD`) and a priority. Edit it to add, reorder or pause topics (`"auto": false`).
2. **Write.** `.github/workflows/content-writer.yml` runs Tuesdays and Fridays and calls
   `scripts/content/writer.py`. Each run takes the next topic that's in season, researches it
   (web search plus the topic's seed URLs plus our own live event data, credited to organizers),
   and drafts the guide only from that research.
3. **Fact-check gate.** Nothing is published unless it passes all of these:
   - every factual sentence carries a numbered citation, and every citation matches a real source;
   - every number, date and time in a cited sentence also appears in that source's evidence text;
   - a separate audit pass finds no unsupported, overstated or invented claims.
   A draft that still fails after one revision goes to `content/drafts/` with a report and its
   topic is marked `needs_review`. Nothing half-checked goes live.
4. **Save the references.** Every published guide has `content/evidence/<slug>.json`: for each
   numbered source, short verbatim excerpts (≤40 words) that back the claims citing it, the date
   they were checked, and a Wayback Machine copy (`archived`, filled in by the "archive guide
   sources" workflow). `build_site.py` refuses to build a guide whose sources lack saved excerpts
   or that has unresolved `gaps`, and each guide's Sources list shows the excerpts ("What the
   source says") and the archived copy.
5. **Build.** `scripts/content/build_site.py` turns `content/articles/*.md` into
   `/guides/<slug>/` pages with Article, Breadcrumb and FAQ structured data, plus the guides hub,
   the author page, the "How we fact-check" page, the RSS feed and `sitemap.xml`.
   Netlify deploys on push.

## Who writes the guides

Since Nov 8, 2026 a Claude scheduled task ("Totally Cape Cod — new guide (Tue/Fri)") researches,
writes, independently fact-checks, saves the references for and publishes the next due topic
every Tuesday and Friday morning. It needs no API key. The GitHub Action below is the older,
unattended alternative; don't enable both, or each will publish.

## To turn on the GitHub writer instead

Add **one** repository secret (GitHub → Settings → Secrets and variables → Actions):

- `ANTHROPIC_API_KEY` (recommended: enables web research), or
- `GEMINI_API_KEY` (works from seed URLs and site data only).

Without a key, runs skip cleanly. To test without publishing: Actions → content writer →
Run workflow → `dry_run` = `1`.

## Editing by hand

Write `content/articles/<slug>.md` (front matter with `sources`, body with `[n]` citations), then
run `python scripts/content/build_site.py`. `--check` validates without building. Mark lines that
are deliberately uncited editorial notes with `<!-- nocite -->`.

## Standards (also published at /guides/standards/)

- We're an intermediary: nothing is made up. Research, confirm with the source, then post, and save
  the references. If it can't be confirmed, it's left out. This applies to social posts and app copy
  too: no invented picks, rankings, reviews, quotes or "live" numbers.
- Primary sources first: organizers, towns, the state, NPS, NOAA.
- Credit organizers and photographers by name, with a link to the original. Photos are used only
  with permission.
- Byline: Versel Johnson. Every guide carries a short note that it was researched with AI tools and
  checked against its sources.
- No invented experiences, rankings or superlatives.

## Keyword map (from Google autocomplete mining, Oct 26, 2026)

Rough demand signal = how often a phrase appeared across 486 autocomplete probes. These are not
search volumes.

| Cluster | Target searches | Our page |
|---|---|---|
| Holidays | cape cod christmas events 2026, christmas stroll, falmouth christmas parade, gardens aglow, holly folly | /guides/cape-cod-holiday-events-2026/ ✅ |
| Live data (our moat) | sagamore bridge traffic (right now), bourne bridge traffic, cape cod traffic, best time to cross | /cape-cod-bridge-traffic.html + bridge guide (queued) |
| Live data | cape cod water temperature, beach conditions today | existing live pages |
| Events | cape cod events this weekend / today / this week, events calendar | /events (now live + sourced) |
| Seasons | cape cod in november … april, cape cod in winter, weather by month, best time to visit | monthly guides (queued, each in its season window) |
| Planning | is cape cod worth visiting (top autocomplete phrase), how many days, is cape cod an island, is cape cod expensive | queued |
| Wildlife | right whales cape cod bay, where to see seals, whale watching, cold-stunned sea turtles | /guides/whales-and-seals-cape-cod-winter/ ✅ |
| Beaches | dog friendly beaches, free parking, beach stickers 2027, sharks | queued for spring |
| Towns | provincetown off-season, things to do in chatham | queued |

## Season calendar (Tue/Fri, projected Nov 9, 2026)

The scheduled writer takes the lowest-priority topic that's in season, so the queue publishes roughly:

| When | What |
|---|---|
| Nov–Dec 2026 | November/December/New Year's guides, bridge times, "is Cape Cod worth visiting", best time to visit, Provincetown off-season, how many days, lighthouses, National Seashore, rainy days, Chatham, island ferries |
| Jan–Feb 2027 | Camping and reservations, town guides (Wellfleet, Falmouth/Woods Hole, Hyannis, Orleans, Eastham, Brewster, Sandwich, Provincetown, Truro, Harwich, Dennis, Yarmouth, Bourne/Canal), Rail Trail, monthly guides |
| Mar–Apr 2027 | Dog rules, beach rules, bike paths, whale watching 2027, getting there without a car, summer events 2027, fishing/shellfishing permits, seal tours, ponds, bridge replacement, beach parking 2027, lifeguarded beaches 2027, Fourth of July 2027, band concerts, farmers markets, Memorial Day |
| May 2027 | May and June guides, shark safety; then refresh every dated guide as 2027 details are posted |

Dated guides publish with "not yet announced" sections and are updated as organizers post 2027 details.

## What else moves rankings (outside the pipeline)

- **Search Console + GA4 reporting.** Add `GOOGLE_SA_KEY`, `GA4_PROPERTY_ID` and
  `STRIPE_REPORTING_KEY` as secrets so the nightly metrics job reports traffic and rankings, and
  submit `https://totallycapecod.com/sitemap.xml` in Google Search Console.
- **Backlinks.** Credited events and photographers are natural link partners: tell organizers
  and photographers when they're featured.
- **Freshness.** Guides with live sections (events) stay current on their own. Seasonal guides are
  re-queued each year with new dates.
