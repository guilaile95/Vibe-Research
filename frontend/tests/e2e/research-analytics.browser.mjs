// Production React page + API client, fixed synthetic response parity checked by backend tests.
// Actual browser launch is CI-only; --build-only stops before any listener/browser.
import assert from 'node:assert/strict';
import { createReadStream, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright';
const frontend = fileURLToPath(new URL('../../', import.meta.url));
const output = process.env.RESEARCH_ANALYTICS_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), 'research-analytics-'));
mkdirSync(output, { recursive: true });
const dist = join(output, 'component-dist');
const fixture = JSON.parse(readFileSync(new URL('./research-analytics.fixture.json', import.meta.url), 'utf8'));
await build({ configFile: false, root: join(frontend, 'tests/e2e/research-analytics-adapter'), plugins: [react()],
  resolve: { alias: { '@': join(frontend, 'src') } }, css: { postcss: frontend }, build: { outDir: dist, emptyOutDir: true } });
if (process.argv.includes('--build-only')) { console.log('Research analytics production page built; browser NOT_RUN'); process.exit(0); }
if (process.env.GITHUB_ACTIONS !== 'true') throw Error('Actual browser acceptance is restricted to existing GitHub CI');
const audit = { external: [], unexpected: [], errors: [], requests: [] };
const server = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/favicon.ico') { res.writeHead(204).end(); return; }
  const target = pathname === '/' ? join(dist, 'index.html') : resolve(dist, '.' + pathname);
  if (!target.startsWith(dist + sep) || !existsSync(target)) { audit.unexpected.push(req.url); res.writeHead(404).end(); return; }
  res.setHeader('Content-Type', { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' }[extname(target)] || 'application/octet-stream');
  createReadStream(target).pipe(res);
});
let browser, page, release = null, status = 'FAIL';
const checks = [];
try {
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  const origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ['--disable-background-networking', '--dns-prefetch-disable'],
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: 'block' });
    await context.routeWebSocket('**/*', socket => { audit.external.push(socket.url()); socket.close(); });
    let behavior = 'normal', arrival = null;
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== origin) { audit.external.push(url.origin); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      audit.requests.push(req.method() + ' ' + url.pathname);
      const example = url.pathname.match(/^\/api\/research-analytics\/example\/(simulation|scenario|performance|ledger-performance|cost-comparison)$/);
      if (example && req.method() === 'GET') return route.fulfill({ json: { synthetic: true, input: fixture[example[1]].input } });
      const result = url.pathname.match(/^\/api\/research-analytics\/(simulation|scenario|performance|ledger-performance|cost-comparison)$/);
      if (result && req.method() === 'POST') {
        assert.deepEqual(req.postDataJSON(), fixture[result[1]].input);
        if (behavior.startsWith('malformed:')) {
          const patches = [{ status: {} }, { limitations: null }, { curve: [null] }, { metrics: { x: null } }];
          return route.fulfill({ json: { ...fixture[result[1]].result, ...patches[Number(behavior.split(':')[1])] } });
        }
        if (behavior === 'error') return route.fulfill({ status: 422, json: { detail: 'SYNTHETIC_CONTRACT_ERROR' } });
        if (behavior === 'hold') { arrival?.(); await new Promise(done => { release = done; }); }
        return route.fulfill({ json: fixture[result[1]].result });
      }
      audit.unexpected.push(req.method() + ' ' + url.pathname);
      return route.fulfill({ status: 503, json: { detail: 'UNEXPECTED_TEST_REQUEST' } });
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on('pageerror', error => audit.errors.push(error.message));
    await page.goto(origin);
    await page.getByRole('heading', { name: '研究计算实验室' }).waitFor();
    await page.getByRole('button', { name: '载入合成示例' }).click();
    await page.getByTestId('synthetic-warning').waitFor();
    await page.getByRole('button', { name: '只读计算', exact: true }).click();
    await page.getByTestId('research-analytics-result').waitFor();
    assert.match(await page.getByTestId('research-analytics-result').innerText(), /固定上游实际 20 项/);
    await page.getByRole('img', { name: '只读研究净值路径' }).waitFor();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2));
    await page.screenshot({ path: join(output, `simulation-${width}.png`), fullPage: true });
    for (const [label, text] of [['风险与历史情景', '历史 VaR'], ['估值与资金收益', 'TWR'], ['正式账本只读投影', 'MISSING_INPUTS'], ['FIFO / 均价比较', '分币种成本比较']]) {
      await page.getByRole('tab', { name: label, exact: true }).click();
      assert.equal(await page.getByTestId('research-analytics-result').count(), 0);
      await page.getByRole('button', { name: '载入合成示例' }).click();
      await page.getByTestId('synthetic-warning').waitFor();
      await page.getByRole('button', { name: '只读计算', exact: true }).click();
      await page.getByTestId('research-analytics-result').waitFor();
      assert((await page.getByTestId('research-analytics-result').innerText()).includes(text));
    }
    await page.getByRole('tab', { name: '假设策略模拟', exact: true }).click();
    await page.getByRole('button', { name: '载入合成示例' }).click();
    await page.getByTestId('synthetic-warning').waitFor();
    for (let bad = 0; bad < 4; bad++) {
      behavior = `malformed:${bad}`;
      await page.getByRole('button', { name: '只读计算', exact: true }).click();
      await page.getByRole('alert').waitFor();
      assert.equal(await page.getByTestId('research-analytics-result').count(), 0);
      assert.notEqual(await page.locator('#analytics-input').inputValue(), '');
    }
    behavior = 'error';
    await page.getByRole('button', { name: '只读计算', exact: true }).click();
    await page.getByRole('alert').waitFor();
    behavior = 'normal';
    await page.getByRole('button', { name: '只读计算', exact: true }).click();
    await page.getByTestId('research-analytics-result').waitFor();
    behavior = 'hold';
    const arrived = new Promise(done => { arrival = done; });
    await page.getByRole('button', { name: '只读计算', exact: true }).click();
    await arrived;
    await page.getByRole('button', { name: '清空输入与结果' }).click();
    const response = page.waitForResponse(r => r.url().endsWith('/api/research-analytics/simulation'));
    release(); release = null; await response;
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.equal(await page.getByTestId('research-analytics-result').count(), 0);
    assert.equal(await page.locator('#analytics-input').inputValue(), '');
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2));
    checks.push({ width, flows: ['all_modes', 'missingness', 'undefined_metrics', 'malformed_recovery', 'error_retry', 'cancel_stale_response', 'no_horizontal_overflow'] });
    await context.close();
  }
  assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, []); assert.deepEqual(audit.errors, []);
  status = 'PASS';
} finally {
  release?.();
  writeFileSync(join(output, 'result.json'), JSON.stringify({ status, checks, audit, evidence: 'SYNTHETIC_COMPONENT_RUNTIME_NOT_MARKET_VALIDATION' }, null, 2));
  await browser?.close();
  await new Promise(done => server.close(done));
}
