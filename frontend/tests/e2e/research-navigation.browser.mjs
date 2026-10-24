// Production app, disposable browser storage, synthetic intercepted API only.
// Unspecified reads deliberately fail (the product must remain usable without data).
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { checkRequestLifecycle } from './request-lifecycle.fixture.mjs';
import { readReply } from './ai-settings-storage.fixture.mjs';
import { researchEvidenceManifest } from './research-evidence-manifest.fixture.mjs';
import { installResearchWriteAudit } from './research-write-audit.fixture.mjs';
import { navigationEvidencePage } from './research-navigation.fixture.mjs';
import { portfolioEntryFixture, checkPortfolioEntries } from './portfolio-entry.fixture.mjs';
const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
const output = process.env.RESEARCH_NAVIGATION_OUTPUT_DIR || mkdtempSync(join(tmpdir(), 'research-navigation-'));
mkdirSync(output, { recursive: true });
const buildManifest = researchEvidenceManifest(import.meta.url);
writeFileSync(join(output, 'build-manifest.json'), JSON.stringify(buildManifest, null, 2));
const server = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname.startsWith('/api/')) return res.writeHead(503).end();
  let target = resolve(dist, '.' + decodeURIComponent(pathname));
  if (!target.startsWith(resolve(dist) + sep) || !existsSync(target) || !extname(target)) target = join(dist, 'index.html');
  res.setHeader('Content-Type', { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml' }[extname(target)] || 'application/octet-stream');
  createReadStream(target).pipe(res);
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const baseURL = `http://127.0.0.1:${server.address().port}`;
const results = []; let browser;
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
try {
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
  for (const width of [1440, 390, 320]) {
    const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: 'block' });
    const errors = [], external = [], writes = [], reads = []; let record; let slow = false; let phase = 'fixture-init'; let portfolioAuthority = 'LEGACY_PORTFOLIO';
    const storageWrites = await installResearchWriteAudit(context, () => phase);
    const started = deferred(), release = deferred(), finished = deferred();
    await context.routeWebSocket('**/*', socket => { external.push(socket.url()); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
      if (url.origin !== baseURL) { external.push(url.href); return route.abort(); }
      if (!path.startsWith('/api/')) return route.continue();
      const ok = data => route.fulfill({ json: { data } });
      if (request.method() !== 'GET') {
        writes.push({ phase, path, method: request.method(), body: request.postDataJSON() });
        assert.equal(phase, 'create-evidence', 'only the explicit Evidence save may mutate');
        assert.equal(path, '/api/evidence'); assert.equal(request.method(), 'POST');
        record = { ...request.postDataJSON(), id: 'synthetic-evidence', created_at: '2026-10-22T00:00:00Z', updated_at: '2026-10-22T00:00:00Z', deleted: 0 };
        return ok(record);
      }
      reads.push(path + url.search);
      if (path === '/api/portfolio' && !url.search) return ok(portfolioEntryFixture(portfolioAuthority));
      if (path === '/api/watchlist') return ok({ status: 'valid', data: { codes: ['600519'], updated_at: null }, etag: '1111111111111111' });
      if (path === '/api/watchlist/anomalies') return ok({ items: [], unavailable_codes: [], as_of_ms: null });
      if (path === '/api/quote') return ok({});
      if (path === '/api/evidence') return ok(navigationEvidencePage(record ? [record] : [], url.searchParams));
      if (path === '/api/campaigns' || path === '/api/thesis') return ok({ items: [], total: 0 });
      if (path === '/api/native-intel/security-context/600519') return ok({ status: 'normal', security: { code: '600519', company_name: '合成公司' }, mapping: { terms: [], errors: [] }, window_hours: 24, observation: { items: [], item_count: 0 }, rank_history: {} });
      if (path === '/api/valuation' && url.searchParams.get('code') === '600519' && slow) { started.resolve(); await release.promise; try { return await ok({ code: '600519', name: '旧股晚到', price: 1 }); } finally { finished.resolve(); } }
      const reply = readReply('GET', path, url.search); if (reply) return route.fulfill({ json: reply });
      return route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable source' } });
    });
    phase = 'create-page';
    const page = await context.newPage(); page.setDefaultTimeout(10000); page.on('pageerror', error => errors.push(error.message));
    try {
      await checkPortfolioEntries(page, { baseURL, width, output, writes, storageWrites,
        setAuthority: value => { portfolioAuthority = value; },
        phase: async value => { await storageWrites.flush(page); phase = value; await storageWrites.setPhase(page, phase); },
      });
      await storageWrites.flush(page); phase = 'watchlist-entry'; await storageWrites.setPhase(page, phase);
      await page.goto('/watchlist?sort=amount&anomalies=0');
      const entry = page.getByTestId('watchlist-candidate-600519'); await entry.waitFor();
      const expectedReturn = '/watchlist?sort=amount&anomalies=0#watchlist-600519';
      assert.equal(new URL(await entry.getAttribute('href'), baseURL).searchParams.get('return_to'), expectedReturn);
      // Preserve the direct one-click Watchlist data shortcut, not only Candidate's href.
      const directData = page.locator('a[href="/stock-data?code=600519"]').first();
      await directData.click(); await page.getByRole('heading', { name: '个股数据', exact: true }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/stock-data');
      await page.goBack(); await entry.waitFor();
      await entry.click(); await page.getByRole('heading', { name: '候选研究 · 合成公司（600519）', exact: true }).waitFor();
      assert.deepEqual(writes, [], 'initial pure navigation must not save Evidence');
      await storageWrites.flush(page); phase = 'create-evidence'; await storageWrites.setPhase(page, phase);
      await page.getByTestId('candidate-add-evidence').click();
      await page.getByPlaceholder('一句话陈述这条证据说了什么。例如：公司2024Q3营收同比+25%，超出市场一致预期+18%。').fill('合成证据，不含真实研究');
      await page.getByPlaceholder('如：《XX公司2024年三季报点评》').fill('合成来源');
      await page.getByRole('button', { name: '保存', exact: true }).click();
      await storageWrites.flush(page); phase = 'read-saved-evidence'; await storageWrites.setPhase(page, phase);
      await page.getByTestId('candidate-existing-evidence').waitFor();
      assert.equal(record.subject_id, '600519');
      await page.getByTestId('candidate-stock-data-entry').click();
      await page.getByTestId('watchlist-candidate-600519').waitFor();
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).search + new URL(page.url()).hash, expectedReturn);
      assert.equal(await page.getByLabel('自选排序').inputValue(), 'amount');
      await page.screenshot({ path: join(output, `list-return-${width}.png`) });

      await storageWrites.flush(page); phase = 'quote-failure-entry'; await storageWrites.setPhase(page, phase);
      await page.goto('/stock-data?code=600519');
      await page.getByTestId('stock-data-research-without-quote').waitFor();
      const query = page.getByPlaceholder('A 股 6 位代码，或美股/港股/韩股（AAPL / 00700 / 005930.KS）', { exact: true });
      await query.fill('600520');
      const target = new URL(await page.getByTestId('stock-data-candidate-entry').getAttribute('href'), baseURL);
      assert.equal(target.pathname, '/candidates/600519'); assert.equal(new URL(target.searchParams.get('return_to'), baseURL).searchParams.get('code'), '600519');
      await page.getByTestId('stock-data-candidate-entry').click();
      await storageWrites.flush(page); phase = 'fill-candidate-draft'; await storageWrites.setPhase(page, phase);
      // React synchronizes textarea.defaultValue, which makes the wrapping label's
      // text include the draft. Use the unique field placeholder for later reads.
      const tentativeView = page.getByTestId('candidate-research-note').getByPlaceholder('先写目前的理解，不必形成正式结论', { exact: true });
      await tentativeView.waitFor();
      assert.equal(await tentativeView.count(), 1);
      await page.getByLabel('我的暂定看法', { exact: true }).fill('未保存的合成看法');
      await storageWrites.flush(page); phase = 'product-return-blocked'; await storageWrites.setPhase(page, phase);
      await page.getByTestId('candidate-stock-data-entry').click();
      const dialog = page.getByRole('dialog', { name: '研究内容尚未保存' }); await dialog.waitFor();
      await storageWrites.flush(page); phase = 'cancel-product-return'; await storageWrites.setPhase(page, phase);
      await dialog.getByRole('button', { name: '留下继续编辑', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      assert.equal(new URL(page.url()).pathname, '/candidates/600519');
      assert.equal(await tentativeView.inputValue(), '未保存的合成看法');
      await storageWrites.flush(page); phase = 'browser-back-blocked'; await storageWrites.setPhase(page, phase);
      await page.goBack(); await dialog.waitFor();
      await page.waitForURL(url => url.pathname === '/candidates/600519');
      assert.equal(new URL(page.url()).pathname, '/candidates/600519');
      assert.equal(await tentativeView.inputValue(), '未保存的合成看法');
      await storageWrites.flush(page); phase = 'discard-draft-and-return'; await storageWrites.setPhase(page, phase);
      await dialog.getByRole('button', { name: '放弃未保存内容并离开', exact: true }).click();
      await page.waitForURL(url => url.pathname === '/stock-data' && url.searchParams.get('code') === '600519');
      await page.getByTestId('stock-data-candidate-entry').waitFor();
      await page.screenshot({ path: join(output, `quote-failure-${width}.png`) });
      await storageWrites.flush(page); phase = 'reject-non-ashare'; await storageWrites.setPhase(page, phase);
      for (const code of ['', '00700', 'AAPL', 'BAD', '60051']) {
        await page.goto('/stock-data' + (code ? `?code=${code}` : ''));
        await page.getByRole('heading', { name: '个股数据', exact: true }).waitFor();
        assert.equal(await page.getByTestId('stock-data-candidate-entry').count(), 0, code);
      }
      await storageWrites.flush(page); phase = 'reject-unsafe-return-targets'; await storageWrites.setPhase(page, phase);
      for (const value of ['//evil.example', '/%2fevil.example', '/%255cevil.example', 'https://evil.example', '/bad%']) {
        await page.goto('/candidates/600519?' + new URLSearchParams({ return_to: value }));
        assert.equal(await page.getByTestId('candidate-stock-data-entry').getAttribute('href'), '/stock-data?code=600519');
      }
      await page.goto('/candidates/600519?return_to=%2Fwatchlist&return_to=%2Fother');
      assert.equal(await page.getByTestId('candidate-stock-data-entry').getAttribute('href'), '/stock-data?code=600519');
      await storageWrites.flush(page); phase = 'late-old-quote'; await storageWrites.setPhase(page, phase);
      slow = true; await page.goto('/stock-data?code=600519'); await started.promise;
      const cancelled = page.waitForEvent('requestfailed', { predicate: request => {
        const url = new URL(request.url());
        return url.pathname === '/api/valuation' && url.searchParams.get('code') === '600519';
      } });
      await query.fill('600520'); await query.press('Enter');
      await page.waitForFunction(() => document.querySelector('[data-active-code="600520"]'));
      assert.match((await cancelled).failure()?.errorText || '', /abort|cancel/i);
      release.resolve(); await finished.promise;
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
      assert.equal(new URL(await page.getByTestId('stock-data-candidate-entry').getAttribute('href'), baseURL).pathname, '/candidates/600520');
      assert.equal(await page.getByText('旧股晚到', { exact: true }).count(), 0);
      phase = 'request-lifecycle';
      const requestLifecycle = await checkRequestLifecycle(page, { baseURL, width, output });
      assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.equal(writes.length, 1);
      await storageWrites.flush(page);
      assert.deepEqual(storageWrites.filter(event => event.kind !== 'navigation-preference'), [], 'navigation never writes research questions or notes');
      assert.deepEqual(writes.filter(event => event.phase !== 'create-evidence'), [], 'navigation phase has zero formal writes');
      results.push({ width, status: 'PASS', checkoutSha: buildManifest.checkoutSha, checkoutTree: buildManifest.checkoutTree, checks: storageWrites.phases, requestLifecycle, reads, writes, storageWrites });
    } catch (error) {
      const dom = await page.evaluate(() => ({
        url: location.href,
        candidateCode: document.querySelector('[data-testid="candidate-workspace"]')?.getAttribute('data-security-code'),
        dialogs: [...document.querySelectorAll('dialog')].map(node => ({ open: node.open, text: node.textContent })),
        draftFields: [...document.querySelectorAll('[data-testid="candidate-research-note"] textarea')].map(node => ({ placeholder: node.placeholder, value: node.value, defaultValue: node.defaultValue, labelText: node.closest('label')?.textContent })),
      })).catch(cause => ({ diagnosticError: cause.message }));
      results.push({ width, status: 'FAIL', phase, error: error.message, stack: error.stack, dom, errors, external, reads, writes }); await page.screenshot({ path: join(output, `failure-${width}.png`) }); throw error; }
    finally { release.resolve(); await context.close(); }
  }
} finally { writeFileSync(join(output, 'results.json'), JSON.stringify(results, null, 2)); await browser?.close(); server.closeAllConnections(); await new Promise(done => server.close(done)); console.log(output); }
