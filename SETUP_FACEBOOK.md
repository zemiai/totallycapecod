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
Four values pasted into GitHub repo secrets (one token-generation flow mints all of them):
- `FB_PAGE_ID` — your Page's numeric id
- `FB_PAGE_ACCESS_TOKEN` — a **long-lived Page** token (posting; effectively doesn't expire)
- `FB_ADS_TOKEN` — the **long-lived User** token from the same flow (ads reporting/boosting; ~60 days)
- `FB_AD_ACCOUNT_ID` — your ad account id (`act_…`)
(Plus optional `IG_USER_ID` for Instagram cross-posting — see the bottom section.)

---

## Step 1 — Create a Meta app (the API key holder)
1. Go to **https://developers.facebook.com/apps** → **Create App**.
2. Use case: **"Other"** → type: **"Business"** → name it anything (e.g. "TCC Poster").
3. You do **not** need to submit it for review — it only ever posts to your *own* Page.

## Step 2 — Get a token in the Graph API Explorer
1. Open **https://developers.facebook.com/tools/explorer**.
2. Top-right: pick your app from the **Meta App** dropdown.
3. **User or Page** dropdown → **Get User Access Token**.
4. Click **Add a Permission** and check ALL of these (posting + ads in one token flow):
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `ads_read`
   - `ads_management`
   - `read_insights`
   - `business_management` *(needed if your Page or ad account is in a Business Portfolio — check it anyway, harmless)*
   - `instagram_basic` + `instagram_content_publish` *(for the IG cross-posting below)*
5. Click **Generate Access Token** and approve the popup **logged in as the account
   that owns the ad account** (select your Page when asked).

> Already set this up before with fewer permissions? Just redo Steps 2–4 with the
> full list — regenerating adds the new scopes, and you simply paste the fresh
> values over the old secrets. Nothing else changes.

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
That returns a **long-lived user token** — save it, this is your **`FB_ADS_TOKEN`**.
Now call `me/accounts` **again** in the Explorer using that long-lived user token —
the Page `access_token` it returns is now a **long-lived Page token**. That is your
**`FB_PAGE_ACCESS_TOKEN`**. (One flow, both tokens.)

## Step 4b — Find your ad account id
In the Explorer, with the long-lived user token, run:
```
me/adaccounts?fields=name,account_id
```
Copy the `id` that looks like **`act_1234567890`** → that's **`FB_AD_ACCOUNT_ID`**.
(Or: Ads Manager → the account dropdown shows the same number.)

> Tip: a Page token derived from a long-lived user token effectively does not
> expire as long as you log into Facebook periodically. If posting ever stops with
> an auth error, just redo Steps 2–4 and update the secret.

## Step 5 — Add the secrets to GitHub
1. Repo → **Settings → Secrets and variables → Actions → New repository secret**.
2. Add (or update, if they already exist):
   - `FB_PAGE_ID` → the id from Step 3
   - `FB_PAGE_ACCESS_TOKEN` → the long-lived **Page** token from Step 4
   - `FB_ADS_TOKEN` → the long-lived **User** token from Step 4
   - `FB_AD_ACCOUNT_ID` → the `act_…` id from Step 4b

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
Hashtags are built automatically per post, 4–6 total so it reads clean, not spammy:
- A **rotating pair** from `#CapeCod #CapeCodLife #CapeCodMA #CapeCodSummer`
- A **format tag** (`#CapeCodBeaches`, `#CapeCodEvents`, `#ThingsToDoCapeCod`,
  `#CapeCodSunset`, `#HiddenGem`, `#CapeCodTonight`, `#CapeCodDebate`, `#Fireworks`)
- **Town tags** pulled from the day's actual content (e.g. `#Orleans #Truro`)

To tweak, edit `BASE_TAGS` / the format functions in `scripts/post_facebook.py`.

## Notes
- **Schedule:** twice daily — 11:30 UTC (7:30 AM ET, rotating weekday format) and
  21:00 UTC (5 PM ET, "Tonight on Cape"). Reels post Tue+Fri 20:00 UTC via
  `post-reel.yml`. Change the `cron:` lines to move them.
- **No double-posts:** each slot records its date in `data/.fb_state.json` and
  skips if already posted. (Re-run with **force** `1` to override.)
- **Fireworks days** override the morning format with the fireworks lineup +
  branded `img/fireworks.png`.
- **Links live in the first comment**, never the post body (Facebook demotes
  link posts) — added automatically with a per-format `utm_campaign`.
- **Renewing tokens:** if posting or ads ever stop with an auth error, redo
  Steps 2–4b and paste fresh values over `FB_PAGE_ACCESS_TOKEN` / `FB_ADS_TOKEN`.
  The ads (user) token expires ~every 60 days; the Page token effectively doesn't.

---

## Instagram cross-posting (optional — same photo + caption)
The poster will also publish to Instagram automatically once you add one more
secret. It uses the *same* Facebook app and Page token, so no new app needed.

**Requirements (one-time):**
1. Your Instagram account must be a **Business** (or Creator) account, and it must
   be **linked to your Facebook Page** (Instagram app → Settings → Accounts Center,
   or the Page's Settings → Linked accounts).
2. In Step 2 above, also check these two permissions when generating the token:
   - `instagram_basic`
   - `instagram_content_publish`
3. Find your **Instagram Business account id**: in the Graph API Explorer, run
   ```
   me/accounts?fields=instagram_business_account,name
   ```
   The Page that's linked to Instagram will show an `instagram_business_account.id`.
   Copy that id.
4. Add it as a GitHub secret named **`IG_USER_ID`**.

That's it — once `IG_USER_ID` exists, every daily post goes to **both** Facebook
and Instagram. If Instagram ever errors, the Facebook post still succeeds (IG
failures are logged, not fatal). Instagram doesn't allow clickable links in
captions, so the totallycapecod.com URL appears as text — consider putting the
link in your IG bio.
