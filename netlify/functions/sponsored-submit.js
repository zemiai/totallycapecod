/**
 * Netlify Function: Sponsored Listing Submission
 * Stores business listing submissions and forwards to Zapier
 *
 * Usage: POST /.netlify/functions/sponsored-submit
 * Body: { name, category, description, website, email, phone, town, tier, photos[] }
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

  const { name, category, description, website, email, phone, town, tier, photos } = body;

  if (!name || !email || !category) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'Name, email, and category are required' }) };
  }

  const submission = {
    id: `sub_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name: name.toString().slice(0, 100),
    category: category.toString().slice(0, 50),
    description: (description || '').toString().slice(0, 2000),
    website: (website || '').toString().slice(0, 500),
    email: email.toLowerCase().trim(),
    phone: (phone || '').toString().slice(0, 30),
    town: (town || '').toString().slice(0, 100),
    tier: (tier || 'basic').toString().slice(0, 20),
    photos: Array.isArray(photos) ? photos.slice(0, 5) : [],
    status: 'pending',
    submitted_at: new Date().toISOString(),
  };

  // Store in Netlify blobs
  try {
    const { getStore } = require('@netlify/blobs');
    const store = getStore('submissions');
    await store.setJSON(submission.id, submission);
  } catch {
    // Blobs not available locally
  }

  // Forward to Zapier
  const ZAPIER_WEBHOOK = process.env.ZAPIER_SUBMISSION_WEBHOOK;
  if (ZAPIER_WEBHOOK) {
    try {
      await fetch(ZAPIER_WEBHOOK, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(submission),
      });
    } catch {
      // Non-blocking
    }
  }

  // Send confirmation email via Resend
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
          from: 'Totally Cape Cod <info@totallycapecod.com>',
          to: submission.email,
          subject: 'We received your listing submission! ☀️',
          html: `<p>Hi ${submission.name},</p><p>Thanks for submitting your business to Totally Cape Cod! We've received your ${submission.tier} listing and will review it within 24 hours.</p><p>Here's what's next:</p><ul><li>Our team reviews all submissions for quality and accuracy</li><li>Once approved, your listing goes live on the site</li><li>Paid featured listings get priority placement</li></ul><p>Questions? Just reply to this email.</p><p>— The Totally Cape Cod Team</p>`,
        }),
      });
    } catch {
      // Non-blocking
    }
  }

  return {
    statusCode: 200,
    headers,
    body: JSON.stringify({ success: true, id: submission.id, message: 'Submission received!' }),
  };
};
