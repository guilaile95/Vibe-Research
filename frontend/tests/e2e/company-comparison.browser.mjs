/** CI-only acceptance of the real built StockData and Debate pages, never a component adapter. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { captureBrowserFailure } from './browser-failure-evidence.mjs';
import { observedBrowserAction } from './observed-browser-action.mjs';
import { createComparisonFixture, comparisonGoldens, comparisonHistoryGolden, comparisonLlm, comparisonCutoff, generationPath, CLOCK } from './company-comparison.fixture.mjs';

if (process.env.CI !== 'true') throw Error('Comparison browser acceptance is CI-only; local browser execution is not authorized');
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const dist = path.join(frontend, 'dist');
const output = process.env.COMPANY_COMPARISON_BROWSER_OUTPUT_DIR;
assert.ok(output, 'COMPANY_COMPARISON_BROWSER_OUTPUT_DIR is required');
mkdirSync(output, { recursive: true });
let origin, browser, page, width, phase = 'startup';
const runs = [], errors = [], violations = [], captures = [], dialogs = [];
const server = createServer((req, res) => {
  const u = new URL(req.url, origin);
  if (req.method !== 'GET' || req.headers.host !== new URL(origin).host || u.pathname.startsWith('/api/')) {
    violations.push(`escaped interception ${req.method} ${u.pathname}${u.search}`); res.writeHead(403).end(); return;
  }
  const file = path.resolve(dist, ['/stock-data', '/debate'].includes(u.pathname) ? 'index.html' : u.pathname.slice(1));
  if (!file.startsWith(dist + path.sep) || !existsSync(file)) { res.writeHead(404).end(); return; }
  let bytes = readFileSync(file);
  const ext = path.extname(file);
  if (ext === '.html') bytes = Buffer.from(bytes.toString().replace(/<link\b(?=[^>]*\brel=["'](?:preconnect|dns-prefetch)["'])[^>]*>/gi, '').replace(/<link\b(?=[^>]*\bhref=["']https?:\/\/)[^>]*>/gi, ''));
  res.setHeader('content-type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' })[ext] || 'application/octet-stream');
  res.end(bytes);
});

// Buffer an actual intercepted API response, then hold only its delivery to the app.
// Deliberately delivering after AbortSignal cancellation tests production owner guards,
// rather than relying on the browser network abort to hide a stale-completion bug.
function deliveryObserver() {
  const fetchOriginal = window.fetch.bind(window);
  window.__comparisonHoldNext = [];
  window.__comparisonHeld = [];
  window.fetch = async (input, init) => {
    const u = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.origin);
    const key = u.pathname + u.search;
    const at = u.origin === location.origin ? window.__comparisonHoldNext.indexOf(key) : -1;
    if (at < 0) return fetchOriginal(input, init);
    window.__comparisonHoldNext.splice(at, 1);
    const response = await fetchOriginal(input, init), bytes = await response.arrayBuffer();
    const state = { key, returned: false, consumed: false };
    await new Promise(resolve => window.__comparisonHeld.push({ state, resolve }));
    const replay = new Response(bytes, { status: response.status, headers: response.headers });
    const json = replay.json.bind(replay);
    replay.json = async () => { try { return await json(); } finally { state.consumed = true; } };
    const readerOriginal = replay.body.getReader.bind(replay.body);
    replay.body.getReader = (...args) => {
      const reader = readerOriginal(...args), read = reader.read.bind(reader), cancel = reader.cancel.bind(reader);
      reader.read = async (...values) => { const result = await read(...values); if (result.done) state.consumed = true; return result; };
      reader.cancel = async (...values) => { try { return await cancel(...values); } finally { state.consumed = true; } };
      return reader;
    };
    state.returned = true;
    return replay;
  };
}

try {
  assert.ok(existsSync(path.join(dist, 'index.html')), 'Build the real frontend before browser acceptance');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ['--disable-background-networking', '--dns-prefetch-disable'] });
  for (width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 }, serviceWorkers: 'block' });
    const fixture = createComparisonFixture(origin); runs.push({ width, fixture });
    await context.routeWebSocket('**/*', socket => { violations.push('websocket'); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(); let body;
      if (request.postData() !== null) { try { body = request.postDataJSON(); } catch { body = request.postData(); } }
      const reply = fixture.handle(request.url(), request.method(), body);
      if (reply.kind === 'deny') return route.abort();
      if (reply.kind === 'static') return route.continue();
      return reply.kind === 'stream' ? route.fulfill({ contentType: 'application/x-ndjson', body: reply.body }) : route.fulfill({ status: reply.status || 200, json: reply.body });
    });
    await context.addInitScript(llm => { localStorage.clear(); localStorage.setItem('vr-llm', JSON.stringify(llm)); }, comparisonLlm);
    await context.addInitScript(deliveryObserver);
    page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
    await page.clock.setFixedTime(new Date(CLOCK));
    const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const card = () => page.getByTestId('company-comparison');
    const generate = () => card().getByRole('button', { name: '确认一次调用预算并开始对比', exact: true });
    const read = () => card().getByRole('button', { name: '读取两股已有资料（不调用模型）', exact: true });
    const currentResult = () => card().locator(':scope > [data-testid="company-comparison-result"]');
    const modelPosts = () => fixture.calls.filter(call => call.method === 'POST');
    const comparisonCalls = () => fixture.calls.filter(call => call.path.startsWith('/api/company-comparison/') || call.path.startsWith('/api/company-research/'));
    const query = () => page.getByPlaceholder('A 股 6 位代码，或美股/港股/韩股（AAPL / 00700 / 005930.KS）');
    const shot = async (target, name) => {
      await target.evaluate(element => element.scrollIntoView({ block: 'start', behavior: 'instant' })); await settle();
      const bounds = await target.boundingBox(); assert.ok(bounds);
      assert.ok(bounds.x >= -1 && bounds.x + bounds.width <= width + 1, 'comparison target must fit horizontally, including its offset');
      const text = await target.innerText();
      writeFileSync(path.join(output, `${width}-${name}.html`), await target.evaluate(element => element.outerHTML));
      await page.screenshot({ path: path.join(output, `${width}-${name}.png`), fullPage: false });
      // Tall cards may extend below a scrollport. Capture their visible intersection,
      // not a whole-card screenshot that asks Playwright to scroll hidden content.
      const clip = await target.evaluate(element => {
        const b = element.getBoundingClientRect();
        const main = element.closest('main')?.getBoundingClientRect() || { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
        const x = Math.max(0, b.left, main.left), y = Math.max(0, b.top, main.top);
        return { x, y, width: Math.min(innerWidth, b.right, main.right) - x, height: Math.min(innerHeight, b.bottom, main.bottom) - y };
      });
      assert.ok(clip.width > 0 && clip.height > 0, 'comparison target must have a visible screenshot crop');
      await page.screenshot({ path: path.join(output, `${width}-${name}-card.png`), clip });
      captures.push({ width, name, text });
    };
    const openCard = async identity => {
      await card().getByText(`两股归档研究对比 · ${identity}`, { exact: true }).waitFor();
      if (!await card().evaluate(element => element.open)) await card().locator(':scope > summary').click();
    };
    const configurePair = async () => {
      await card().getByLabel('对比市场', { exact: true }).selectOption('HK');
      await card().getByLabel('对比代码', { exact: true }).fill('00700');
      await card().getByLabel('对比归档截止日', { exact: true }).fill(comparisonCutoff);
    };
    const chooseBundles = async (scenario = 'complete') => {
      fixture.expectBundles(scenario); await read().click();
      const g = comparisonGoldens[scenario];
      await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="company-comparison"] button')].some(button => button.textContent === '读取两股已有资料（不调用模型）' && !button.disabled));
      await card().getByLabel('对比资料1', { exact: true }).waitFor();
      assert.equal(await generate().isDisabled(), true, 'a list is not selection authorization');
      await card().getByLabel('对比资料1', { exact: true }).selectOption(g.bundles[0].bundle_id);
      assert.equal(await generate().isDisabled(), true, 'both frozen bundles must be explicitly selected');
      await card().getByLabel('对比资料2', { exact: true }).selectOption(g.bundles[1].bundle_id);
      assert.equal(await generate().isDisabled(), false);
    };
    const confirmClick = accept => observedBrowserAction(async () => {
      const dialog = await page.waitForEvent('dialog');
      const text = dialog.message(); dialogs.push({ width, accept, text });
      try {
        assert.match(text, /US:AAPL.*HK:00700/); assert.match(text, /https:\/\/fixture\.example/);
        assert.ok(text.includes(comparisonCutoff)); assert.ok(text.includes(comparisonLlm.model));
        assert.match(text, /最多1次模型调用、90秒、2500输出token/); assert.match(text, /无自动重试/);
        assert.ok(!text.includes(comparisonLlm.apiKey), 'confirmation must not expose the synthetic credential field');
      } catch (error) { await dialog.dismiss().catch(() => {}); throw error; }
      await (accept ? dialog.accept() : dialog.dismiss());
    }, () => generate().click());
    const begin = async (scenario = 'complete', delivery = 'complete') => {
      fixture.expectGeneration(scenario, delivery); await confirmClick(true);
    };
    const completed = async (scenario = 'complete') => {
      const g = comparisonGoldens[scenario], result = currentResult();
      await result.getByText(`${g.record.as_of} · COMPLETED · ${g.record.run_id} · 配对哈希 ${g.record.pair_sha256}`, { exact: true }).waitFor();
      const text = await result.innerText();
      assert.match(text, /事实和数字未核验/); assert.match(text, /可比性尚未建立/); assert.match(text, /未进行结构化排名/);
      assert.match(text, /合成案例（非真实市场验收）/); assert.equal(await result.locator('section').count(), 2);
      for (const [i, subject] of g.record.subjects.entries()) {
        assert.ok(text.includes(`${subject.market}:${subject.symbol}`)); assert.ok(text.includes(subject.expected_bundle_sha256));
        for (const source of g.record.evidence[i].sources) {
          assert.ok(text.includes(`${subject.market}:${subject.symbol}/${source.evidence_id}`)); assert.ok(text.includes(source.payload_sha256));
        }
        for (const missing of g.record.output.subjects[i].missingness) assert.ok(text.includes(missing));
      }
      assert.deepEqual(fixture.expected, []);
    };
    const hold = async () => page.evaluate(key => window.__comparisonHoldNext.push(key), generationPath);
    const held = () => page.waitForFunction(key => window.__comparisonHeld.some(item => item.state.key === key && !item.state.returned), generationPath);
    const release = async () => {
      await page.evaluate(key => { const item = window.__comparisonHeld.find(item => item.state.key === key && !item.state.returned); if (!item) throw Error('Missing held response'); item.resolve(); }, generationPath);
      await page.waitForFunction(key => window.__comparisonHeld.filter(item => item.state.key === key).every(item => item.state.returned && item.state.consumed), generationPath); await settle();
    };

    phase = `${width} selected identity, manual inputs, no automatic reads`;
    await page.goto(origin + '/stock-data?code=AAPL', { waitUntil: 'domcontentloaded' }); await openCard('US:AAPL');
    assert.equal(await page.getByTestId('company-research').count(), 1, 'comparison is next to the real research panel');
    assert.match(await page.getByTestId('company-research').locator(':scope > summary').innerText(), /US:AAPL/);
    assert.equal(comparisonCalls().length, 0); assert.equal(modelPosts().length, 0);
    assert.equal(await card().getByLabel('对比归档截止日', { exact: true }).inputValue(), '');
    await card().getByLabel('对比市场', { exact: true }).selectOption('US'); await card().getByLabel('对比代码', { exact: true }).fill('AAPL');
    await card().getByLabel('对比归档截止日', { exact: true }).fill(comparisonCutoff); assert.equal(await read().isDisabled(), true, 'same company rejected');
    await configurePair(); assert.equal(comparisonCalls().length, 0);
    fixture.expectEmptyBundles(); await read().click();
    await card().getByText('该身份和截止日没有可用的已冻结资料，不能生成对比', { exact: true }).first().waitFor();
    assert.equal(await card().getByText('该身份和截止日没有可用的已冻结资料，不能生成对比', { exact: true }).count(), 2);
    assert.equal(await generate().isDisabled(), true); assert.equal(modelPosts().length, 0); assert.deepEqual(fixture.expected, []);
    await shot(card(), 'empty-existing-archives-no-generation');
    await chooseBundles();
    assert.equal(modelPosts().length, 0); await shot(card(), 'manual-existing-bundles-same-cutoff');
    phase = `${width} decline then explicit bounded consent`;
    const beforeDecline = comparisonCalls().length; await confirmClick(false); await settle();
    assert.equal(comparisonCalls().length, beforeDecline, 'declined consent does not even read frozen bodies');
    await begin(); await completed(); assert.equal(modelPosts().length, 1); await shot(currentResult(), 'completed-unverified-synthetic');

    phase = `${width} explicit history and context reset`;
    const beforeHistory = comparisonCalls().length;
    await card().locator(':scope > summary').click(); await card().locator(':scope > summary').click(); await settle();
    assert.equal(comparisonCalls().length, beforeHistory, 'reopening never fetches or generates');
    fixture.expectHistory(); await card().getByRole('button', { name: '读取该配对历史', exact: true }).click();
    const history = card().locator(':scope > details'); await history.first().locator(':scope > summary').waitFor();
    await history.first().locator(':scope > summary').click(); await shot(history.first(), 'manual-history-provenance');
    assert.equal(modelPosts().length, 1);
    await card().getByLabel('对比归档截止日', { exact: true }).fill('2026-09-29'); await settle();
    assert.equal(await card().getByTestId('company-comparison-result').count(), 0); assert.equal(await card().getByLabel('对比资料1', { exact: true }).count(), 0);
    await card().getByLabel('对比归档截止日', { exact: true }).fill(comparisonCutoff);

    phase = `${width} failed raw quote survives as missingness`;
    await chooseBundles('missing'); await begin('missing'); await completed('missing');
    const failedSource = comparisonGoldens.missing.record.evidence[0].sources.find(source => source.evidence_id === 'global_quote_ref');
    assert.equal(failedSource.status, 'ERROR'); assert.match(await currentResult().innerText(), /global_quote_ref.*ERROR/);
    await shot(currentResult(), 'failed-source-missingness');

    phase = `${width} truncated stream is not a completed report`;
    await begin('missing', 'truncated'); await card().getByRole('alert').getByText('对比响应中断，未收到完整报告', { exact: true }).waitFor();
    assert.equal(await currentResult().count(), 0); assert.equal(await generate().isDisabled(), false); await shot(card(), 'truncated-stream-no-report');

    phase = `${width} cancellation rejects late complete delivery; history remains explicit`;
    await chooseBundles(); await hold(); await begin(); await held();
    await card().getByRole('button', { name: '取消对比', exact: true }).click();
    await card().getByRole('alert').getByText('已取消；未完成报告不保存为完成，已产生的模型费用可能无法撤销', { exact: true }).waitFor();
    await release(); assert.equal(await currentResult().count(), 0); assert.equal(await generate().isDisabled(), false);
    await shot(card(), 'cancelled-late-delivery-ignored');
    for (const state of ['running', 'cancelled', 'failed']) {
      fixture.expectHistoryState(state); await card().getByRole('button', { name: '读取该配对历史', exact: true }).click();
      const records = comparisonHistoryGolden[state + '_history'].data;
      const labels = records.map(record => `${record.started_at} · ${record.status === 'RUNNING' ? '未结束记录（不代表仍在运行）' : record.status}`);
      await page.waitForFunction(labels => JSON.stringify([...document.querySelectorAll('[data-testid="company-comparison"] > details > summary')].map(element => element.textContent)) === JSON.stringify(labels), labels);
      assert.equal(await currentResult().count(), 0, 'manual persisted history does not resurrect current result');
      const rows = card().locator(':scope > details');
      for (let i = 0; i < records.length; i++) {
        if (!await rows.nth(i).evaluate(element => element.open)) await rows.nth(i).locator(':scope > summary').click();
        assert.ok((await rows.nth(i).innerText()).includes(records[i].status));
        assert.equal(await rows.nth(i).getByText('引用：', { exact: false }).count(), 0, 'incomplete history has no model output');
      }
      await shot(card(), 'manual-' + state + '-history');
    }

    phase = `${width} actual failed generation receipt remains retryable without partial result`;
    await begin('complete', 'failed');
    await card().getByRole('alert').getByText('对比未完成；没有可用的完整报告，请检查资料后手动重试', { exact: true }).waitFor();
    assert.equal(await currentResult().count(), 0); assert.equal(await generate().isDisabled(), false);
    await shot(card(), 'failed-generation-no-current-report');

    phase = `${width} late selected-company response cannot own new company`;
    await hold(); await begin(); await held(); await query().fill('00700'); await query().press('Enter'); await openCard('HK:00700');
    assert.equal(await card().getByLabel('对比归档截止日', { exact: true }).inputValue(), '');
    await release(); assert.equal(await card().getByTestId('company-comparison-result').count(), 0);
    assert.doesNotMatch(await card().innerText(), /US:AAPL/); await shot(card(), 'selected-HK-ignores-late-US');
    const beforeBack = comparisonCalls().length; await page.goBack(); await openCard('US:AAPL');
    assert.equal(await card().getByLabel('对比归档截止日', { exact: true }).inputValue(), ''); assert.equal(comparisonCalls().length, beforeBack);

    phase = `${width} selected A-share to Debate carries only identity and never starts model`;
    await query().fill('600000'); await query().press('Enter'); await openCard('A:600000');
    const link = page.getByTestId('stock-context-link-debate'); assert.equal(await link.getAttribute('href'), '/debate?code=600000');
    const beforeDebate = modelPosts().length; await link.click();
    await page.getByRole('heading', { name: '多空辩论', exact: true }).waitFor();
    assert.equal(await page.getByPlaceholder('6 位代码，如 600519').inputValue(), '600000');
    assert.equal(await page.getByRole('button', { name: '开始辩论', exact: true }).isEnabled(), true); await settle();
    assert.equal(modelPosts().length, beforeDebate); assert.equal(fixture.calls.some(call => call.path === '/api/debate'), false);
    await shot(page.locator('main'), 'selected-stock-debate-no-auto-model');
    await page.goBack(); await openCard('A:600000'); assert.equal(modelPosts().length, beforeDebate);

    phase = `${width} strict final request audit`;
    assert.equal(modelPosts().length, 6, 'exactly six explicitly confirmed synthetic comparison attempts');
    assert.deepEqual(fixture.expected, []); assert.deepEqual(fixture.violations, []);
    assert.deepEqual(fixture.base.violations, []); assert.deepEqual(fixture.base.base.violations, []); assert.deepEqual(fixture.base.base.writes, []);
    assert.equal(await page.evaluate(() => Object.keys(localStorage).some(key => /note|report|history/i.test(key))), false, 'no implicit saved research note');
    await context.close(); page = null;
  }
  assert.deepEqual(errors, []); assert.deepEqual(violations, []);
} catch (error) {
  errors.push(String(error)); process.exitCode = 1;
  await captureBrowserFailure({ page, output, prefix: String(width || 'startup'), selector: '[data-testid="company-comparison"]', error,
    audit: { phase, violations, errors, runs: runs.map(({ width, fixture }) => ({ width, requests: fixture.calls, violations: fixture.violations, pending: fixture.expected })) } });
  console.error(error);
} finally {
  writeFileSync(path.join(output, 'results.json'), JSON.stringify({ passed: !process.exitCode, scope: 'Real built StockData/selected-stock Debate, actual registered API synthetic goldens; no live provider/model; CI-only browser', phase, captures, dialogs, errors, violations,
    runs: runs.map(({ width, fixture }) => ({ width, requests: fixture.calls, violations: fixture.violations, pending: fixture.expected, baseViolations: fixture.base.violations, startupViolations: fixture.base.base.violations })) }, null, 2));
  await browser?.close(); if (server.listening) await new Promise(resolve => server.close(resolve));
}
