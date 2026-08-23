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
 * Auth: set ADMIN_KEY in Netlify env vars, then open /admin and enter it in the
 * login form. A successful login creates an HttpOnly secure session cookie so
 * the secret never needs to remain in the address bar.
 */
const crypto = require('crypto');
const BUNDLED_METRICS = require('../../data/metrics.json');

const MAX_PER_STORE = 500;      // safety cap on keys scanned per store
const SHOW = 60;                // rows rendered per section
const COOKIE_NAME = 'tcc_admin';
const COOKIE_MAX_AGE = 60 * 60 * 12;

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
  if (!store) return { rows: [], error: 'Netlify Blobs is unavailable in this function.' };
  const out = [];
  try {
    const { blobs } = await store.list();
    const keys = (blobs || []).map(b => b.key).filter(k => !skip || !skip(k)).slice(0, MAX_PER_STORE);
    await Promise.all(keys.map(async (key) => {
      const val = await store.get(key, { type: 'json' }).catch(() => null);
      if (val) out.push({ key, val });
    }));
    return { rows: out, error: null };
  } catch (err) {
    return { rows: out, error: err && err.message ? err.message : 'Store could not be read.' };
  }
}

function parseCookies(raw) {
  return String(raw || '').split(';').reduce((all, pair) => {
    const i = pair.indexOf('=');
    if (i < 0) return all;
    const key = pair.slice(0, i).trim();
    const value = pair.slice(i + 1).trim();
    if (key) all[key] = decodeURIComponent(value);
    return all;
  }, {});
}

function sessionToken(adminKey) {
  return crypto.createHmac('sha256', adminKey).update('totally-cape-cod-admin-v1').digest('hex');
}

function loginPage(message = '') {
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">`
    + `<meta name="robots" content="noindex"><title>TCC Admin Login</title></head>`
    + `<body style="font-family:system-ui;max-width:420px;margin:12vh auto;padding:24px;text-align:center">`
    + `<h2>🔒 Totally Cape Cod admin</h2>`
    + (message ? `<p style="color:#a33">${esc(message)}</p>` : '')
    + `<form method="POST"><input name="key" type="password" placeholder="Admin key" autofocus autocomplete="current-password" `
    + `style="width:100%;padding:12px;font-size:16px;border:1px solid #ccc;border-radius:10px;margin:12px 0">`
    + `<button style="width:100%;padding:12px;font-size:16px;background:#173a63;color:#fff;border:0;border-radius:10px">Log in</button></form></body></html>`;
}

function formBody(event) {
  try { return new URLSearchParams(event.body || ''); } catch { return new URLSearchParams(); }
}

async function loadMetrics() {
  const url = 'https://raw.githubusercontent.com/zemiai/totallycapecod/main/data/metrics.json';
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(6000), headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
    return { metrics: await response.json(), source: 'live GitHub report', error: null };
  } catch (remoteError) {
    try {
      // Static require is deliberate: Netlify's bundler can trace this fallback
      // even if included_files behavior changes between CLI/runtime versions.
      const metrics = JSON.parse(JSON.stringify(BUNDLED_METRICS));
      return { metrics, source: 'bundled fallback', error: `Live report unavailable: ${remoteError.message}` };
    } catch (fileError) {
      return { metrics: {}, source: 'unavailable', error: `Live report: ${remoteError.message}; bundled report: ${fileError.message}` };
    }
  }
}

async function loadStripe30d() {
  const key = process.env.STRIPE_REPORTING_KEY || process.env.STRIPE_SECRET_KEY;
  if (!key) return { data: null, error: 'STRIPE_SECRET_KEY / STRIPE_REPORTING_KEY not set' };
  const since = Math.floor((Date.now() - 30 * 24 * 60 * 60 * 1000) / 1000);
  let startingAfter = null, intents = [];
  try {
    for (let page = 0; page < 10; page += 1) {
      const qs = new URLSearchParams({ limit: '100', 'created[gte]': String(since) });
      if (startingAfter) qs.set('starting_after', startingAfter);
      const response = await fetch(`https://api.stripe.com/v1/payment_intents?${qs}`, {
        signal: AbortSignal.timeout(8000),
        headers: { Authorization: `Basic ${Buffer.from(`${key}:`).toString('base64')}` }
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error && payload.error.message ? payload.error.message : `Stripe returned ${response.status}`);
      intents = intents.concat(payload.data || []);
      if (!payload.has_more || !(payload.data || []).length) break;
      startingAfter = payload.data[payload.data.length - 1].id;
    }
    const paid = intents.filter(p => p.status === 'succeeded');
    const currency = paid[0] ? String(paid[0].currency || 'usd').toUpperCase() : 'USD';
    return {
      data: {
        window: 'last_30d', sales: paid.length,
        revenue: paid.reduce((sum, p) => sum + Number(p.amount_received || p.amount || 0), 0) / 100,
        currency, source: 'live Stripe API'
      },
      error: null
    };
  } catch (err) {
    return { data: null, error: err && err.message ? err.message : 'Stripe request failed' };
  }
}

async function checkStore(name) {
  const store = getStore(name);
  if (!store) return { name, ok: false, detail: 'Netlify Blobs unavailable' };
  const key = `__admin_health_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`;
  try {
    await store.setJSON(key, { ok: true, at: new Date().toISOString() });
    const value = await store.get(key, { type: 'json' });
    await store.delete(key);
    return { name, ok: Boolean(value && value.ok), detail: value && value.ok ? 'write/read/delete passed' : 'readback failed' };
  } catch (err) {
    try { await store.delete(key); } catch { /* best-effort cleanup */ }
    return { name, ok: false, detail: err && err.message ? err.message : 'health check failed' };
  }
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

  const cookies = parseCookies(event.headers.cookie || event.headers.Cookie);
  const bearer = (event.headers.authorization || '').replace(/^Bearer\s+/i, '');
  const expectedSession = sessionToken(ADMIN_KEY);
  const hasSession = safeEqual(cookies[COOKIE_NAME], expectedSession);
  const hasBearer = safeEqual(bearer, ADMIN_KEY);

  if (event.httpMethod === 'POST' && !hasSession && !hasBearer) {
    const supplied = formBody(event).get('key');
    if (!safeEqual(supplied, ADMIN_KEY)) {
      return { statusCode: 401, headers: H, body: loginPage('That admin key was not accepted.') };
    }
    return {
      statusCode: 303,
      headers: { ...H, Location: '/admin', 'Set-Cookie': `${COOKIE_NAME}=${expectedSession}; Path=/admin; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Strict` },
      body: ''
    };
  }

  if (event.queryStringParameters && event.queryStringParameters.logout === '1') {
    return {
      statusCode: 303,
      headers: { ...H, Location: '/admin', 'Set-Cookie': `${COOKIE_NAME}=; Path=/admin; Max-Age=0; HttpOnly; Secure; SameSite=Strict` },
      body: ''
    };
  }

  if (!hasSession && !hasBearer) {
    return { statusCode: 401, headers: H, body: loginPage() };
  }

  // --- gather ---
  const metricsResult = await loadMetrics();
  const metrics = metricsResult.metrics;
  let metricsError = metricsResult.error;

  // Netlify already needs STRIPE_SECRET_KEY for purchase restoration. Reuse it
  // server-side so the admin can show current sales even when the GitHub metrics
  // workflow has no separate STRIPE_REPORTING_KEY configured.
  const stripeLive = await loadStripe30d();
  if (stripeLive.data) metrics.stripe = stripeLive.data;
  else if (!metrics.stripe || metrics.stripe.skipped) {
    metrics.stripe = { error: stripeLive.error || 'Stripe reporting unavailable' };
  }

  let healthResults = null;
  if (event.httpMethod === 'POST' && formBody(event).get('action') === 'storage-health') {
    healthResults = await Promise.all(['feedback', 'leads', 'submissions', 'beach-reports'].map(checkStore));
  }

  const [feedbackResult, leadsResult, subsResult, beachesResult] = await Promise.all([
    readAll(getStore('feedback')),
    readAll(getStore('leads'), { skip: k => k.startsWith('email:') }),
    readAll(getStore('submissions')),
    readAll(getStore('beach-reports'), { skip: k => k.startsWith('ip:') }),
  ]);
  const feedback = feedbackResult.rows, leads = leadsResult.rows,
        subs = subsResult.rows, beaches = beachesResult.rows;
  const storeResults = [
    ['Feedback', feedbackResult], ['Email leads', leadsResult],
    ['Business submissions', subsResult], ['Beach reports', beachesResult]
  ];

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

  // ---- Metrics (data/metrics.json, refreshed nightly) ----
  const money = n => '$' + Number(n || 0).toFixed(2);
  const ads = metrics.meta_ads || {}, stripe = metrics.stripe || {},
        ga4 = metrics.ga4 || {}, gsc = metrics.gsc || {};
  const adRows = (ads.ads || []).map(a =>
    `<tr><td>${esc(a.ad)}</td><td>${money(a.spend)}</td><td>${a.impressions}</td>`
    + `<td>${a.clicks}</td><td>${a.ctr}%</td><td>${money(a.cpc)}</td></tr>`);
  const flagHtml = (ads.flags || []).length
    ? `<div class="flags"><strong>⚠️ Spend flags</strong><ul>`
      + ads.flags.map(f => `<li>${esc(f)}</li>`).join('') + `</ul></div>` : '';
  const campRows = Object.entries(ga4.by_campaign || {}).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td>${v}</td></tr>`);
  const qRows = (gsc.queries || []).map(q =>
    `<tr><td>${esc(q.q)}</td><td>${q.clicks}</td><td>${q.impressions}</td></tr>`);
  const notReady = k => (metrics[k] && (metrics[k].skipped || metrics[k].error))
    ? `<p class="empty">${esc(metrics[k].skipped || metrics[k].error)}</p>` : '';

  const sourceStatus = (label, value, ready) => `<li><strong>${esc(label)}:</strong> `
    + (ready ? `<span class="ok">connected</span>` : `<span class="warn">${esc(value || 'not configured')}</span>`) + `</li>`;
  const diagnosticsHtml = `<section><h2>🩺 System status</h2>`
    + `<p class="${metricsError ? 'warn' : 'ok'}"><strong>Metrics report:</strong> ${esc(metricsResult.source)}`
    + ` · generated ${esc(metrics.generated_at || 'time unavailable')}${metricsError ? ` · ${esc(metricsError)}` : ''}</p>`
    + `<ul class="status">`
    + storeResults.map(([label, result]) => sourceStatus(label, result.error, !result.error)).join('')
    + sourceStatus('Meta Ads reporting', ads.skipped || ads.error, Array.isArray(ads.ads))
    + sourceStatus('Stripe reporting', stripe.skipped || stripe.error, stripe.sales != null)
    + sourceStatus('Google Analytics', ga4.skipped || ga4.error, ga4.sessions != null)
    + sourceStatus('Search Console', gsc.skipped || gsc.error, Array.isArray(gsc.queries))
    + `</ul>`
    + `<form method="POST"><input type="hidden" name="action" value="storage-health">`
    + `<button class="testbtn">Run storage write/read/delete test</button></form>`
    + (healthResults ? `<div class="health">${healthResults.map(r => `<p class="${r.ok ? 'ok' : 'error'}">${r.ok ? '✓' : '✕'} ${esc(r.name)} — ${esc(r.detail)}</p>`).join('')}</div>` : '')
    + `</section>`;

  const metricsHtml = `
${section('💸 Ad spend (last 7 days)', ads.ads ? ads.ads.length : 0,
    (flagHtml || '') + table(['Ad', 'Spend', 'Impr.', 'Clicks', 'CTR', 'CPC'], adRows)
    + notReady('meta_ads'))}
${section('💵 Sales (last 30 days)', stripe.sales || 0,
    stripe.sales != null
      ? `<p><strong>${stripe.sales}</strong> sales · <strong>${money(stripe.revenue)}</strong> revenue</p>`
      : notReady('stripe'))}
${section('📈 Traffic by campaign (last 7 days)', ga4.sessions || 0,
    (ga4.sessions != null
      ? `<p><strong>${ga4.sessions}</strong> sessions · ${ga4.users} users · ${ga4.purchases} purchases</p>` : '')
    + table(['Campaign', 'Sessions'], campRows) + notReady('ga4'))}
${section('🔍 Top search queries (last 7 days)', (gsc.queries || []).length,
    table(['Query', 'Clicks', 'Impressions'], qRows) + notReady('gsc'))}`;

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
.flags{background:#FDF3E3;border-left:4px solid #C45448;border-radius:8px;padding:10px 14px;margin:0 0 12px;font-size:13px}
.flags ul{margin:6px 0 0;padding-left:18px}
.ok{color:#176b3a}.warn{color:#95620a}.error{color:#a32b25}.status{line-height:1.8;padding-left:20px}
.testbtn{background:var(--navy);color:#fff;border:0;border-radius:9px;padding:10px 14px;font-weight:700;cursor:pointer}
.health{margin-top:10px}.health p{margin:5px 0;font-size:13px}
.logout{float:right;color:#fff;font-size:13px;font-weight:500}
.foot{color:#999;font-size:12px;text-align:center;padding:8px 0 24px}
</style></head><body>
<header><h1>🐚 Totally Cape Cod — Admin <a class="logout" href="/admin?logout=1">Log out</a></h1></header>
<div class="wrap">
<div class="cards">
  <div class="card"><div class="n">${feedback.length}</div><div class="l">Feedback</div></div>
  <div class="card"><div class="n">${leads.length}</div><div class="l">Email leads</div></div>
  <div class="card"><div class="n">${subs.length}</div><div class="l">Submissions</div></div>
  <div class="card"><div class="n">${beachRows.length}</div><div class="l">Live beaches</div></div>
  <div class="card"><div class="n">${ads.total_spend != null ? money(ads.total_spend) : '—'}</div><div class="l">Ad spend 7d</div></div>
  <div class="card"><div class="n">${stripe.revenue != null ? money(stripe.revenue) : '—'}</div><div class="l">Revenue 30d</div></div>
</div>
${diagnosticsHtml}
${metricsHtml}
${section('💬 Feedback', feedback.length, table(['When (ET)', 'From', 'Context', 'Message'], fbRows))}
${section('📥 Email leads', leads.length, table(['When (ET)', 'Email', 'Source', 'Page'], leadRows))}
${section('🏪 Business submissions', subs.length, table(['When (ET)', 'Business', 'Tier', 'Town', 'Category', 'Contact'], subRows))}
${section('🏖️ Beach reports (last 3h)', beachRows.length, table(['Last (ET)', 'Beach', 'Status', 'Reports'], beachRows))}
<div class="foot">Live from Netlify Blobs · showing up to ${SHOW}/section · times in ET</div>
</div></body></html>`;

  return { statusCode: 200, headers: H, body };
};
