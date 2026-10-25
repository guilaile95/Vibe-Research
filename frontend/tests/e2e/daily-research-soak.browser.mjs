// Bounded CI-only repeated workflow experiment. Synthetic APIs, real disposable
// browser storage, no model/backend/user data. This is not Product Reality Day 1.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { performance } from 'node:perf_hooks';
import { chromium } from 'playwright';
import { readReply } from './ai-settings-storage.fixture.mjs';
import { researchCheckReadReply } from './research-check-loop.fixture.mjs';
import { isExpectedSoakUnavailable, isExpectedSoakConsoleError } from './daily-research-soak.fixture.mjs';
import { researchEvidenceManifest } from './research-evidence-manifest.fixture.mjs';

const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
const output = process.env.DAILY_RESEARCH_SOAK_OUTPUT_DIR || mkdtempSync(join(tmpdir(), 'daily-research-soak-'));
mkdirSync(output, { recursive: true });
const manifest = researchEvidenceManifest(import.meta.url);
const longSoak = process.argv.includes('--long-soak');
assert.ok(process.argv.slice(2).every(arg => arg === '--long-soak'), 'unknown soak argument');
const iterations = longSoak ? 120 : 24; // Below the 200-note local storage cap.
const viewportBudgetMs = longSoak ? 450_000 : null; // Two viewports: ~15 minutes total.
const hardLimitMs = longSoak ? 960_000 : null; // Bounds slow operations plus cleanup.
let hardLimitReached = false;
let hardLimitTimer;
const experimentStarted = performance.now();
const results = [];
let browser;
const server = createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  if (path.startsWith('/api/')) return res.writeHead(503).end();
  let target = resolve(dist, '.' + decodeURIComponent(path));
  if (!target.startsWith(resolve(dist) + sep) || !existsSync(target) || !extname(target)) target = join(dist, 'index.html');
  res.setHeader('Content-Type', { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }[extname(target)] || 'application/octet-stream');
  createReadStream(target).pipe(res);
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const baseURL = `http://127.0.0.1:${server.address().port}`;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
  if (hardLimitMs) hardLimitTimer = setTimeout(() => {
    hardLimitReached = true;
    void browser.close().catch(() => {}); // Unblock any pending action; finally preserves partial evidence.
  }, hardLimitMs);
  for (const width of [1440, 390]) {
    const started = performance.now();
    const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: 'block' });
    const errors = [], external = [], mutations = [], reads = [], samples = [], consoleErrors = [], expectedUnavailable = [], unexpectedRequests = [], cycles = [];
    let page, phase = 'setup', cdp;
    await context.routeWebSocket('**/*', socket => { external.push(socket.url()); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
      if (url.origin !== baseURL) { external.push(url.href); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      if (request.method() !== 'GET') {
        mutations.push({ phase, method: request.method(), path: url.pathname });
        return route.fulfill({ status: 500, json: { detail: 'Synthetic soak forbids backend/model mutations' } });
      }
      reads.push({ phase, path: url.pathname, query: url.search });
      const reply = researchCheckReadReply(url.pathname, url.search) ?? readReply('GET', url.pathname, url.search);
      if (reply !== null) return route.fulfill({ json: reply });
      if (isExpectedSoakUnavailable(request.method(), url.pathname, url.search)) {
        expectedUnavailable.push({ phase, path: url.pathname, query: url.search });
        return route.fulfill({ status: 503, json: { detail: 'Synthetic optional source unavailable' } });
      }
      unexpectedRequests.push({ phase, method: request.method(), path: url.pathname, query: url.search });
      return route.fulfill({ status: 500, json: { detail: 'Unexpected fixture request' } });
    });
    const openPage = async () => {
      page = await context.newPage(); page.setDefaultTimeout(15000);
      page.on('pageerror', error => errors.push({ phase, message: error.message }));
      page.on('console', message => { if (message.type() === 'error') consoleErrors.push({ phase, text: message.text(), url: message.location().url }); });
      cdp = await context.newCDPSession(page);
      await cdp.send('Performance.enable');
    };
    const snapshot = async iteration => {
      // GC changes the experiment; record both readings and do not call a plateau
      // proof of absence of leaks. Saved notes intentionally grow each iteration.
      const before = await cdp.send('Performance.getMetrics');
      await cdp.send('HeapProfiler.collectGarbage');
      const after = await cdp.send('Performance.getMetrics');
      const keep = metrics => Object.fromEntries(metrics.metrics.filter(row => ['JSHeapUsedSize', 'JSHeapTotalSize', 'Nodes', 'Documents', 'JSEventListeners', 'TaskDuration'].includes(row.name)).map(row => [row.name, row.value]));
      const storage = await page.evaluate(() => {
        const raw = localStorage.getItem('vr-notes.v2');
        return { bytes: new TextEncoder().encode(raw || '').length, notes: raw ? JSON.parse(raw).notes.length : 0 };
      });
      samples.push({ iteration, elapsedMs: performance.now() - started, beforeGC: keep(before), afterGC: keep(after), storage, pages: context.pages().length });
    };
    try {
      await openPage();
      phase = 'discovery-keyboard-entry';
      await page.goto('/screener?mode=discovery&strategy=SWING');
      const candidate = page.getByTestId('discovery-candidate-600519');
      await candidate.waitFor(); await candidate.focus();
      assert.equal(await candidate.evaluate(node => node === document.activeElement), true);
      await page.keyboard.press('Enter');
      await page.getByTestId('candidate-discovery-context').waitFor();
      assert.match(await page.getByTestId('candidate-discovery-context').innerText(), /市场发现/);
      await snapshot(0);
      for (let iteration = 1; iteration <= iterations; iteration++) {
        if (longSoak && performance.now() - started >= viewportBudgetMs) break;
        const cycleStart = performance.now();
        phase = `cycle-${iteration}-save`;
        const panel = page.getByTestId('candidate-research-note');
        const judgement = `合成循环 ${iteration}：资料不足，保持待核，不构成真实投资判断。`;
        await panel.getByLabel('我的暂定看法', { exact: true }).fill(judgement);
        await panel.getByLabel('下次核对', { exact: true }).fill(`合成下一问 ${iteration}`);
        const save = panel.getByRole('button', { name: '保存暂定研究', exact: true });
        await save.focus(); await page.keyboard.press('Enter');
        await panel.getByRole('button', { name: '已保存暂定研究', exact: true }).waitFor();
        const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('vr-notes.v2')).notes);
        assert.equal(saved.length, iteration);
        assert.equal(saved[0].research.securityCode, '600519');
        assert.equal(saved[0].research.tentativeView, judgement);
        phase = `cycle-${iteration}-known-stock-return`;
        await page.getByTestId('candidate-open-stock-data').click();
        await page.getByRole('heading', { name: '个股数据', exact: true }).waitFor();
        await page.getByTestId('stock-data-research-without-quote').waitFor();
        const back = page.getByTestId('stock-data-candidate-entry');
        const target = new URL(await back.getAttribute('href'), baseURL);
        assert.equal(target.pathname, '/candidates/600519');
        await back.click(); await panel.waitFor();
        await panel.getByText(`下次核对：合成下一问 ${iteration}`, { exact: false }).waitFor();
        assert.equal(await page.getByRole('dialog', { name: '研究内容尚未保存' }).isVisible(), false);
        // Route return must not recursively amplify return_to on repeated visits.
        assert.ok(page.url().length < 1500);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        assert.equal(await page.locator('vite-error-overlay').count(), 0);
        if (iteration % 8 === 0) {
          phase = `cycle-${iteration}-close-reopen`;
          const href = page.url(); await cdp.detach(); await page.close(); await openPage();
          await page.goto(href); await page.getByTestId('candidate-research-note').waitFor();
          const reopened = await page.evaluate(() => JSON.parse(localStorage.getItem('vr-notes.v2')).notes);
          assert.deepEqual(reopened, saved, 'closing/reopening must retain all acknowledged synthetic notes');
          assert.equal(context.pages().length, 1);
        }
        const activeMs = performance.now() - cycleStart;
        const idleStarted = performance.now();
        if (longSoak) {
          phase = `cycle-${iteration}-idle`;
          await page.waitForTimeout(Math.min(10_000, Math.max(0, viewportBudgetMs - (performance.now() - started))));
        }
        cycles.push({ iteration, activeMs, idleMs: performance.now() - idleStarted, elapsedMs: performance.now() - cycleStart });
        if (iteration % 4 === 0) await snapshot(iteration);
      }
      phase = 'final';
      assert.equal(hardLimitReached, false, 'hard wall-time limit reached');
      if (longSoak) {
        assert.ok(performance.now() - started >= viewportBudgetMs, 'iteration cap ended long soak before its observation window');
        assert.ok(cycles.length >= 8, 'long soak must complete at least one close/reopen batch');
      }
      await snapshot(cycles.length);
      assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(mutations, []);
      assert.deepEqual(unexpectedRequests, [], 'all synthetic requests must be explicitly classified');
      assert.deepEqual(consoleErrors.filter(row => !isExpectedSoakConsoleError(row, baseURL)), [], 'only exact same-origin optional-source 503 errors are expected');
      assert.equal(context.pages().length, 1);
      await page.screenshot({ path: join(output, `daily-soak-${width}.png`), fullPage: false });
      results.push({ width, status: 'PASS', phase, iterations: cycles.length, iterationCap: iterations, elapsedMs: performance.now() - started, cycles, samples, errors, external, mutations, consoleErrors, reads, expectedUnavailable, unexpectedRequests });
    } catch (error) {
      results.push({ width, status: 'FAIL', phase, error: error.message, stack: error.stack, iterations: cycles.length, cycles, elapsedMs: performance.now() - started, samples, errors, external, mutations, consoleErrors, reads, expectedUnavailable, unexpectedRequests });
      await page?.screenshot({ path: join(output, `failure-${width}.png`) }).catch(() => {});
      throw error;
    } finally { await context.close(); }
    results.at(-1).contextsRemainingAfterClose = browser.contexts().length;
    assert.equal(browser.contexts().length, 0, 'the disposable context must be closed');
  }
} finally {
  clearTimeout(hardLimitTimer);
  writeFileSync(join(output, 'results.json'), JSON.stringify({ manifest, browserVersion: browser?.version(), mode: longSoak ? 'bounded-active-idle' : 'short-regression', elapsedMs: performance.now() - experimentStarted, hardLimitReached, viewportBudgetMs, hardLimitMs, workload: longSoak ? '450 seconds per viewport, save/SPA-return alternating with up to10-second idle; close/reopen every8;120-cycle cap per viewport' : '24 save/SPA-return cycles per viewport, close/reopen every8;48 cycles total', boundary: 'Synthetic sources and unavailable optional quotes, no real models or natural use. Sequential timings are not a benchmark. CDP JS heap is not process RSS. Heap includes deliberate saved-note growth; not a long-term leak proof.', results }, null, 2));
  await browser?.close(); server.closeAllConnections(); await new Promise(done => server.close(done));
  console.log(output);
}
