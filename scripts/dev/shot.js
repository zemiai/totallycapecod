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
const os = require('os');

// Install OUTSIDE the repo so npm can't walk up to the production package.json.
const CACHE = path.join(os.tmpdir(), 'tcc-visual-qa');
function ensureDeps() {
  if (fs.existsSync(path.join(CACHE, 'node_modules', '@sparticuz', 'chromium'))) return;
  fs.mkdirSync(CACHE, { recursive: true });
  // Give the cache its own package.json so npm installs HERE and never walks up
  // to the repo's production package.json. --no-save is belt-and-suspenders.
  fs.writeFileSync(path.join(CACHE, 'package.json'), JSON.stringify({ name: 'visual-qa', private: true, version: '0.0.0' }));
  console.log('[shot] installing headless chromium via npm (one-time this session)…');
  execSync('npm i --no-save --no-audit --no-fund @sparticuz/chromium puppeteer-core', { cwd: CACHE, stdio: 'inherit' });
}

(async () => {
  ensureDeps();
  // Resolve by package name from the cache (honors each package's "exports" field —
  // requiring the directory path directly does not).
  const req = require('module').createRequire(path.join(CACHE, 'package.json'));
  const chromium = req('@sparticuz/chromium').default;
  const puppeteer = req('puppeteer-core');
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
