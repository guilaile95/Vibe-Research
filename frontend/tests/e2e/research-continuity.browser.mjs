// Real production-mode React DOM/component acceptance through a test-only parent.
// Intentionally narrower than whole-app route acceptance; no production code fork.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright';
import { continuity, readOnlyReply } from './research-continuity.fixture.mjs';
const frontend = fileURLToPath(new URL('../../', import.meta.url));
const output = process.env.RESEARCH_CONTINUITY_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), 'continuity-dom-'));
mkdirSync(output, { recursive: true });
const dist = join(output, 'component-dist');
process.chdir(frontend);
await build({ configFile: false, mode: 'production', root: join(frontend, 'tests/e2e/research-continuity-adapter'), plugins: [react()], resolve: { alias: { '@': join(frontend, 'src') } }, css: { postcss: frontend }, build: { outDir: dist, emptyOutDir: true } });
if (process.argv.includes('--build-only')) { console.log('Production component adapter built; browser NOT_RUN'); process.exit(0); }
const server = createServer((req, res) => {
  let path = resolve(dist, '.' + new URL(req.url, 'http://local').pathname);
  if (!path.startsWith(resolve(dist) + sep)) path = join(dist, 'index.html');
  if (!existsSync(path) || !extname(path)) path = join(dist, 'index.html');
  res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(path)] || 'application/octet-stream');
  createReadStream(path).pipe(res);
});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const bounded = async promise => { let timer; try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Synthetic request did not arrive')), 10000); })]); } finally { clearTimeout(timer); } };
const results = [], errors = [], unexpected = [], reads = [];
let browser, page, status = 'FAIL';
try {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: 'block' });
    page = await context.newPage(); page.setDefaultTimeout(10000); page.on('pageerror', e => errors.push(e.message));
    const queue = [], all = [];
    const hold = (id, marker, failed = false) => { const gate = deferred(), started = deferred(); const slot = { id, marker, failed, gate, started }; queue.push(slot); all.push(slot); return slot; };
    await context.routeWebSocket('**/*', socket => { unexpected.push(socket.url()); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== base) { unexpected.push(request.url()); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      reads.push(`${request.method()} ${url.pathname}`);
      const slot = queue.shift();
      if (!slot || url.pathname !== `/api/campaigns/${slot.id}/research-continuity`) { unexpected.push(request.url()); return route.fulfill({ status: 503, json: { detail: 'Unexpected synthetic endpoint' } }); }
      const reply = readOnlyReply(request.method(), url.pathname, slot.marker, slot.failed);
      if (!reply) { unexpected.push(request.method() + ' ' + request.url()); return route.abort(); }
      slot.started.resolve(); await slot.gate.promise; await route.fulfill(reply);
    });
    const settle = () => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    const props = async value => { await page.evaluate(value => window.continuityFixture.setProps(value), value); await settle(); };
    const card = () => page.getByTestId('research-continuity');
    const refresh = () => page.getByRole('button', { name: '刷新研究连续性', exact: true });
    const has = async marker => { await card().getByText(`SYNTHETIC_${marker}`, { exact: false }).waitFor(); };
    const release = async slot => { const response = page.waitForResponse(r => new URL(r.url()).pathname === `/api/campaigns/${slot.id}/research-continuity`); slot.gate.resolve(); await (await response).finished(); await settle(); };
    const reset = async () => { await props({ campaignId: 'A', prefetched: continuity('A') }); await has('A'); };
    try {
      await page.goto(base); await has('A');
      for (const failed of [false, true]) {
        await reset(); const stale = hold('A', 'STALE', failed); await refresh().click(); await bounded(stale.started.promise);
        await props({ campaignId: 'B', prefetched: continuity('B') }); await has('B'); await release(stale);
        await has('B'); assert.equal(await card().getByRole('alert').count(), 0); assert.equal(await refresh().isDisabled(), false);
        results.push({ width, scenario: `campaign switch late ${failed ? 'error' : 'success'}`, status: 'PASS' });
        await reset(); const old = hold('A', 'STALE', failed); await refresh().click(); await bounded(old.started.promise);
        await props({ campaignId: 'A', prefetched: continuity('PREFETCH') }); await has('PREFETCH'); await release(old); await has('PREFETCH');
        results.push({ width, scenario: `replacement prefetch late ${failed ? 'error' : 'success'}`, status: 'PASS' });
        await reset(); const manual = hold('A', 'STALE', failed); await refresh().click(); await bounded(manual.started.promise);
        const newer = hold('B', 'NEWER'); await props({ campaignId: 'B' }); await bounded(newer.started.promise); await release(manual);
        assert.equal(await refresh().isDisabled(), true, 'Obsolete finalizer cannot end newer load');
        await release(newer); await has('NEWER'); assert.equal(await refresh().isDisabled(), false);
        results.push({ width, scenario: `newer loading survives late ${failed ? 'error' : 'success'}`, status: 'PASS' });
      }
      await reset(); const old = hold('A', 'STALE'); await refresh().click(); await bounded(old.started.promise);
      await props({ campaignId: 'B', awaitingPrefetch: true }); await release(old); assert.equal(await refresh().isDisabled(), true);
      await props({ campaignId: 'B', prefetched: continuity('B') }); await has('B');
      results.push({ width, scenario: 'batch waiting retains loading ownership', status: 'PASS' });
      await reset(); const unmounted = hold('A', 'UNMOUNTED'); await refresh().click(); await bounded(unmounted.started.promise);
      await page.evaluate(() => window.continuityFixture.setMounted(false)); await settle(); await release(unmounted); assert.equal(await card().count(), 0);
      await page.evaluate(() => window.continuityFixture.setMounted(true)); await has('A');
      results.push({ width, scenario: 'unmount rejects obsolete response', status: 'PASS' });
      const rows = () => card().locator('[data-testid^="research-change-"]');
      assert.equal(await rows().count(), 8);
      const expand = card().getByRole('button', { name: '展开剩余 5 条变化', exact: true });
      assert.equal(await expand.getAttribute('aria-expanded'), 'false'); await expand.click();
      assert.equal(await rows().count(), 13); assert.equal(await card().getByTestId('research-change-changed').count(), 1); assert.equal(await card().getByTestId('research-change-source_conflict').count(), 1);
      const collapse = card().getByRole('button', { name: '收起变化', exact: true }); assert.equal(await collapse.getAttribute('aria-expanded'), 'true');
      const controls = await collapse.getAttribute('aria-controls'); assert.equal(await page.locator(`[id="${controls}"]`).count(), 1);
      await page.screenshot({ path: join(output, `expanded-${width}.png`), fullPage: true }); await collapse.click(); assert.equal(await rows().count(), 8);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'No horizontal page overflow');
      results.push({ width, scenario: '13 actual-projection changes accessible by expand/collapse', status: 'PASS' });
      assert.equal(queue.length, 0);
    } catch (error) {
      await page.screenshot({ path: join(output, `failure-${width}.png`), fullPage: true }).catch(() => {});
      throw error;
    } finally { all.forEach(s => s.gate.resolve()); await context.close(); }
  }
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []); assert.ok(reads.every(r => r.startsWith('GET '))); status = 'PASS';
} catch (error) {
  errors.push(error.stack || String(error));
  if (page && !page.isClosed()) await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  writeFileSync(join(output, 'results.json'), JSON.stringify({ status, scope: 'production-mode real React component DOM with synthetic parent/API; not full-app route or real provider acceptance', results, errors, unexpected, reads }, null, 2));
  await browser?.close(); await new Promise(r => server.close(r)); console.log(JSON.stringify({ status, output, scenarios: results.length }));
}
