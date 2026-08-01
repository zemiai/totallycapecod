/**
 * Netlify Function: crowdsourced beach status (Waze-style).
 *
 * Makes the "is the lot full?" data REAL instead of static seed values:
 *   POST { slug, status, deviceId }  — a beachgoer reports open|mid|full. Stored + timestamped.
 *   GET                              — returns the live consensus for beaches reported recently:
 *                                      { slug: { status, count, at } }  (last 3 hours)
 *
 * Storage: @netlify/blobs store "beach-reports", one rolling list per beach slug.
 * Rate-limited per IP so it can't be spammed. No API key required.
 */
const STATUSES = ['open', 'mid', 'full'];
const WINDOW_MS = 3 * 60 * 60 * 1000;   // reports older than 3h are ignored / pruned
const MAX_PER_SLUG = 40;
const IP_HOURLY_LIMIT = 40;

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
  recent.sort((a, b) => b.at - a.at);
  return { status: recent[0].status, count: recent.length, at: recent[0].at };
}

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
    rec.reports.push({ status, at: now, dev: String(body.deviceId || '').slice(0, 40) });
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
