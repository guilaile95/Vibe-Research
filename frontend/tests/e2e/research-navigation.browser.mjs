// Production app, disposable browser storage, synthetic intercepted API only.
// Unspecified reads deliberately fail (the product must remain usable without data).
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { readReply } from './ai-settings-storage.fixture.mjs';
const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
const output = process.env.RESEARCH_NAVIGATION_OUTPUT_DIR || mkdtempSync(join(tmpdir(), 'research-navigation-'));
mkdirSync(output, { recursive: true });
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
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: 'block' });
    const errors = [], external = [], writes = [], reads = []; let record; let slow = false;
    const started = deferred(), release = deferred();
    await context.routeWebSocket('**/*', socket => { external.push(socket.url()); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
      if (url.origin !== baseURL) { external.push(url.href); return route.abort(); }
      if (!path.startsWith('/api/')) return route.continue();
      const ok = data => route.fulfill({ json: { data } });
      if (request.method() !== 'GET') {
        writes.push({ path, method: request.method(), body: request.postDataJSON() });
        assert.equal(path, '/api/evidence'); assert.equal(request.method(), 'POST');
        record = { ...request.postDataJSON(), id: 'synthetic-evidence', created_at: '2026-10-22T00:00:00Z', updated_at: '2026-10-22T00:00:00Z', deleted: 0 };
        return ok(record);
      }
      reads.push(path + url.search);
      if (path === '/api/watchlist') return ok({ status: 'valid', data: { codes: ['600519'], updated_at: null }, etag: 'synthetic' });
      if (path === '/api/watchlist/anomalies') return ok({ items: [], unavailable_codes: [], as_of_ms: null });
      if (path === '/api/quote') return ok({});
      if (path === '/api/evidence') return ok({ items: record ? [record] : [], total: record ? 1 : 0 });
      if (path === '/api/campaigns' || path === '/api/thesis') return ok({ items: [], total: 0 });
      if (path === '/api/native-intel/security-context/600519') return ok({ status: 'normal', security: { code: '600519', company_name: '合成公司' }, mapping: { terms: [], errors: [] }, window_hours: 24, observation: { items: [], item_count: 0 }, rank_history: {} });
      if (path === '/api/valuation' && url.searchParams.get('code') === '600519' && slow) { started.resolve(); await release.promise; return ok({ code: '600519', name: '旧股晚到', price: 1 }); }
      const reply = readReply('GET', path, url.search); if (reply) return route.fulfill({ json: reply });
      return route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable source' } });
    });
    const page = await context.newPage(); page.setDefaultTimeout(10000); page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto('/watchlist?sort=amount&anomalies=0');
      const entry = page.getByTestId('watchlist-candidate-600519'); await entry.waitFor();
      const expectedReturn = '/watchlist?sort=amount&anomalies=0#watchlist-600519';
      assert.equal(new URL(await entry.getAttribute('href'), baseURL).searchParams.get('return_to'), expectedReturn);
      await entry.click(); await page.getByRole('heading', { name: '候选研究 · 合成公司（600519）', exact: true }).waitFor();
      await page.getByTestId('candidate-add-evidence').click();
      await page.getByPlaceholder('一句话陈述这条证据说了什么。例如：公司2024Q3营收同比+25%，超出市场一致预期+18%。').fill('合成证据，不含真实研究');
      await page.getByPlaceholder('如：《XX公司2024年三季报点评》').fill('合成来源');
      await page.getByRole('button', { name: '保存', exact: true }).click();
      await page.getByTestId('candidate-existing-evidence').waitFor();
      assert.equal(record.subject_id, '600519');
      await page.getByTestId('candidate-stock-data-entry').click();
      await page.getByTestId('watchlist-candidate-600519').waitFor();
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).search + new URL(page.url()).hash, expectedReturn);
      assert.equal(await page.getByLabel('自选排序').inputValue(), 'amount');
      await page.screenshot({ path: join(output, `list-return-${width}.png`) });

      await page.goto('/stock-data?code=600519');
      await page.getByTestId('stock-data-research-without-quote').waitFor();
      const query = page.getByPlaceholder('A 股 6 位代码，或美股/港股/韩股（AAPL / 00700 / 005930.KS）', { exact: true });
      await query.fill('600520');
      const target = new URL(await page.getByTestId('stock-data-candidate-entry').getAttribute('href'), baseURL);
      assert.equal(target.pathname, '/candidates/600519'); assert.equal(new URL(target.searchParams.get('return_to'), baseURL).searchParams.get('code'), '600519');
      await page.getByTestId('stock-data-candidate-entry').click();
      await page.getByLabel('我的暂定看法', { exact: true }).fill('未保存的合成看法');
      await page.getByTestId('candidate-stock-data-entry').click();
      const dialog = page.getByRole('dialog', { name: '研究内容尚未保存' }); await dialog.waitFor();
      await dialog.getByRole('button', { name: '留在此页', exact: true }).click();
      await page.goBack(); await dialog.waitFor();
      await dialog.getByRole('button', { name: '放弃未保存内容并离开', exact: true }).click();
      await page.getByTestId('stock-data-candidate-entry').waitFor();
      await page.screenshot({ path: join(output, `quote-failure-${width}.png`) });
      for (const code of ['', '00700', 'AAPL', 'BAD', '60051']) {
        await page.goto('/stock-data' + (code ? `?code=${code}` : ''));
        await page.getByRole('heading', { name: '个股数据', exact: true }).waitFor();
        assert.equal(await page.getByTestId('stock-data-candidate-entry').count(), 0, code);
      }
      for (const value of ['//evil.example', '/%2fevil.example', '/%255cevil.example', 'https://evil.example', '/bad%']) {
        await page.goto('/candidates/600519?' + new URLSearchParams({ return_to: value }));
        assert.equal(await page.getByTestId('candidate-stock-data-entry').getAttribute('href'), '/stock-data?code=600519');
      }
      await page.goto('/candidates/600519?return_to=%2Fwatchlist&return_to=%2Fother');
      assert.equal(await page.getByTestId('candidate-stock-data-entry').getAttribute('href'), '/stock-data?code=600519');
      slow = true; await page.goto('/stock-data?code=600519'); await started.promise;
      await query.fill('600520'); await query.press('Enter');
      await page.waitForFunction(() => document.querySelector('[data-active-code="600520"]'));
      release.resolve(); await page.waitForTimeout(100);
      assert.equal(new URL(await page.getByTestId('stock-data-candidate-entry').getAttribute('href'), baseURL).pathname, '/candidates/600520');
      assert.equal(await page.getByText('旧股晚到', { exact: true }).count(), 0);
      assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.equal(writes.length, 1);
      results.push({ width, status: 'PASS', reads, writes });
    } catch (error) { results.push({ width, status: 'FAIL', error: error.message, errors, external, reads, writes }); await page.screenshot({ path: join(output, `failure-${width}.png`) }); throw error; }
    finally { release.resolve(); await context.close(); }
  }
} finally { writeFileSync(join(output, 'results.json'), JSON.stringify(results, null, 2)); await browser?.close(); server.closeAllConnections(); await new Promise(done => server.close(done)); console.log(output); }
