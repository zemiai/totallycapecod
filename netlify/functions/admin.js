/**
 * Netlify Function: founder admin dashboard.
 *
 * One password-gated page that reads the Blobs stores the app writes to and
 * lists recent activity — so reports/leads/feedback don't sit unseen:
 *   - feedback     (in-app feedback,      feedback.js)
 *   - leads        (newsletter signups,   email-capture.js)
 *   - submissions  (business listings,    sponsored-submit.js)
 *   - beach-reports(crowdsourced status,  beach-report.js)
 *
 * Auth: set ADMIN_KEY in Netlify env vars, then open
 *   https://totallycapecod.com/admin?key=YOUR_KEY
 * (a /admin rewrite points here; the raw function URL works too). Not linked
 * anywhere and marked noindex. Rotate ADMIN_KEY to revoke access.
 */
const crypto = require('crypto');

const MAX_PER_STORE = 500;      // safety cap on keys scanned per store
const SHOW = 60;                // rows rendered per section

function safeEqual(a, b) {
  a = String(a || ''); b = String(b || '');
  if (!a || !b || a.length !== b.length) return false;
  try { return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b)); }
  catch { return false; }
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmt(t) {
  const d = typeof t === 'number' ? new Date(t) : new Date(String(t || ''));
  return isNaN(d) ? '—' : d.toLocaleString('en-US', { timeZone: 'America/New_York' });
}

function getStore(name) {
  try { return require('@netlify/blobs').getStore(name); } catch { return null; }
}

async function readAll(store, { skip } = {}) {
  if (!store) return [];
  const out = [];
  try {
    const { blobs } = await store.list();
    const keys = (blobs || []).map(b => b.key).filter(k => !skip || !skip(k)).slice(0, MAX_PER_STORE);
    await Promise.all(keys.map(async (key) => {
      const val = await store.get(key, { type: 'json' }).catch(() => null);
      if (val) out.push({ key, val });
    }));
  } catch { /* store unreadable — return what we have */ }
  return out;
}

function section(title, count, rowsHtml) {
  return `<section><h2>${esc(title)} <span class="count">${count}</span></h2>`
       + (rowsHtml || `<p class="empty">Nothing yet.</p>`) + `</section>`;
}

function table(head, rows) {
  if (!rows.length) return '';
  return `<div class="scroll"><table><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>`
       + `<tbody>${rows.join('')}</tbody></table></div>`;
}

exports.handler = async (event) => {
  const H = { 'Content-Type': 'text/html; charset=utf-8', 'X-Robots-Tag': 'noindex, nofollow', 'Cache-Control': 'no-store' };

  const ADMIN_KEY = process.env.ADMIN_KEY;
  if (!ADMIN_KEY) {
    return { statusCode: 500, headers: H,
      body: `<h1>Admin not configured</h1><p>Set <code>ADMIN_KEY</code> in Netlify environment variables, then reload with <code>?key=…</code>.</p>` };
  }

  const provided = (event.queryStringParameters && event.queryStringParameters.key)
    || ((event.headers.authorization || '').replace(/^Bearer\s+/i, ''));
  if (!safeEqual(provided, ADMIN_KEY)) {
    return { statusCode: 401, headers: H, body:
      `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">`
      + `<body style="font-family:system-ui;max-width:420px;margin:12vh auto;padding:24px;text-align:center">`
      + `<h2>🔒 Totally Cape Cod admin</h2>`
      + `<form method="GET"><input name="key" type="password" placeholder="Admin key" autofocus `
      + `style="width:100%;padding:12px;font-size:16px;border:1px solid #ccc;border-radius:10px;margin:12px 0">`
      + `<button style="width:100%;padding:12px;font-size:16px;background:#173a63;color:#fff;border:0;border-radius:10px">View</button></form></body>` };
  }

  // --- gather ---
  const [feedback, leads, subs, beaches] = await Promise.all([
    readAll(getStore('feedback')),
    readAll(getStore('leads'), { skip: k => k.startsWith('email:') }),
    readAll(getStore('submissions')),
    readAll(getStore('beach-reports'), { skip: k => k.startsWith('ip:') }),
  ]);

  // feedback: newest first
  feedback.sort((a, b) => new Date(b.val.at) - new Date(a.val.at));
  const fbRows = feedback.slice(0, SHOW).map(({ val }) =>
    `<tr><td>${fmt(val.at)}</td><td>${esc(val.email || 'anonymous')}</td><td>${esc(val.context || 'app')}</td><td>${esc(val.message)}</td></tr>`);

  // leads: newest first
  leads.sort((a, b) => new Date(b.val.timestamp) - new Date(a.val.timestamp));
  const leadRows = leads.slice(0, SHOW).map(({ val }) =>
    `<tr><td>${fmt(val.timestamp)}</td><td>${esc(val.email)}</td><td>${esc(val.source)}</td><td>${esc(val.url)}</td></tr>`);

  // submissions: newest first
  subs.sort((a, b) => new Date(b.val.submitted_at) - new Date(a.val.submitted_at));
  const subRows = subs.slice(0, SHOW).map(({ val }) =>
    `<tr><td>${fmt(val.submitted_at)}</td><td>${esc(val.name)}</td><td>${esc(val.tier)}</td><td>${esc(val.town)}</td><td>${esc(val.category)}</td><td>${esc(val.email)} ${esc(val.phone)}</td></tr>`);

  // beach reports: latest per slug, within 3h
  const now = Date.now(), WIN = 3 * 60 * 60 * 1000;
  const beachRows = beaches.map(({ key, val }) => {
    const recent = (val.reports || []).filter(r => now - r.at < WIN).sort((a, b) => b.at - a.at);
    return { key, latest: recent[0], count: recent.length };
  }).filter(b => b.latest).sort((a, b) => b.latest.at - a.latest.at).map(b =>
    `<tr><td>${fmt(b.latest.at)}</td><td>${esc(b.key)}</td><td><strong>${esc((b.latest.status || '').toUpperCase())}</strong></td><td>${b.count}</td></tr>`);

  const body = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>TCC Admin</title><style>
:root{--navy:#173a63;--sand:#f3cd93;--ink:#2b2b2b}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f7f1e1;color:var(--ink)}
header{background:var(--navy);color:#fff;padding:16px 20px}header h1{margin:0;font-size:18px}
.wrap{max-width:1000px;margin:0 auto;padding:16px}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 18px}
.card{flex:1;min-width:120px;background:#fff;border-radius:12px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card .n{font-size:26px;font-weight:800;color:var(--navy)}.card .l{font-size:12px;color:#777;text-transform:uppercase;letter-spacing:.04em}
section{background:#fff;border-radius:12px;padding:14px 16px;margin:0 0 16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h2{font-size:15px;margin:0 0 10px;color:var(--navy)}.count{background:var(--sand);color:#5a3d12;border-radius:20px;padding:1px 9px;font-size:12px;vertical-align:middle}
.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #eee;vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#999}
td:first-child{white-space:nowrap;color:#666}.empty{color:#999;font-size:13px;margin:4px 0}
.foot{color:#999;font-size:12px;text-align:center;padding:8px 0 24px}
</style></head><body>
<header><h1>🐚 Totally Cape Cod — Admin</h1></header>
<div class="wrap">
<div class="cards">
  <div class="card"><div class="n">${feedback.length}</div><div class="l">Feedback</div></div>
  <div class="card"><div class="n">${leads.length}</div><div class="l">Email leads</div></div>
  <div class="card"><div class="n">${subs.length}</div><div class="l">Submissions</div></div>
  <div class="card"><div class="n">${beachRows.length}</div><div class="l">Live beaches</div></div>
</div>
${section('💬 Feedback', feedback.length, table(['When (ET)', 'From', 'Context', 'Message'], fbRows))}
${section('📥 Email leads', leads.length, table(['When (ET)', 'Email', 'Source', 'Page'], leadRows))}
${section('🏪 Business submissions', subs.length, table(['When (ET)', 'Business', 'Tier', 'Town', 'Category', 'Contact'], subRows))}
${section('🏖️ Beach reports (last 3h)', beachRows.length, table(['Last (ET)', 'Beach', 'Status', 'Reports'], beachRows))}
<div class="foot">Live from Netlify Blobs · showing up to ${SHOW}/section · times in ET</div>
</div></body></html>`;

  return { statusCode: 200, headers: H, body };
};
