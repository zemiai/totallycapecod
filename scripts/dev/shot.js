#!/usr/bin/env node
/**
 * Visual QA screenshot helper for the Claude Code on-web sandbox.
 *
 * The sandbox's egress allowlist blocks the Playwright / Chrome-for-Testing CDNs,
 * so `playwright install` fails. But npm + GitHub are allowlisted, and
 * @sparticuz/chromium ships a headless Chromium binary through npm — so this works.
 *
 * Usage:
 *   node scripts/dev/shot.js <url> [out.png] [width] [height] [waitMs]
 *   e.g. node scripts/dev/shot.js http://localhost:8000/app/ /tmp/app.png 390 844
 *
 * Deps self-install (once per session) into scripts/dev/.cache (git-ignored).
 */
const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const CACHE = path.join(__dirname, '.cache');
function ensureDeps() {
  try { require.resolve('@sparticuz/chromium', { paths: [path.join(CACHE, 'node_modules')] }); return; } catch {}
  fs.mkdirSync(CACHE, { recursive: true });
  console.log('[shot] installing headless chromium via npm (one-time this session)…');
  execSync('npm i --no-audit --no-fund @sparticuz/chromium puppeteer-core', { cwd: CACHE, stdio: 'inherit' });
}

(async () => {
  ensureDeps();
  const chromium = require(path.join(CACHE, 'node_modules/@sparticuz/chromium')).default;
  const puppeteer = require(path.join(CACHE, 'node_modules/puppeteer-core'));
  const [url, out = 'shot.png', w = '1440', h = '900', wait = '2500'] = process.argv.slice(2);
  if (!url) { console.error('usage: node scripts/dev/shot.js <url> [out.png] [w] [h] [waitMs]'); process.exit(1); }
  const width = +w, height = +h, mobile = width < 700;
  const browser = await puppeteer.launch({
    args: [...chromium.args, '--no-sandbox', '--disable-setuid-sandbox'],
    executablePath: await chromium.executablePath(), headless: 'shell',
  });
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile });
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
  await new Promise(r => setTimeout(r, +wait));
  await page.screenshot({ path: out });
  console.log('[shot] saved', out, `(${width}x${height})`);
  await browser.close();
})().catch(e => { console.error('[shot] ERR', e.message); process.exit(1); });
