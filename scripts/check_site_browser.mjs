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
  await page.click('[data-case="open-model-release"]');
  await page.waitForSelector('[data-price-series="NVDA"]');
  assert.equal(await page.$eval('#market-analysis', n => n.hidden), false);
  assert.match(await page.$eval('#market-readout', n => n.textContent), /-16\.97%/);
  await page.click('[data-group="frontier"]');
  assert.match(await page.$eval('#market-group-title', n => n.textContent), /no direct price series/);
  assert.equal(await page.$$eval('[data-price-series="NVDA"]', n => n.length), 0);
  assert.equal(await page.$eval('.evidence h3', n => n.textContent), 'Could customers switch?');
  await page.click('[data-group="chips"]');
  assert.equal(await page.$$eval('[data-price-series="AVGO"]', n => n.length), 1);
  await page.select('#market-mode', 'relative');
  assert.match(await page.$eval('#market-baseline', n => n.textContent), /Difference in returns/);
  await page.click('[data-event="release"]');
  assert.match(await page.$eval('#market-baseline', n => n.textContent), /17 Jan/);
  assert.match(await page.$eval('#market-selected-date', n => n.textContent), /21 Jan/);
  await page.select('#market-window', 'full');
  assert.equal(await page.$eval('#market-date', n => n.max), '18');
  await page.click('[data-symbol="GOOGL"]');
  assert.equal(await page.$$eval('[data-price-series="GOOGL"]', n => n.length), 1);
  await page.click('[data-event="selloff"]');
  await page.select('#market-mode', 'indexed');
  await page.select('#market-window', 'near');
  await page.click('[data-group="all"]');
  await mkdir(resolve(root, 'reports/site'), { recursive: true });
  await page.screenshot({ path: resolve(root, 'reports/site/desktop.png'), fullPage: true });
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 });
  await page.screenshot({ path: resolve(root, 'reports/site/mobile.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'Mobile page must not overflow');
  // Keyboard operation of the date scrubber exposes exact data on mobile.
  await page.focus('#market-date');
  const priorDate = await page.$eval('#market-selected-date', n => n.textContent);
  await page.keyboard.press('ArrowRight');
  assert.notEqual(await page.$eval('#market-selected-date', n => n.textContent), priorDate);
  await page.$eval('[data-node="profit-outlook"]', node => node.focus());
  await page.keyboard.press('Enter');
  assert.match(await page.$eval('#market-group-title', n => n.textContent), /Frontier labs/);
  await page.click('[data-case="stablecoin-fracture"]');
  assert.equal(await page.$eval('#market-analysis', n => n.hidden), true);
  await page.select('#connection-picker', 'margin-pressure');
  await page.click('#challenge-link');
  assert.match(await page.$eval('#reachability', node => node.textContent), /challenged/);
  await page.reload({ waitUntil: 'networkidle0' });
  assert.equal(await page.$eval('#challenge-link', node => node.getAttribute('aria-pressed')), 'true', 'Shareable URL preserves the challenged connection');
  assert.deepEqual(errors, []);
  // A missing market snapshot must leave the mechanism map usable and recover on retry.
  await page.setRequestInterception(true);
  const blockPrices = req => req.url().endsWith('/data/deepseek-2025.json') ? req.abort() : req.continue();
  page.on('request', blockPrices);
  await page.goto(`http://127.0.0.1:${server.address().port}/?market-failure=1#case=open-model-release`, { waitUntil: 'networkidle0' });
  await page.waitForSelector('#market-loading button');
  assert.ok(await page.$$eval('.edge-control', nodes => nodes.length > 0));
  page.off('request', blockPrices);
  await page.setRequestInterception(false);
  await page.click('#market-loading button');
  await page.waitForSelector('[data-price-series="NVDA"]');
  // Verify the real error/recovery state rather than a decorative placeholder.
  await page.setRequestInterception(true);
  page.on('request', req => req.url().endsWith('/data/catalog.json') ? req.abort() : req.continue());
  await page.reload({ waitUntil: 'networkidle0' });
  assert.equal(await page.$eval('#load-error', node => node.hidden), false);
  assert.deepEqual(errors, []);
  console.log('Browser checks passed: desktop/mobile, evidence, counterfactual, shareable state and error recovery');
} finally {
  await browser.close(); await new Promise(resolve => server.close(resolve));
}
