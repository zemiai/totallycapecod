/**
 * Netlify Function: Email Capture
 * Stores email leads and optionally forwards to Zapier webhook
 *
 * Usage: POST /.netlify/functions/email-capture
 * Body: { email, source, url, timestamp }
 */

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
    return { statusCode: 405, headers, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid JSON' }) };
  }

  const { email, source, url, timestamp } = body;

  if (!email || !email.includes('@')) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'Valid email required' }) };
  }

  // Sanitize
  const cleanEmail = email.toLowerCase().trim();
  const cleanSource = (source || 'unknown').toString().slice(0, 50);

  // Store in Netlify blobs (available on Netlify)
  try {
    const { getStore } = require('@netlify/blobs');
    const store = getStore('leads');
    const id = `lead_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    await store.setJSON(id, {
      email: cleanEmail,
      source: cleanSource,
      url: url || '',
      timestamp: timestamp || new Date().toISOString(),
    });
  } catch {
    // Blobs not available locally or not configured — that's fine
  }

  // Forward to Zapier/Make webhook if configured
  const ZAPIER_WEBHOOK = process.env.ZAPIER_EMAIL_WEBHOOK;
  if (ZAPIER_WEBHOOK) {
    try {
      await fetch(ZAPIER_WEBHOOK, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: cleanEmail, source: cleanSource, url, timestamp }),
      });
    } catch {
      // Zapier failure is non-blocking
    }
  }

  // Forward to Mailchimp/Resend if configured
  const RESEND_API_KEY = process.env.RESEND_API_KEY;
  if (RESEND_API_KEY) {
    try {
      await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${RESEND_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from: 'Totally Cape Cod <hello@totallycapecod.com>',
          to: cleanEmail,
          subject: 'Your Free 2026 Cape Cod Vibe Guide is here! 🌊',
          html: `<p>Hey there!</p><p>Thanks for joining Totally Cape Cod. Here's your free <strong>2026 Vibe Guide</strong> — a curated PDF with hidden beaches, secret sunset spots, the best lobster rolls, and a ready-to-use week-long itinerary.</p><p><a href="https://totallycapecod.netlify.app/vibe-guide-2026.pdf" style="background:#1A3A6C;color:white;padding:12px 24px;border-radius:10px;text-decoration:none;display:inline-block;">Download My Guide</a></p><p>See you on the Cape!</p>`,
        }),
      });
    } catch {
      // Email send failure is non-blocking
    }
  }

  return {
    statusCode: 200,
    headers,
    body: JSON.stringify({ success: true, message: 'Subscribed!' }),
  };
};
