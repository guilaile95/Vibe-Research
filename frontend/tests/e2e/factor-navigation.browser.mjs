/** Offline browser acceptance of production routing with controlled delayed API responses. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium } from 'playwright';
const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
const server = createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://local').pathname;
  const file = pathname.startsWith('/assets/') ? path.join(dist, pathname) : path.join(dist, 'index.html');
  try { const content = await readFile(file); res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); res.end(content); }
  catch { res.writeHead(404); res.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--disable-background-networking'] });
  const context = await browser.newContext();
  let release, started;
  const report = { status: 'unavailable', results: {}, limitations: ['synthetic completed result'] };
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname.endsWith('/factor-validation/registry')) return route.fulfill({ json: { factors: [{ factor_id: 'return_5d', label: 'Return 5d' }] } });
    if (url.pathname.endsWith('/factor-validation/evaluate')) {
      started?.();
      await new Promise(resolve => { release = resolve; });
      // Aborted browser waits do not remove or cancel a stored server result.
      try { await route.fulfill({ json: report }); } catch { /* request already aborted */ }
      return;
    }
    if (url.pathname === '/api/research-experiments') return route.fulfill({ json: { records: [] } });
    return route.fulfill({ status: 503, json: { detail: 'offline fixture boundary' } });
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const evidence = process.env.E2E_SCREENSHOT_DIR;
  if (evidence) await mkdir(evidence, { recursive: true });
  const shot = async name => { if (evidence) await page.screenshot({ path: path.join(evidence, name + '.png'), fullPage: true }); };
  async function open() {
    await page.goto(`${origin}/signals/factor-validation?keep=yes`);
    await page.getByRole('button', { name: '运行因子验证', exact: true }).waitFor();
  }
  async function start() {
    const requestStarted = new Promise(resolve => { started = resolve; });
    await page.getByRole('button', { name: '运行因子验证', exact: true }).click();
    await requestStarted;
  }
  await open(); await start();
  // Research analytics is a secondary entry under Trades, not a global link.
  // Follow the real client-side navigation so the pending request loses ownership.
  await page.locator('a[href="/trades"]').first().click();
  await page.waitForURL('**/trades');
  await page.locator('a[href="/research-analytics"]').first().click();
  await page.waitForURL('**/research-analytics');
  release(); await page.waitForTimeout(100);
  assert.equal(new URL(page.url()).pathname, '/research-analytics');
  assert.equal(await page.getByTestId('factor-validation').count(), 0);
  await shot('navigation-stays-on-current-page');
  await open(); await start();
  await page.getByLabel('因子验证起始日期').fill('2025-01-01');
  release(); await page.waitForTimeout(100);
  assert.equal(new URL(page.url()).search, '?keep=yes');
  assert.equal(await page.getByText('synthetic completed result').count(), 0);
  await start(); release();
  await page.getByText('synthetic completed result').waitFor();
  assert.equal(new URL(page.url()).searchParams.get('keep'), 'yes');
  assert.equal(new URL(page.url()).searchParams.get('factor'), 'return_5d');
  assert.equal(new URL(page.url()).searchParams.get('from'), '2025-01-01');
  await shot('current-factor-result-preserves-query');
  assert.deepEqual(pageErrors, []);
  // Router remains live after its own search update and a subsequent real tab navigation.
  await page.getByRole('button', { name: /历史验证/ }).click();
  await page.waitForURL('**/signals/validation');
  assert.equal(await page.getByTestId('factor-validation').count(), 0);
  console.log('PASS: delayed navigation, input invalidation, current result, preserved query, router tab transition');
} finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
