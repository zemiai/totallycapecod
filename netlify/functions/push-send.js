/**
 * Netlify Function: Push Send
 * Broadcasts a web-push notification to every stored subscription.
 *
 * Usage: POST /.netlify/functions/push-send
 * Body: { secret, title, body, url, tag }
 *
 * Required env vars:
 *   PUSH_SEND_SECRET   — shared secret to authorize this endpoint
 *   VAPID_PUBLIC_KEY   — generate with: npx web-push generate-vapid-keys
 *   VAPID_PRIVATE_KEY  — (same command)
 *   VAPID_SUBJECT      — e.g. "mailto:info@totallycapecod.com"
 *
 * Returns: { sent, removed, failed }
 *   sent    — notifications delivered successfully
 *   removed — dead subscriptions pruned (404 / 410 responses)
 *   failed  — transient send errors (subscription kept for retry)
 */

const webpush = require('web-push');

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

  // ── Auth: shared secret ──
  const PUSH_SEND_SECRET = process.env.PUSH_SEND_SECRET;
  if (!PUSH_SEND_SECRET || body.secret !== PUSH_SEND_SECRET) {
    return {
      statusCode: 401,
      headers,
      body: JSON.stringify({ error: 'Unauthorized' }),
    };
  }

  // ── Guard: VAPID env vars must exist ──
  const VAPID_PUBLIC_KEY  = process.env.VAPID_PUBLIC_KEY;
  const VAPID_PRIVATE_KEY = process.env.VAPID_PRIVATE_KEY;
  const VAPID_SUBJECT     = process.env.VAPID_SUBJECT;

  if (!VAPID_PUBLIC_KEY || !VAPID_PRIVATE_KEY || !VAPID_SUBJECT) {
    console.error('push-send: VAPID env vars are not configured');
    return {
      statusCode: 503,
      headers,
      body: JSON.stringify({ error: 'Push service not configured' }),
    };
  }

  // ── Configure web-push ──
  webpush.setVapidDetails(VAPID_SUBJECT, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY);

  // ── Build notification payload ──
  const { title, body: msgBody, url, tag } = body;
  const payload = JSON.stringify({
    title: title || 'Totally Cape Cod',
    body:  msgBody || '',
    url:   url    || '/app/',
    tag:   tag    || 'tcc-push',
  });

  // ── Load subscriptions from Blobs ──
  let store;
  let entries = [];
  try {
    const { getStore } = require('@netlify/blobs');
    store   = getStore('push-subs');
    const result = await store.list();
    entries = result.blobs || [];
  } catch (err) {
    console.error('push-send: failed to load subscriptions:', err.message);
    return {
      statusCode: 503,
      headers,
      body: JSON.stringify({ error: 'Could not load subscriptions' }),
    };
  }

  // ── Fan out notifications ──
  let sent    = 0;
  let removed = 0;
  let failed  = 0;

  await Promise.all(
    entries.map(async (entry) => {
      let sub;
      try {
        sub = await store.get(entry.key, { type: 'json' });
      } catch {
        // Can't read this entry — skip
        failed++;
        return;
      }

      if (!sub || !sub.endpoint) {
        failed++;
        return;
      }

      try {
        await webpush.sendNotification(
          { endpoint: sub.endpoint, keys: sub.keys },
          payload
        );
        sent++;
      } catch (err) {
        const status = err.statusCode || err.status;
        if (status === 404 || status === 410) {
          // Subscription is gone — prune it
          try {
            await store.delete(entry.key);
          } catch {
            // Non-fatal; it'll be skipped next time
          }
          removed++;
        } else {
          // Transient error — leave sub in place for next send
          console.error(
            `push-send: failed to deliver to ${entry.key}: ${err.message}`
          );
          failed++;
        }
      }
    })
  );

  return {
    statusCode: 200,
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ sent, removed, failed }),
  };
};
