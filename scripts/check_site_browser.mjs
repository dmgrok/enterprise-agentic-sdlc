import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(new URL('../tools/diagrams/package.json', import.meta.url));
const puppeteer = require('puppeteer');
const executablePath = [process.env.PUPPETEER_EXECUTABLE_PATH, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium'].find(path => path && existsSync(path));
if (!executablePath) throw new Error('Chrome is required for actual browser verification');
const types = { '.html': 'text/html', '.mjs': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.svg': 'image/svg+xml' };
const server = createServer(async (req, res) => {
  try {
    const path = resolve(root, '_site', '.' + decodeURIComponent(new URL(req.url, 'http://localhost').pathname === '/' ? '/index.html' : new URL(req.url, 'http://localhost').pathname));
    if (!path.startsWith(resolve(root, '_site') + '/')) throw new Error('Invalid path');
    const bytes = await readFile(path); res.setHeader('Content-Type', types[extname(path)] || 'application/octet-stream'); res.end(bytes);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await puppeteer.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage(); const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewport({ width: 1440, height: 1100, deviceScaleFactor: 1 });
  await page.goto(`http://127.0.0.1:${server.address().port}`, { waitUntil: 'networkidle0' });
  await page.waitForSelector('.edge-control');
  assert.ok(await page.$$eval('.case-button', buttons => buttons.length >= 2));
  assert.equal(await page.$eval('#case-title', node => node.textContent), 'When a stablecoin slips');
  await page.click('#challenge-link');
  assert.match(await page.$eval('#reachability', node => node.textContent), /1 connection challenged/);
  assert.ok(await page.$$eval('.node.unreachable', nodes => nodes.length >= 1));
  await page.click('#reset-links');
  assert.equal(await page.$$eval('.node.unreachable', nodes => nodes.length), 0);
  await page.select('#connection-picker', 'collateral-mark');
  assert.equal(await page.$eval('.evidence h3', node => node.textContent), 'The collateral is worth less');
  await page.click('[data-case="rate-surprise"]');
  assert.equal(await page.$eval('#case-title', node => node.textContent), 'The rate surprise');
  assert.match(await page.$eval('.source-link', node => node.href), /federalreserve\.gov/);
  await page.click('[data-case="stablecoin-fracture"]');
  await mkdir(resolve(root, 'reports/site'), { recursive: true });
  await page.screenshot({ path: resolve(root, 'reports/site/desktop.png'), fullPage: true });
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 });
  await page.screenshot({ path: resolve(root, 'reports/site/mobile.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'Mobile page must not overflow');
  await page.select('#connection-picker', 'margin-pressure');
  await page.click('#challenge-link');
  assert.match(await page.$eval('#reachability', node => node.textContent), /challenged/);
  await page.reload({ waitUntil: 'networkidle0' });
  assert.equal(await page.$eval('#challenge-link', node => node.getAttribute('aria-pressed')), 'true', 'Shareable URL preserves the challenged connection');
  assert.deepEqual(errors, []);
  // Verify the real error/recovery state rather than a decorative placeholder.
  await page.setRequestInterception(true);
  page.on('request', req => req.url().endsWith('/data/catalog.json') ? req.abort() : req.continue());
  await page.reload({ waitUntil: 'networkidle0' });
  assert.equal(await page.$eval('#load-error', node => node.hidden), false);
  console.log('Browser checks passed: desktop/mobile, evidence, counterfactual, shareable state and error recovery');
} finally {
  await browser.close(); await new Promise(resolve => server.close(resolve));
}
