/**
 * Shared founder-notification helper.
 *
 * Sends an alert to the founder when something worth seeing lands in a Blobs
 * store (a new lead, a first beach report, etc.). Mirrors the pattern already
 * used in feedback.js: Resend if RESEND_API_KEY is set, else a Zapier webhook.
 * Always non-blocking — a notification failure must never break the request.
 *
 * This file lives under lib/ (not a top-level function file) so Netlify does
 * not publish it as its own endpoint; the functions require it relatively.
 */
const FOUNDER_EMAIL = 'dishguyturncook@gmail.com';

async function notifyFounder({ subject, html, replyTo }) {
  try {
    const RESEND_API_KEY = process.env.RESEND_API_KEY;
    if (RESEND_API_KEY) {
      await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: { Authorization: `Bearer ${RESEND_API_KEY}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from: 'Totally Cape Cod <info@totallycapecod.com>',
          to: FOUNDER_EMAIL,
          reply_to: replyTo || undefined,
          subject,
          html,
        }),
      });
      return;
    }
    const zap = process.env.ZAPIER_SUBMISSION_WEBHOOK;
    if (zap) {
      await fetch(zap, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject, html }),
      });
    }
  } catch { /* non-blocking: never let a notification failure break the request */ }
}

module.exports = { notifyFounder, FOUNDER_EMAIL };
