# Facebook auto-posting — setup (≈15 min, one time)

The app already builds a daily **"Cape Cod Today"** post from its own live data
(weather, water temp, sunset spot, bridge delays, today's events, and the July 4th
fireworks). To let it post to your Facebook **Page** automatically, you just need
to give GitHub two secrets: your Page's ID and a long-lived Page access token.

You only do this once. After that it posts every morning at **7:30 AM ET** on its
own. (It will *not* post until these secrets exist — so nothing happens publicly
until you finish this.)

---

## What you'll end up with
Two values pasted into GitHub repo secrets:
- `FB_PAGE_ID` — your Page's numeric id
- `FB_PAGE_ACCESS_TOKEN` — a **long-lived Page** token (lasts ~60 days; see "Renewing" below)

---

## Step 1 — Create a Meta app (the API key holder)
1. Go to **https://developers.facebook.com/apps** → **Create App**.
2. Use case: **"Other"** → type: **"Business"** → name it anything (e.g. "TCC Poster").
3. You do **not** need to submit it for review — it only ever posts to your *own* Page.

## Step 2 — Get a token in the Graph API Explorer
1. Open **https://developers.facebook.com/tools/explorer**.
2. Top-right: pick your app from the **Meta App** dropdown.
3. **User or Page** dropdown → **Get User Access Token**.
4. Click **Add a Permission** and check these four:
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `business_management` *(only if your Page is in a Business Portfolio)*
5. Click **Generate Access Token** and approve the popup (select your Page when asked).

## Step 3 — Find your Page ID
In the Explorer, with the token from Step 2, run this in the query bar and click **Submit**:
```
me/accounts
```
You'll get a list of your Pages. Copy the **`id`** of the Page you want to post to
→ that's your **`FB_PAGE_ID`**. Also copy that Page's **`access_token`** from the
same response — that's a Page token, but it's short-lived; do Step 4 to make it last.

## Step 4 — Make the token long-lived (~60 days)
Paste this URL in a browser, filling in the three blanks (`APP_ID`, `APP_SECRET`
from your app's **Settings → Basic**, and the **User** token from Step 2):
```
https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=USER_TOKEN_FROM_STEP_2
```
That returns a **long-lived user token**. Now call `me/accounts` **again** in the
Explorer using that long-lived user token — the Page `access_token` it returns is
now a **long-lived Page token**. That is your **`FB_PAGE_ACCESS_TOKEN`**.

> Tip: a Page token derived from a long-lived user token effectively does not
> expire as long as you log into Facebook periodically. If posting ever stops with
> an auth error, just redo Steps 2–4 and update the secret.

## Step 5 — Add the two secrets to GitHub
1. Repo → **Settings → Secrets and variables → Actions → New repository secret**.
2. Add:
   - Name `FB_PAGE_ID` → value = the id from Step 3
   - Name `FB_PAGE_ACCESS_TOKEN` → value = the long-lived Page token from Step 4

## Step 6 — Test it safely (no public post)
Repo → **Actions → "post to Facebook" → Run workflow** → in **dry_run** type `1`
→ Run. Open the run logs: you'll see the exact post it *would* publish, with
nothing sent. When it looks good, run it again with **dry_run** blank to publish a
real post immediately. After that it runs itself every morning.

---

## Pictures 📸
Every post goes out **as a photo** (photos get far more reach than plain links).
The image is chosen automatically:
1. **Your pick for a specific day** — drop a file named by date in `img/social/`,
   e.g. `img/social/2026-07-04.jpg`, and that day's post uses it.
2. **Fireworks days** — uses the branded `img/fireworks.png` automatically.
3. **Rotation** — any other images you add to `img/social/` get rotated through
   day by day, so posts stay fresh.
4. **Fallback** — the branded `img/social/default.png` (already included).

So "posting pictures through here" = **commit a photo to `img/social/`** (or name
it by date to schedule it). No code changes needed. Landscape 1200×630 or square
1080×1080 look best.

## Hashtags #️⃣
Hashtags are built automatically from each day's content, so they're always
relevant — never a static block:
- Always: `#CapeCod #CapeCodLife #CapeCodMA #CapeCodSummer`
- Per **town** in the post (e.g. `#Falmouth #Provincetown`)
- Per **event type** (e.g. `#LiveMusic`, `#CapeCodEats`, `#FamilyFun`, `#CapeCodArt`)
- Fireworks days add `#Fireworks #FourthOfJuly #July4th #IndependenceDay`
- Beaches always get `#CapeCodBeaches`

Capped at ~14 so it reads clean, not spammy. To tweak the tag map, edit
`CATEGORY_TAGS` / `BASE_TAGS` at the top of `scripts/post_facebook.py`.

## Notes
- **Schedule:** daily 11:30 UTC = 7:30 AM ET (`.github/workflows/post-facebook.yml`).
  Change the `cron:` line to move it.
- **No double-posts:** it records the date in `data/.fb_state.json` and skips if it
  already posted that day. (Re-run with **force** `1` to override.)
- **Fireworks week:** on any day with a fireworks event it leads with the fireworks
  list and attaches the branded `img/fireworks.png`. Other days post a link card.
- **Instagram:** the same Graph API can cross-post to an IG Business account linked
  to the Page — say the word and I'll add it.
- **Renewing the token:** if it ever expires, redo Steps 2–4 and paste the new value
  into the `FB_PAGE_ACCESS_TOKEN` secret. Nothing else changes.
