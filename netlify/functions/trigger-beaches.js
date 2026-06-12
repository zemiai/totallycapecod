/**
 * Netlify Scheduled Function: kick the beach water-temp pipeline on a reliable clock.
 *
 * Why this exists: GitHub throttles `schedule:` cron on this repo, so the
 * "[hermes] beaches" workflow (scheduled every 20 min) actually fires only once
 * every few hours — leaving live water temps stale. Netlify's scheduler IS
 * reliable, so this
 * function fires `workflow_dispatch` on update-beaches.yml at a steady interval.
 * The workflow itself does the NOAA/NDBC fetch + commit; we just trigger it.
 *
 * Schedule is configured in netlify.toml ([functions."trigger-beaches"]).
 *
 * Requires a Netlify env var GH_DISPATCH_TOKEN — a fine-grained GitHub PAT
 * scoped to zemiai/totallycapecod with Actions: read & write (and Metadata: read).
 * If the token isn't set, the function no-ops gracefully (no error spam).
 */
const REPO = 'zemiai/totallycapecod';
const WORKFLOW = 'update-beaches.yml';
const REF = 'main';

exports.handler = async () => {
  const token = process.env.GH_DISPATCH_TOKEN;
  if (!token) {
    console.log('[trigger-beaches] GH_DISPATCH_TOKEN not set — skipping (no-op).');
    return { statusCode: 200, body: 'no token configured; skipped' };
  }

  // Only run in the Cape's season (May–Oct), mirroring the workflow's own cron.
  const month = new Date().getUTCMonth() + 1; // 1–12
  if (month < 5 || month > 10) {
    return { statusCode: 200, body: 'off-season; skipped' };
  }

  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'totallycapecod-scheduler',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: REF }),
    });

    if (res.status === 204) {
      console.log('[trigger-beaches] dispatched update-beaches.yml ✓');
      return { statusCode: 200, body: 'dispatched' };
    }
    const text = await res.text().catch(() => '');
    console.error(`[trigger-beaches] dispatch failed: ${res.status} ${text}`);
    return { statusCode: 200, body: `dispatch returned ${res.status}` };
  } catch (e) {
    console.error('[trigger-beaches] error:', e.message);
    return { statusCode: 200, body: 'error (logged)' };
  }
};
