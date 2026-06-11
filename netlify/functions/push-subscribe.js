/**
 * Netlify Function: Push Subscribe
 * Stores a browser PushSubscription in @netlify/blobs so push-send.js
 * can enumerate them later.
 *
 * Usage: POST /.netlify/functions/push-subscribe
 * Body: { endpoint, keys: { p256dh, auth }, deviceId? }
 *
 * The blob key is a SHA-256 hash of the endpoint URL so re-subscribes
 * (e.g., after a browser restart) simply overwrite the existing record
 * rather than creating duplicates.
 *
 * Response: { ok: true }
 */

const { createHash } = require('crypto');

/** Return a short, URL-safe hex hash of the endpoint string. */
function endpointKey(endpoint) {
  return createHash('sha256').update(endpoint).digest('hex');
}

exports.handler = async (event) => {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
  };

  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 200, headers, body: '' };
  }

  if (event.httpMethod !== 'POST') {
    return {
      statusCode: 405,
      headers,
      body: JSON.stringify({ error: 'Method not allowed' }),
    };
  }

  // ── Parse body ──
  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return {
      statusCode: 400,
      headers,
      body: JSON.stringify({ error: 'Invalid JSON' }),
    };
  }

  // ── Validate ──
  const { endpoint, keys, deviceId } = body || {};

  if (
    !endpoint ||
    typeof endpoint !== 'string' ||
    !keys ||
    typeof keys.p256dh !== 'string' ||
    typeof keys.auth   !== 'string'
  ) {
    return {
      statusCode: 400,
      headers,
      body: JSON.stringify({ error: 'endpoint and keys (p256dh, auth) are required' }),
    };
  }

  // ── Persist to Netlify Blobs ──
  try {
    const { getStore } = require('@netlify/blobs');
    const store = getStore('push-subs');
    const key   = endpointKey(endpoint);

    await store.setJSON(key, {
      endpoint,
      keys: { p256dh: keys.p256dh, auth: keys.auth },
      deviceId: deviceId ? String(deviceId).slice(0, 128) : null,
      createdAt: new Date().toISOString(),
    });
  } catch {
    // Blobs unavailable (local dev or misconfigured) — acknowledge gracefully
    // so the client doesn't surface an error to the user.
  }

  return {
    statusCode: 200,
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ ok: true }),
  };
};
