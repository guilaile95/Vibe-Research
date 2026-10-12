// CI-only browser execution: actual production Intel page, strict raw→FactLake→API golden.
import { captureBrowserFailure } from './browser-failure-evidence.mjs';
import { publicResearchPaths, publicResearchStaticAllowed, publicResearchSource, PUBLIC_RESEARCH_CLOCK } from './public-research.fixture.mjs';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFileSync, createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright';
const frontend = fileURLToPath(new URL('../../', import.meta.url));
const { output, dist } = publicResearchPaths(frontend, process.env.PUBLIC_RESEARCH_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), 'public-research-dom-')));
mkdirSync(output, { recursive: true });
const golden = JSON.parse(readFileSync(new URL('../fixtures/public-research.golden.json', import.meta.url)));
process.chdir(frontend);
try { await build({ configFile: false, mode: 'production', root: join(frontend, 'tests/e2e/public-research-adapter'),
  plugins: [react()], resolve: { alias: { '@': join(frontend, 'src') } }, css: { postcss: frontend }, build: { outDir: dist, emptyOutDir: true } });
  assert.ok(existsSync(join(dist, 'index.html')), 'Vite output must exist at the exact static-server path');
} catch (error) {
  writeFileSync(join(output, 'result.json'), JSON.stringify({ status: 'FAIL', phase: 'build', error: String(error), output, dist }, null, 2));
  throw error;
}
if (process.argv.includes('--build-only')) { console.log('Actual Intel page built; browser NOT_RUN'); process.exit(0); }
if (!process.env.CI) throw new Error('Browser execution is CI-only; no local browser authorization');
const audit = { external: [], unexpected: [], errors: [], reads: [] };
let origin, browser, activePage, activeWidth, phase = 'startup';const releases = [];

const server = createServer((req, res) => {
  const url = new URL(req.url, origin);
  if (req.headers.host !== new URL(origin).host || !publicResearchStaticAllowed(req.method, url.pathname, url.search)) { audit.unexpected.push(req.url); res.writeHead(403).end(); return; }
  if (url.pathname === '/favicon.ico') { res.writeHead(204).end(); return; }
  const target = url.pathname === '/' ? join(dist, 'index.html') : resolve(dist, '.' + url.pathname);
  if (!target.startsWith(resolve(dist) + sep) || !existsSync(target)) { audit.unexpected.push(`missing static ${url.pathname}`); res.writeHead(404).end(); return; }
  res.setHeader('Content-Type', { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' }[extname(target)] || 'text/plain');
  createReadStream(target).pipe(res);
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
origin = `http://127.0.0.1:${server.address().port}`;
const cases = [];
try {
  browser = await chromium.launch({ headless: true });
  for (const width of [1440, 390]) {
    activeWidth = width; phase = 'initial event archive';
    const context = await browser.newContext({ viewport: { width, height: 960 }, serviceWorkers: 'block' });
    let mode = 'normal', held, release;
    await context.routeWebSocket('**/*', socket => { audit.external.push(socket.url()); socket.close(); });
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== origin) { audit.external.push(url.href); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) {
        if (!publicResearchStaticAllowed(req.method(), url.pathname, url.search)) { audit.unexpected.push(req.url()); return route.abort(); }
        return route.continue();
      }
      const source = publicResearchSource(req.method(), url.pathname, url.search);
      audit.reads.push({ method: req.method(), path: url.pathname, search: url.search, source, mode });
      if (!source || !golden[source]) {
        audit.unexpected.push(`${req.method()} ${url.href}`); return route.fulfill({ status: 500, json: { detail: 'unexpected fixture request' } });
      }
      const selected = mode;
      if (selected === 'hold') { held?.(); await new Promise(done => { release = done; releases.push(done); }); }
      const data = structuredClone(golden[source]);
      if (selected === 'wrong') data.source_id = 'private';
      if (selected === 'malformed') data.blocks[0].rows[0].listings = [null];
      if (selected === 'failure') return route.fulfill({ status: 503, json: { detail: 'synthetic' } });
      if (selected === 'missing') { data.blocks = []; data.missing_subjects = golden[source].blocks.map(b => b.subject); data.status = 'missing'; data.message = '合成缺失归档'; }
      return route.fulfill({ json: { data } });
    });
    const page = await context.newPage(); activePage = page; page.setDefaultTimeout(10000);
    page.on('pageerror', e => audit.errors.push(e.message));
    await page.clock.setFixedTime(new Date(PUBLIC_RESEARCH_CLOCK));
    await page.goto(origin + '/?tab=events');
    const events = page.getByRole('region', { name: '事件定价归档' });
    await events.getByText('合成案例：仅离线软件验证，非真实市场数据', { exact: true }).waitFor();
    await events.getByText('synthetic-no-token', { exact: true }).waitFor();
    await events.getByText('synthetic-yes-token', { exact: true }).waitFor();
    assert.match(await events.innerText(), /不是客观概率/);
    await events.getByRole('button', { name: 'Kalshi 事件定价', exact: true }).click();
    await events.getByText('yes_bid_ask_midpoint_dollars', { exact: true }).waitFor();
    assert.match(await events.innerText(), /0\.42 USD/);
    phase = 'industry archive';
    await page.getByRole('button', { name: '产业公开数据', exact: true }).click();
    const industry = page.getByRole('region', { name: '产业公开数据归档' });
    await industry.getByText('2026-08', { exact: true }).first().waitFor();
    assert.match(await industry.innerText(), /未核实合并\/修订口径/);
    await industry.getByRole('button', { name: 'DRAM / NAND 现货', exact: true }).click();
    await industry.getByText('Synthetic DDR4 8Gb 1Gx8 3200', { exact: true }).waitFor();
    assert.match(await industry.innerText(), /不是 HBM 价格/);
    await industry.getByRole('button', { name: '大宗连续期货', exact: true }).click();
    await industry.getByText('continuous_series_daily_close', { exact: true }).first().waitFor();
    assert.match(await industry.innerText(), /换月及调整规则未披露/);
    await industry.getByRole('button', { name: '公开招聘信号', exact: true }).click();
    await industry.getByText('greenhouse:lightmatter', { exact: true }).first().waitFor();
    assert.match(await industry.innerText(), /岗位数是招聘意图，不是产能/);
    await industry.locator('details').filter({ hasText: '查看岗位标识与日期' }).first().locator('summary').click();
    await industry.getByText(/synthetic-job-1 · Synthetic hardware engineer/).first().waitFor();
    const retry = industry.getByRole('button', { name: '重读归档', exact: true });
    for (const bad of ['wrong', 'malformed', 'failure']) {
      phase = `invalid ${bad} retry`; mode = bad; await retry.click(); await industry.getByRole('alert').waitFor();
      assert.equal(await industry.locator('article').count(), 0);
      mode = 'normal'; await retry.click(); await industry.locator('article').first().waitFor();
      cases.push({ width, case: bad + '-retry' });
    }
    phase = 'missing archive recovery'; mode = 'missing'; await retry.click(); await industry.getByText(/合成缺失归档/).waitFor();
    assert.equal(await industry.locator('article').count(), 0);
    mode = 'normal'; await retry.click(); await industry.locator('article').first().waitFor();
    phase = 'held source switch'; mode = 'hold'; const started = new Promise(done => { held = done; }); await retry.click(); await started;
    mode = 'normal'; await industry.getByRole('button', { name: '台湾月营收', exact: true }).click();
    await industry.getByText('2026-08', { exact: true }).first().waitFor(); release();
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.doesNotMatch(await industry.innerText(), /synthetic-job-1/);
    phase = 'back forward reload'; await page.goBack(); await events.getByText('synthetic-yes-token', { exact: true }).waitFor();
    await page.goForward(); await industry.getByText('2026-08', { exact: true }).first().waitFor();
    await page.reload(); await industry.getByText('2026-08', { exact: true }).first().waitFor();
    const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert.ok(dimensions.document <= dimensions.width + 1);
    await page.screenshot({ path: join(output, `${width}-public-research.png`), fullPage: true });
    cases.push({ width, case: 'actual-Intel-page-six-providers-identity-units-caveats-missing-race-history-reload-layout' });
    await context.close(); activePage = undefined;
  }
  assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, []); assert.deepEqual(audit.errors, []);
} catch (error) {
  process.exitCode = 1;
  audit.errors.push(String(error));
  await captureBrowserFailure({ page: activePage, output, prefix: String(activeWidth || 'startup'), selector: 'section[aria-label="事件定价归档"], section[aria-label="产业公开数据归档"]', error, audit: { phase, ...audit } });
  console.error(error);
} finally {
  writeFileSync(join(output, 'result.json'), JSON.stringify({ status: process.exitCode ? 'FAIL' : 'PASS', phase, cases, audit }, null, 2));
  for (const release of releases) release();
  await browser?.close(); await new Promise(done => server.close(done));
}
