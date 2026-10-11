/** CI-only full-app synthetic quote scheduler acceptance. Build first.
 * E2E_LIVE_QUOTES_OUTPUT_DIR is required. No backend, quote provider or model.
 * The app interval is fixed: exercise failure backoff, not a nonexistent setting.
 * Request cancellation, stale responses and freshness are intentionally unchanged.
 */
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { preview } from 'vite';

const root = fileURLToPath(new URL('../..', import.meta.url));
assert.ok(process.env.E2E_LIVE_QUOTES_OUTPUT_DIR, 'Set E2E_LIVE_QUOTES_OUTPUT_DIR');
const output = resolve(process.env.E2E_LIVE_QUOTES_OUTPUT_DIR);
mkdirSync(output, { recursive: true });
const results = { suite: 'live-quotes-ownership', transport: 'synthetic held responses; no backend/provider/model',
  boundary: 'scheduler ownership only; no cancellation or freshness claim', cases: [], status: 'running' };
const record = () => writeFileSync(join(output, 'results.json'), JSON.stringify(results, null, 2));
record();
let browser, server;
try {
  assert.ok(existsSync(join(root, 'dist/index.html')), 'Run npm run build first');
  server = await preview({ root, configFile: false, preview: { host: '127.0.0.1', port: 0, strictPort: true } });
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    const page = await context.newPage(); page.setDefaultTimeout(10000);
    const errors = [], external = [], requests = [], pending = new Set();
    let currentCase = 'initial-readiness';
    page.on('pageerror', error => errors.push(error.message));
    await page.clock.install({ time: new Date('2026-10-12T01:59:59Z') });
    await context.addInitScript(() => {
      localStorage.setItem('vr-watchlist-live', 'off');
      let hidden = false;
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => hidden ? 'hidden' : 'visible' });
      const nativeSet = window.setTimeout.bind(window), nativeClear = window.clearTimeout.bind(window);
      const timers = new Map();
      // Observe real bundled Watchlist timers, without changing scheduling.
      // Fail-closed assertions below also ensure this observes the current bundle.
      window.setTimeout = (callback, ms, ...args) => {
        const owned = /\/Watchlist-[^/\s]+\.js/.test(new Error().stack || '')
          && [3000, 6000, 10000, 12000, 24000, 30000].includes(ms);
        let id;
        id = nativeSet((...values) => { timers.delete(id); callback(...values); }, ms, ...args);
        if (owned) timers.set(id, ms);
        return id;
      };
      window.clearTimeout = id => { timers.delete(id); nativeClear(id); };
      window.__quoteAcceptance = {
        timers: () => [...timers.values()],
        visible: value => { hidden = !value; document.dispatchEvent(new Event('visibilitychange')); },
      };
    });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (request.method() === 'GET' && request.resourceType() === 'stylesheet'
          && url.href === 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap') {
        return route.fulfill({ contentType: 'text/css', body: '/* Offline system font fallback. */' });
      }
      if (url.origin !== origin) { external.push(request.url()); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      if (request.method() !== 'GET') { errors.push(`Unexpected mutation: ${request.method()} ${url.pathname}`); return route.abort(); }
      if (url.pathname === '/api/watchlist') return route.fulfill({ json: { data: {
        status: 'valid', data: { codes: ['600519'], updated_at: '2026-10-12 10:00:00' }, etag: 'synthetic-quotes',
      } } });
      if (url.pathname === '/api/watchlist/anomalies') return route.fulfill({ json: { data: { items: [], unavailable_codes: [] } } });
      if (url.pathname === '/api/native-intel/watchlist-context') return route.fulfill({ json: { data: {
        status: 'ok', codes: ['600519'], degraded: [], securities: [], usage_boundary: 'observation_only_not_an_investment_authority',
      } } });
      if (url.pathname === '/api/quote') {
        let release;
        const gate = new Promise(done => { release = done; });
        const hold = { release, status: 200, codes: url.searchParams.get('codes') };
        requests.push(hold); pending.add(hold);
        const timeout = setTimeout(() => { errors.push('Unreleased synthetic quote hold expired'); release(); }, 20000);
        try {
          await gate;
          await route.fulfill({ status: hold.status, json: hold.status === 200
            ? { data: { '600519': { name: 'Synthetic quote', price: 1300, change_pct: 2.5, amount_wan: 20000 } } }
            : { detail: 'SYNTHETIC_QUOTE_FAILURE' } });
        } catch (error) { errors.push(`Quote route: ${error.message}`); }
        finally { clearTimeout(timeout); pending.delete(hold); }
        return;
      }
      return route.fulfill({ json: { data: {} } });
    });
    const until = async predicate => {
      const deadline = Date.now() + 10000;
      while (!predicate()) { assert.ok(Date.now() < deadline, `Timed out: ${currentCase}`); await new Promise(done => setTimeout(done, 10)); }
    };
    const count = async expected => { await until(() => requests.length >= expected); assert.equal(requests.length, expected); };
    const settle = async (index, status = 200) => {
      requests[index].status = status; requests[index].release(); await until(() => !pending.has(requests[index]));
    };
    const timers = async expected => {
      await page.waitForFunction(value => JSON.stringify(window.__quoteAcceptance.timers()) === JSON.stringify(value), expected);
      assert.deepEqual(await page.evaluate(() => window.__quoteAcceptance.timers()), expected);
    };
    const visibilityBurst = () => page.evaluate(() => {
      for (let i = 0; i < 8; i++) { window.__quoteAcceptance.visible(false); window.__quoteAcceptance.visible(true); }
    });
    const checkpoint = async name => {
      await page.screenshot({ path: join(output, `${width}-${name}.png`), fullPage: true });
      results.cases.push({ width, name, quoteRequests: requests.length, timers: await page.evaluate(() => window.__quoteAcceptance.timers()) }); record();
    };
    try {
      await page.goto(`${origin}/watchlist`, { waitUntil: 'domcontentloaded' });
      currentCase = 'initial-quote-request';
      await count(1); await settle(0);
      currentCase = 'initial-quote-render';
      await page.getByText('Synthetic quote', { exact: true }).first().waitFor();
      await page.getByTitle('开启实时行情（交易时段每 3 秒自动刷新）', { exact: true }).waitFor();
      // React's lazy-route Suspense reveal uses a timer. Keep the installed clock
      // running through concrete app readiness, then freeze while polling is off.
      // The one-second future boundary is required by pauseAt; no quote timer
      // exists yet, so every tested interval still starts from a paused clock.
      await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now() + 1000)));
      await timers([]);
      currentCase = 'enable-first-poll';
      await page.getByTitle('开启实时行情（交易时段每 3 秒自动刷新）', { exact: true }).click();
      await count(2);
      currentCase = 'held-visibility-single-owner';
      await visibilityBurst(); await page.clock.runFor(9000);
      assert.equal(requests.length, 2); await timers([]);
      await settle(1); await timers([3000]); await checkpoint(currentCase);

      currentCase = 'backoff-interval-change';
      await page.clock.runFor(3000); await count(3); await visibilityBurst();
      await settle(2, 503); await timers([6000]);
      await page.clock.runFor(5999); assert.equal(requests.length, 3);
      await page.clock.runFor(1); await count(4); await settle(3); await timers([3000]); await checkpoint(currentCase);

      currentCase = 'hidden-heartbeat-restart';
      await page.evaluate(() => window.__quoteAcceptance.visible(false));
      await page.clock.runFor(3000); await timers([10000]); assert.equal(requests.length, 4);
      await page.evaluate(() => window.__quoteAcceptance.visible(true));
      await count(5); await timers([]); await settle(4); await timers([3000]); await checkpoint(currentCase);

      currentCase = 'disable-pending-cleanup';
      await page.clock.runFor(3000); await count(6);
      await page.getByTitle('关闭实时行情', { exact: true }).click();
      await settle(5); await timers([]); await page.clock.runFor(30000); assert.equal(requests.length, 6);
      await page.getByTitle('开启实时行情（交易时段每 3 秒自动刷新）', { exact: true }).click();
      await count(7); await settle(6); await timers([3000]); await checkpoint(currentCase);

      currentCase = 'spa-unmount-pending-cleanup';
      await page.clock.runFor(3000); await count(8);
      // Actual router transition preserves the document; a reload would hide leaked loops.
      await page.evaluate(() => { history.pushState({}, '', '/settings'); dispatchEvent(new PopStateEvent('popstate')); });
      await page.getByTitle('关闭实时行情', { exact: true }).waitFor({ state: 'detached' });
      await settle(7); await timers([]); await visibilityBurst();
      await page.clock.runFor(30000); assert.equal(requests.length, 8); await timers([]); await checkpoint(currentCase);
      assert.deepEqual(errors, []); assert.deepEqual(external, []);
      writeFileSync(join(output, `${width}-requests.json`), JSON.stringify({ codes: requests.map(r => r.codes), errors, external }, null, 2));
    } catch (error) {
      results.failure = { width, currentCase, message: error.message, errors, external, quoteRequests: requests.length };
      await page.screenshot({ path: join(output, `${width}-failure.png`), fullPage: true }).catch(() => {});
      writeFileSync(join(output, `${width}-failure.html`), await page.content().catch(() => 'Page unavailable'));
      throw error;
    } finally {
      for (const hold of pending) hold.release();
      await context.tracing.stop({ path: join(output, `${width}-trace.zip`) }).catch(() => {});
      await context.close();
    }
  }
  results.status = 'passed';
} catch (error) { results.status = 'failed'; results.error = error.stack; throw error; }
finally {
  record();
  await browser?.close();
  if (server) await new Promise(done => server.httpServer.close(done));
}
console.log('live quote scheduler full-app acceptance: PASS');
