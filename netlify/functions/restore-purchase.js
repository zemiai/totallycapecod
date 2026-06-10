/**
 * Netlify Function: Restore Pro Purchase
 * Verifies a $9.99 Pro payment against Stripe by email address.
 *
 * Usage: POST /.netlify/functions/restore-purchase
 * Body: { email }
 *
 * Stripe query strategy:
 *   Payment Links create PaymentIntents with an associated Customer whose email
 *   matches what the buyer typed at checkout. We query the Stripe Customer Search
 *   API (v1/customers/search) for the submitted email, then walk each matching
 *   customer's PaymentIntents (v1/payment_intents?customer=...) looking for a
 *   succeeded intent whose amount is $9.99 (999 cents). This is the most reliable
 *   path for Payment Link purchases because Stripe always attaches a Customer to
 *   Payment Link checkouts and stores the buyer's email on that Customer object.
 *
 *   Fallback: if no Customer is found, we also search v1/charges directly via
 *   receipt_email so we catch edge-cases where a payment was recorded without an
 *   attached customer (e.g., guest checkout fallback).
 *
 * Rate limiting: max 5 attempts per IP per rolling hour, backed by @netlify/blobs.
 * Returns { pro: true } on match, { pro: false } otherwise.
 * Never reveals whether an email exists in Stripe (identical response shape).
 */

const STRIPE_API = 'https://api.stripe.com/v1';
const PRO_AMOUNT_CENTS = 999; // $9.99
const RATE_LIMIT_MAX = 5;
const RATE_LIMIT_WINDOW_MS = 60 * 60 * 1000; // 1 hour

// ── Helpers ──────────────────────────────────────────────────────────────────

function stripeHeaders(key) {
  return {
    'Authorization': `Bearer ${key}`,
    'Content-Type': 'application/x-www-form-urlencoded',
  };
}

async function stripeGet(path, key) {
  const res = await fetch(`${STRIPE_API}${path}`, {
    headers: stripeHeaders(key),
  });
  if (!res.ok) {
    const err = await res.text().catch(() => `HTTP ${res.status}`);
    throw new Error(`Stripe ${path} → ${res.status}: ${err}`);
  }
  return res.json();
}

// ── Rate limiting (Netlify Blobs) ─────────────────────────────────────────────

async function checkRateLimit(ip) {
  let store;
  try {
    const { getStore } = require('@netlify/blobs');
    store = getStore('restore_rate_limits');
  } catch {
    // Blobs not available (local dev) — allow all requests
    return { allowed: true };
  }

  const key = `ip_${ip}`;
  const now = Date.now();

  let record = { attempts: [], windowStart: now };
  try {
    const stored = await store.get(key, { type: 'json' });
    if (stored) record = stored;
  } catch {
    // Key doesn't exist yet — start fresh
  }

  // Purge attempts older than the rolling window
  record.attempts = (record.attempts || []).filter(
    (t) => now - t < RATE_LIMIT_WINDOW_MS
  );

  if (record.attempts.length >= RATE_LIMIT_MAX) {
    return { allowed: false };
  }

  // Record this attempt
  record.attempts.push(now);
  try {
    // TTL slightly beyond the window so old entries expire on their own
    await store.setJSON(key, record, { ttl: Math.ceil(RATE_LIMIT_WINDOW_MS / 1000) + 60 });
  } catch {
    // Non-fatal — allow request through if we can't persist
  }

  return { allowed: true };
}

// ── Stripe lookup ─────────────────────────────────────────────────────────────

/**
 * Search Stripe Customers by email, then check their PaymentIntents.
 * Returns true if any succeeded PaymentIntent has amount == PRO_AMOUNT_CENTS.
 */
async function checkViaCustomerSearch(email, key) {
  const query = encodeURIComponent(`email:'${email}'`);
  const data = await stripeGet(`/customers/search?query=${query}&limit=10`, key);
  const customers = (data.data || []);

  for (const customer of customers) {
    // Walk PaymentIntents for this customer (most recent first, limit 25)
    let url = `/payment_intents?customer=${customer.id}&limit=25`;
    let hasMore = true;

    while (hasMore) {
      const piData = await stripeGet(url, key);
      const intents = piData.data || [];

      for (const pi of intents) {
        if (pi.status === 'succeeded' && pi.amount === PRO_AMOUNT_CENTS) {
          return true;
        }
      }

      hasMore = piData.has_more;
      if (hasMore && intents.length > 0) {
        const last = intents[intents.length - 1];
        url = `/payment_intents?customer=${customer.id}&limit=25&starting_after=${last.id}`;
      } else {
        hasMore = false;
      }
    }
  }

  return false;
}

/**
 * Fallback: search Charges by receipt_email for guest / no-customer cases.
 * Returns true if any succeeded/paid charge has amount == PRO_AMOUNT_CENTS.
 */
async function checkViaCharges(email, key) {
  // Stripe doesn't expose receipt_email in search; use list + filter.
  // We limit to 100 most-recent charges to avoid excessive API calls.
  const query = encodeURIComponent(`receipt_email:'${email}'`);
  // Use Charges Search API (available in newer Stripe API versions)
  const data = await stripeGet(`/charges/search?query=${query}&limit=10`, key);
  const charges = data.data || [];

  for (const ch of charges) {
    if (
      (ch.status === 'succeeded' || ch.paid === true) &&
      ch.amount === PRO_AMOUNT_CENTS
    ) {
      return true;
    }
  }

  return false;
}

// ── Main handler ──────────────────────────────────────────────────────────────

exports.handler = async (event, context) => {
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

  // ── Guard: secret key must exist ──
  const STRIPE_SECRET_KEY = process.env.STRIPE_SECRET_KEY;
  if (!STRIPE_SECRET_KEY) {
    console.error('restore-purchase: STRIPE_SECRET_KEY is not set');
    return {
      statusCode: 503,
      headers,
      body: JSON.stringify({
        error: 'Service temporarily unavailable. Please try again later.',
      }),
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
      body: JSON.stringify({ error: 'Invalid request.' }),
    };
  }

  const rawEmail = body && body.email;
  if (!rawEmail || typeof rawEmail !== 'string' || !rawEmail.includes('@')) {
    return {
      statusCode: 400,
      headers,
      body: JSON.stringify({ error: 'A valid email address is required.' }),
    };
  }

  const email = rawEmail.toLowerCase().trim().slice(0, 254);

  // ── Rate limit ──
  // Netlify puts the real IP in x-nf-client-connection-ip; fall back to x-forwarded-for.
  const clientIp =
    (event.headers && (event.headers['x-nf-client-connection-ip'] ||
      event.headers['x-forwarded-for'] || '')).split(',')[0].trim() || 'unknown';

  const rl = await checkRateLimit(clientIp);
  if (!rl.allowed) {
    return {
      statusCode: 429,
      headers,
      body: JSON.stringify({
        error: 'Too many attempts. Please wait an hour and try again.',
        pro: false,
      }),
    };
  }

  // ── Stripe lookup ──
  let proFound = false;
  try {
    // Primary path: customer search → payment intents
    proFound = await checkViaCustomerSearch(email, STRIPE_SECRET_KEY);

    // Fallback: charges search (handles guest checkout edge-cases)
    if (!proFound) {
      proFound = await checkViaCharges(email, STRIPE_SECRET_KEY);
    }
  } catch (err) {
    // Log server-side only; never leak details to client
    console.error('restore-purchase: Stripe lookup failed:', err.message);
    return {
      statusCode: 503,
      headers,
      body: JSON.stringify({
        error: 'Unable to verify purchase right now. Please try again in a moment.',
        pro: false,
      }),
    };
  }

  // Identical response shape whether pro=true or pro=false to prevent info leakage.
  return {
    statusCode: 200,
    headers,
    body: JSON.stringify({
      pro: proFound,
      message: proFound
        ? 'Purchase verified! Welcome back to Pro.'
        : 'No Pro purchase found for that email. If you used a different email at checkout, please try that one.',
    }),
  };
};
