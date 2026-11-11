/**
 * Netlify Scheduled Function: kick the bridge-traffic pipeline on a reliable clock.
 *
 * Why this exists: GitHub throttles `schedule:` cron on this repo. The "[hermes] bridges"
 * workflow is scheduled hourly (18 runs/day) but in Nov 2026 GitHub actually ran it only
 * 3–5 times a day, so bridge delays on the site were often many hours old. Netlify's
 * scheduler is reliable, so this fires `workflow_dispatch` on update-bridges.yml instead.
 *
 * Schedule is configured in netlify.toml ([functions."trigger-bridges"]).
 *
 * Requires the Netlify env var GH_DISPATCH_TOKEN — a fine-grained GitHub PAT scoped to
 * zemiai/totallycapecod with Actions: read & write (and Metadata: read). Without it the
 * function no-ops quietly.
 */
const REPO = 'zemiai/totallycapecod';
const WORKFLOW = 'update-bridges.yml';
const REF = 'main';

exports.handler = async () => {
  const token = process.env.GH_DISPATCH_TOKEN;
  if (!token) {
    console.log('[trigger-bridges] GH_DISPATCH_TOKEN not set — skipping (no-op).');
    return { statusCode: 200, body: 'no token configured; skipped' };
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
      console.log('[trigger-bridges] dispatched update-bridges.yml ✓');
      return { statusCode: 200, body: 'dispatched' };
    }
    const text = await res.text().catch(() => '');
    console.error(`[trigger-bridges] dispatch failed: ${res.status} ${text}`);
    return { statusCode: 200, body: `dispatch returned ${res.status}` };
  } catch (e) {
    console.error('[trigger-bridges] error:', e.message);
    return { statusCode: 200, body: 'error (logged)' };
  }
};
