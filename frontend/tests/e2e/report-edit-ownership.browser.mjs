/** Full-app synthetic report metadata interruption acceptance. No backend or AI calls.
 * Run after npm run build, with E2E_REPORT_EDIT_OUTPUT_DIR set to an artifact directory.
 * The inherited unbounded list-refresh wait is deliberately not claimed as covered.
 */
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { preview } from 'vite';

const root = fileURLToPath(new URL('../..', import.meta.url));
assert.ok(process.env.E2E_REPORT_EDIT_OUTPUT_DIR, 'Set E2E_REPORT_EDIT_OUTPUT_DIR for acceptance artifacts');
const output = resolve(process.env.E2E_REPORT_EDIT_OUTPUT_DIR);
mkdirSync(output, { recursive: true });
const results = { suite: 'report-edit-ownership', transport: 'synthetic; no backend/model', cases: [], status: 'running' };
const record = () => writeFileSync(join(output, 'results.json'), JSON.stringify(results, null, 2));
record();
let server, browser;
try {
  assert.ok(existsSync(join(root, 'dist/index.html')), 'Run npm run build first');
  server = await preview({ root, configFile: false, preview: { host: '127.0.0.1', port: 0, strictPort: true } });
  const frontend = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: 'block' });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const patches = [], pending = new Set(), errors = [], blocked = [];
    let nextHold, currentCase = 'initial-readiness', readCount = 0;
    const reports = ['A', 'B'].map(id => ({ id, name: `${id}.pdf`, title: `Synthetic ${id}`, size: 100, ts: 1, sector_keys: [] }));
    page.on('pageerror', error => errors.push(error.message));
    const holdNextPatch = (failure = false) => {
      assert.equal(nextHold, undefined);
      let release, entered;
      const gate = new Promise(done => { release = done; });
      const started = new Promise(done => { entered = done; });
      const hold = { gate, started, release, entered, failure };
      nextHold = hold; pending.add(hold); return hold;
    };
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== frontend) { blocked.push(request.url()); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      if (url.pathname === '/api/myreports' && request.method() === 'GET') {
        readCount++; return route.fulfill({ json: { data: reports } });
      }
      if (/^\/api\/myreports\/[AB]$/.test(url.pathname) && request.method() === 'PATCH') {
        const id = url.pathname.split('/').at(-1), body = request.postDataJSON();
        patches.push({ id, body });
        const hold = nextHold; nextHold = undefined;
        if (!hold) { errors.push('Unexpected metadata PATCH without a hold'); return route.fulfill({ status: 500, json: { detail: 'UNEXPECTED_PATCH' } }); }
        hold.entered();
        let timer;
        try {
          await Promise.race([hold.gate, new Promise(done => { timer = setTimeout(() => { errors.push('Unreleased PATCH hold expired'); done(); }, 15000); })]);
          if (hold.failure) return await route.fulfill({ status: 400, json: { detail: 'SYNTHETIC_SAVE_FAILURE' } });
          Object.assign(reports.find(report => report.id === id), body);
          return await route.fulfill({ json: { data: reports.find(report => report.id === id) } });
        } finally { clearTimeout(timer); pending.delete(hold); }
      }
      // Full-app bootstrap reads remain synthetic too. Any mutation outside this
      // bounded contract is a test failure, never forwarded to a real service.
      if (request.method() !== 'GET') errors.push(`Unexpected mutation: ${request.method()} ${url.pathname}`);
      return route.fulfill({ json: { data: {} } });
    });
    const row = id => page.locator(`#report-${id}`);
    const save = id => row(id).getByRole('button', { name: '保存', exact: true });
    const cancel = id => row(id).getByRole('button', { name: '取消', exact: true });
    const title = id => row(id).getByLabel('标题', { exact: true });
    const edit = async id => { await row(id).getByTitle('编辑', { exact: true }).click(); await title(id).waitFor(); };
    const entered = async hold => {
      let timer;
      try {
        await Promise.race([hold.started, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error('Expected metadata PATCH did not start')), 10000);
        })]);
      } finally { clearTimeout(timer); }
    };
    const finish = async hold => {
      const response = page.waitForResponse(response => response.request().method() === 'PATCH' && /\/api\/myreports\/[AB]$/.test(new URL(response.url()).pathname));
      hold.release(); await (await response).finished();
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    };
    const screenshot = async name => {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'No page-level horizontal overflow');
      await page.screenshot({ path: join(output, `${width}-${name}.png`), fullPage: true });
      results.cases.push({ width, name, status: 'passed', patches: patches.length, reads: readCount }); record();
    };
    try {
      await page.goto(`${frontend}/my-reports`, { waitUntil: 'domcontentloaded' });
      await row('A').getByText('Synthetic A', { exact: true }).waitFor();
      await row('B').getByText('Synthetic B', { exact: true }).waitFor();
      assert.equal(readCount, 1);
      for (const target of ['A', 'B']) {
        currentCase = target === 'A' ? 'cancel-reopen-stale-success' : 'switch-report-stale-success';
        await edit('A'); await title('A').fill(`Persisted A for ${target}`);
        const hold = holdNextPatch(); await save('A').click(); await entered(hold);
        await cancel('A').click(); await edit(target); await title(target).fill(`UNSAVED ${target}`);
        assert.equal(await row(target).getByRole('button', { name: '保存中…', exact: true }).isDisabled(), true);
        const before = readCount; await finish(hold); await save(target).waitFor();
        assert.equal(await title(target).inputValue(), `UNSAVED ${target}`);
        assert.equal(await cancel(target).isVisible(), true);
        assert.ok(readCount > before, 'Persisted mutation refreshes archive');
        assert.equal(reports[0].title, `Persisted A for ${target}`);
        await screenshot(currentCase); await cancel(target).click();
      }
      currentCase = 'stale-failure-and-new-editor-retry';
      await edit('A'); const failed = holdNextPatch(true); await save('A').click(); await entered(failed);
      await edit('B'); await title('B').fill('NEW B DRAFT'); await finish(failed); await save('B').waitFor();
      assert.equal(await title('B').inputValue(), 'NEW B DRAFT');
      assert.doesNotMatch(await row('B').innerText(), /SYNTHETIC_SAVE_FAILURE/);
      await page.getByText(/研报「.*」保存失败：SYNTHETIC_SAVE_FAILURE/).waitFor();
      await screenshot('stale-error-preserves-new-editor');
      const retry = holdNextPatch(); await save('B').click(); await entered(retry);
      assert.equal(patches.at(-1).id, 'B'); assert.equal(patches.at(-1).body.title, 'NEW B DRAFT');
      await finish(retry); await cancel('B').waitFor({ state: 'hidden' });
      await row('B').getByText('NEW B DRAFT', { exact: true }).waitFor(); await screenshot(currentCase);

      currentCase = 'same-turn-repeated-save-and-retry';
      await edit('A'); const before = patches.length, repeated = holdNextPatch(true);
      // Dispatch two real DOM clicks in one task, before React's disabled state
      // can be relied upon. The component's synchronous lock must own the write.
      await save('A').evaluate(button => { button.click(); button.click(); }); await entered(repeated);
      assert.equal(await row('A').getByRole('button', { name: '保存中…', exact: true }).isDisabled(), true);
      await finish(repeated); await save('A').waitFor();
      assert.equal(patches.length, before + 1); assert.match(await row('A').innerText(), /SYNTHETIC_SAVE_FAILURE/);
      const recovered = holdNextPatch(); await save('A').click(); await entered(recovered); await finish(recovered);
      await cancel('A').waitFor({ state: 'hidden' }); assert.equal(patches.length, before + 2);
      await screenshot(currentCase);
      assert.deepEqual(errors, []); assert.deepEqual(blocked, []);
      await context.tracing.stop({ path: join(output, `${width}-trace.zip`) });
    } catch (error) {
      results.cases.push({ width, name: currentCase, status: 'failed', error: String(error), patches, errors, blocked }); record();
      await page.screenshot({ path: join(output, `${width}-FAILURE.png`), fullPage: true }).catch(() => {});
      writeFileSync(join(output, `${width}-FAILURE.html`), await page.content().catch(() => 'Page unavailable'));
      await context.tracing.stop({ path: join(output, `${width}-FAILURE-trace.zip`) }).catch(() => {});
      throw error;
    } finally {
      for (const hold of pending) hold.release();
      await context.close();
    }
  }
  results.status = 'passed'; record(); console.log('report edit ownership desktop/mobile: PASS');
} catch (error) {
  results.status = 'failed'; results.error = String(error); record(); throw error;
} finally {
  if (browser) await browser.close();
  if (server) await new Promise(done => server.httpServer.close(done));
}
