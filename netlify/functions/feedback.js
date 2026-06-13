/**
 * Netlify Function: in-app feedback ("What's missing for your trip?").
 *
 * POST /.netlify/functions/feedback
 * Body: { message, email?, context?, deviceId? }
 *
 * Stores every note in the @netlify/blobs "feedback" store, and — if email is
 * configured — pings the founder so feedback is seen, not buried. Light IP rate
 * limit so it can't be spammed. No API key required to store.
 */
const FOUNDER_EMAIL = 'dishguyturncook@gmail.com';
const MAX_LEN = 2000;
const IP_HOURLY_LIMIT = 20;

const headers = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Content-Type': 'application/json',
};

function clientIp(event) {
  return event.headers['x-nf-client-connection-ip']
    || (event.headers['x-forwarded-for'] || '').split(',')[0].trim()
    || 'unknown';
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 200, headers, body: '' };
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, headers, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  let body;
  try { body = JSON.parse(event.body || '{}'); }
  catch { return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid JSON' }) }; }

  const message = (typeof body.message === 'string' ? body.message : '').trim().slice(0, MAX_LEN);
  if (!message) return { statusCode: 400, headers, body: JSON.stringify({ error: 'A message is required' }) };

  const email = (typeof body.email === 'string' ? body.email.trim().slice(0, 120) : '');
  const context = (typeof body.context === 'string' ? body.context.slice(0, 120) : '');
  const deviceId = (typeof body.deviceId === 'string' ? body.deviceId.slice(0, 40) : '');
  const ip = clientIp(event);
  const now = Date.now();

  let store = null;
  try { store = require('@netlify/blobs').getStore('feedback'); } catch { /* local dev */ }

  // Light per-IP hourly rate limit
  if (store) {
    try {
      const ipKey = `ip:${ip}:${new Date().toISOString().slice(0, 13)}`;
      const n = parseInt(await store.get(ipKey) || '0', 10) || 0;
      if (n >= IP_HOURLY_LIMIT) {
        return { statusCode: 429, headers, body: JSON.stringify({ error: 'Thanks — that\'s plenty for now!' }) };
      }
      await store.set(ipKey, String(n + 1), { ttl: 7200 });
    } catch { /* fail open */ }

    try {
      const id = `fb_${now}_${Math.random().toString(36).slice(2, 8)}`;
      await store.setJSON(id, { message, email, context, deviceId, ip, at: new Date(now).toISOString() });
    } catch { /* non-blocking */ }
  }

  // Notify the founder (so feedback actually gets seen) — Resend, then Zapier fallback.
  const RESEND_API_KEY = process.env.RESEND_API_KEY;
  if (RESEND_API_KEY) {
    try {
      await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: { Authorization: `Bearer ${RESEND_API_KEY}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from: 'Totally Cape Cod <info@totallycapecod.com>',
          to: FOUNDER_EMAIL,
          reply_to: email || undefined,
          subject: `💬 App feedback${context ? ' (' + context + ')' : ''}`,
          html: `<p><strong>New in-app feedback:</strong></p><blockquote>${message.replace(/</g, '&lt;')}</blockquote>`
              + `<p style="color:#888;font-size:12px;">From: ${email || 'anonymous'} · ${context || 'app'} · ${new Date(now).toLocaleString()}</p>`,
        }),
      });
    } catch { /* non-blocking */ }
  } else if (process.env.ZAPIER_SUBMISSION_WEBHOOK) {
    try {
      await fetch(process.env.ZAPIER_SUBMISSION_WEBHOOK, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'feedback', message, email, context, at: new Date(now).toISOString() }),
      });
    } catch { /* non-blocking */ }
  }

  return { statusCode: 200, headers, body: JSON.stringify({ ok: true }) };
};
