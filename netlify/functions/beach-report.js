/**
 * Netlify Function: crowdsourced beach status (Waze-style).
 *
 * Makes the "is the lot full?" data REAL instead of static seed values:
 *   POST { slug, status, deviceId }  — a beachgoer reports open|mid|full. Stored + timestamped.
 *   GET                              — returns the live consensus for beaches reported recently:
 *                                      { slug: { status, count, at } }  (last 3 hours)
 *
 * Storage: @netlify/blobs store "beach-reports", one rolling list per beach slug.
 * No API key required. Abuse defenses (each fails open so a defense outage
 * never takes down honest reporting):
 *   - per-IP hourly cap, sized for a human (a family hitting 2-3 beaches), not a bot
 *   - one VOICE per beach per window: same device/IP re-reporting replaces its
 *     earlier report instead of stacking votes
 *   - slug must be a real beach (list fetched from the repo, cached, fail-open)
 *   - consensus is a weighted majority vote, not last-write-wins: GPS-verified
 *     reports (client says it's within a few miles) count double, and one
 *     device can never outvote several honest ones
 */
const crypto = require('crypto');
const STATUSES = ['open', 'mid', 'full'];
const WINDOW_MS = 3 * 60 * 60 * 1000;   // reports older than 3h are ignored / pruned
const MAX_PER_SLUG = 40;
const IP_HOURLY_LIMIT = 6;
const SLUGS_URL = 'https://raw.githubusercontent.com/zemiai/totallycapecod/main/data/beaches.json';
const SLUGS_TTL_MS = 10 * 60 * 1000;
let _slugsCache = { at: 0, set: null };

async function knownSlugs() {
  const now = Date.now();
  if (_slugsCache.set && now - _slugsCache.at < SLUGS_TTL_MS) return _slugsCache.set;
  try {
    const r = await fetch(SLUGS_URL);
    if (r.ok) {
      const j = await r.json();
      const set = new Set((j.beaches || []).map(b => b.slug).filter(Boolean));
      if (set.size) _slugsCache = { at: now, set };
      return _slugsCache.set;
    }
  } catch { /* fall through */ }
  return _slugsCache.set;   // stale cache beats nothing; null = fail open
}

const headers = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Content-Type': 'application/json',
};

function getStoreSafe() {
  try { return require('@netlify/blobs').getStore('beach-reports'); }
  catch { return null; }
}
function clientIp(event) {
  return event.headers['x-nf-client-connection-ip']
    || (event.headers['x-forwarded-for'] || '').split(',')[0].trim()
    || 'unknown';
}
function consensus(reports, now) {
  const recent = reports.filter(r => now - r.at < WINDOW_MS);
  if (!recent.length) return null;
  // Weighted majority: a GPS-verified report counts double an unverified one.
  // Ties go to the side with the newest report. Last-write-wins is exactly the
  // rule a troll wants, so it is exactly the rule we don't use.
  const score = { open: 0, mid: 0, full: 0 };
  const newest = { open: 0, mid: 0, full: 0 };
  for (const r of recent) {
    score[r.status] += r.near === true ? 2 : 1;
    if (r.at > newest[r.status]) newest[r.status] = r.at;
  }
  const winner = STATUSES.slice().sort((a, b) => (score[b] - score[a]) || (newest[b] - newest[a]))[0];
  recent.sort((a, b) => b.at - a.at);
  return { status: winner, count: recent.length, at: recent[0].at };
}
exports._consensus = consensus;   // exposed for tests only

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 200, headers, body: '' };
  const store = getStoreSafe();

  // ---- GET: live consensus for all recently-reported beaches ----
  if (event.httpMethod === 'GET') {
    if (!store) return { statusCode: 200, headers, body: JSON.stringify({}) };
    try {
      const now = Date.now();
      const out = {};
      const { blobs } = await store.list();
      for (const b of blobs) {
        if (b.key.startsWith('ip:')) continue;
        const rec = await store.get(b.key, { type: 'json' }).catch(() => null);
        if (rec && Array.isArray(rec.reports)) {
          const c = consensus(rec.reports, now);
          if (c) out[b.key] = c;
        }
      }
      return { statusCode: 200, headers, body: JSON.stringify(out) };
    } catch {
      return { statusCode: 200, headers, body: JSON.stringify({}) };
    }
  }

  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, headers, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  // ---- POST: record a report ----
  let body;
  try { body = JSON.parse(event.body || '{}'); }
  catch { return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid JSON' }) }; }

  const slug = typeof body.slug === 'string' ? body.slug.slice(0, 60).replace(/[^a-z0-9-]/gi, '') : '';
  const status = body.status;
  if (!slug || !STATUSES.includes(status)) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'slug + valid status required' }) };
  }
  // Only real beaches get blobs — a bot spraying made-up slugs pollutes nothing
  // (and can't trigger founder emails). Fails open if the list can't be fetched.
  const slugs = await knownSlugs();
  if (slugs && !slugs.has(slug)) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'unknown beach' }) };
  }
  if (!store) return { statusCode: 200, headers, body: JSON.stringify({ ok: true, stored: false }) };

  const now = Date.now();
  const ip = clientIp(event);

  // Per-IP hourly rate limit
  try {
    const ipKey = `ip:${ip}:${new Date().toISOString().slice(0, 13)}`;
    const n = parseInt(await store.get(ipKey) || '0', 10) || 0;
    if (n >= IP_HOURLY_LIMIT) {
      return { statusCode: 429, headers, body: JSON.stringify({ error: 'Too many reports — try later' }) };
    }
    await store.set(ipKey, String(n + 1), { metadata: {}, ttl: 7200 });
  } catch { /* fail open on rate limit */ }

  try {
    const rec = (await store.get(slug, { type: 'json' }).catch(() => null)) || { reports: [] };
    rec.reports = (rec.reports || []).filter(r => now - r.at < WINDOW_MS);
    // First report in an otherwise-quiet window is worth a founder ping; the
    // steady stream of follow-on reports is not (it would flood the inbox).
    const wasQuiet = rec.reports.length === 0;
    // One voice per beach per window: if this device (or, lacking a deviceId,
    // this IP) already reported this beach, REPLACE its report — updating your
    // status is welcome, stacking votes is not.
    const dev = String(body.deviceId || '').slice(0, 40);
    const iph = crypto.createHash('sha1').update(ip).digest('hex').slice(0, 10);
    rec.reports = rec.reports.filter(r => !(dev && r.dev === dev) && !(!dev && r.iph === iph));
    // near: client-side GPS check — true (within a few miles), false (far), or
    // null (no GPS). Self-reported, so it only ever raises a report's weight to
    // 2x; it is never a gate.
    rec.reports.push({ status, at: now, dev, iph,
                       near: body.near === true ? true : body.near === false ? false : null });
    if (rec.reports.length > MAX_PER_SLUG) rec.reports = rec.reports.slice(-MAX_PER_SLUG);
    await store.set(slug, JSON.stringify(rec));
    if (wasQuiet) {
      const { notifyFounder } = require('./lib/notify');
      await notifyFounder({
        subject: `🏖️ Beach report: ${slug} → ${status.toUpperCase()}`,
        html: `<p><strong>First live beach report in the last 3 hours.</strong></p>`
            + `<p>Beach: ${slug}<br>Status: <strong>${status.toUpperCase()}</strong><br>`
            + `At: ${new Date(now).toLocaleString()}</p>`
            + `<p style="color:#888;font-size:12px;">Follow-on reports for this beach in this window are not emailed.</p>`,
      });
    }
    return { statusCode: 200, headers, body: JSON.stringify({ ok: true, ...consensus(rec.reports, now) }) };
  } catch (e) {
    return { statusCode: 200, headers, body: JSON.stringify({ ok: true, stored: false }) };
  }
};
