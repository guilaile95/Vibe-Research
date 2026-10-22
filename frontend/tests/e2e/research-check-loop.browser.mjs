// Production-built UI and real disposable IndexedDB. Every API result is a
// synthetic transcription/fixture, not natural usage, original PDF or PIT evidence.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { readReply } from './ai-settings-storage.fixture.mjs';
import { navigationEvidencePage } from './research-navigation.fixture.mjs';
const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
const output = process.env.RESEARCH_CHECK_LOOP_OUTPUT_DIR || mkdtempSync(join(tmpdir(), 'research-check-loop-'));
mkdirSync(output, { recursive: true });
const server = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname.startsWith('/api/')) return res.writeHead(503).end();
  let target = resolve(dist, '.' + decodeURIComponent(pathname));
  if (!target.startsWith(resolve(dist) + sep) || !existsSync(target) || !extname(target)) target = join(dist, 'index.html');
  res.setHeader('Content-Type', { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }[extname(target)] || 'application/octet-stream');
  createReadStream(target).pipe(res);
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const baseURL = `http://127.0.0.1:${server.address().port}`;
const report = (id, title, hash) => ({ id, title, name: `${id}.pdf`, size: 123, ext: '.pdf', ts: 1, industry: 'synthetic', source_url: `https://example.com/${id}.pdf`, publish_date: '2025-01-24', file_sha256: hash.repeat(64), page_count: 2, text_index_status: 'SEARCHABLE' });
const originalReport = report('synthetic-original', '原预告（合成文本）', 'a');
const revisedReport = report('synthetic-revised', '修订预告（合成文本）', 'b');
const originalText = '合成证券600519，2024年全年，合并报表，归属于上市公司股东的净利润，单位：万元；预计盈利648.13至753.93万元。这是测试转录，不是实际原PDF。';
const revisedText = '合成证券600519，2024年全年，合并报表，归属于上市公司股东的净利润，单位：万元；预计亏损594.25至891.37万元。修订预告不是实际业绩。测试转录，不是实际原PDF。';
const discoveryItem = {
  security_code: '600519', name: '合成公司', strategy: 'SWING', sector: '合成行业', themes: [], discovery_state: 'QUEUED', condition_match: 'FULL_CONDITIONS', research_priority: 'MEDIUM',
  reason_codes: ['SYNTHETIC_RETURN_20D'], supporting_observations: [{ code: 'RETURN_20D', label: '20日收益（合成）', value: 0.12, source_ref: 'synthetic:history-source' }],
  uncertainties: ['FUNDAMENTAL_FRESHNESS_UNKNOWN'], data_health: 'partial', catalyst_status: 'PARTIAL', fundamental_status: 'PARTIAL', evidence_gate: 'PARTIAL',
  restricted_universe: { status: 'UNKNOWN', reason_codes: [], listing_age_status: 'UNKNOWN' }, discovered_at: '2026-10-22T02:00:00Z', as_of: '2026-10-21', provenance_refs: ['synthetic:market-source', 'synthetic:announcement-directory'],
};
const discoverySnapshot = {
  schema_version: 'full-market-discovery.v0.1', status: 'partial', as_of: '2026-10-21', fetched_at: '2026-10-22T02:01:00Z', last_successful_at: null, refresh_attempted_at: null,
  market_context: { status: 'partial', core_universe_count: 100, sector_count: 1 }, funnel: { core_universe: 100, cheap_scan_passed: 30, qualification_candidates: 24, queue_items: { SHORT: 0, SWING: 1, MEDIUM: 0 }, excluded: 0 },
  datasets: [], queues: { SHORT: [], SWING: [discoveryItem], MEDIUM: [] }, excluded: [], limitations: ['合成目录；公告窗口未证明查全，不包含原文'], cache: { hit: false, age_seconds: null },
};
const results = []; let browser;
const readDatabase = page => page.evaluate(() => new Promise((resolve, reject) => {
  const request = indexedDB.open('vr-research-workflow');
  request.onerror = () => reject(request.error?.message);
  request.onsuccess = () => { const db = request.result, tx = db.transaction(['questions', 'rounds'], 'readonly'), questions = tx.objectStore('questions').getAll(), rounds = tx.objectStore('rounds').getAll(); tx.oncomplete = () => { resolve({ questions: questions.result, rounds: rounds.result }); db.close(); }; tx.onerror = () => reject(tx.error?.message); };
}));
async function openQuestion(page, questionId) {
  await page.goto('/candidates/600519#candidate-research-check');
  const panel = page.getByTestId('research-check-panel');
  await panel.getByLabel('这只股票的研究问题', { exact: true }).selectOption(questionId);
  await panel.getByTestId('check-question-context').waitFor();
  return panel;
}
async function writeRound(panel, judgement, limits = '仅有局部测试材料，未核验全文、现金流或因果。', next = '需要同口径年报与现金流原页。') {
  await panel.getByLabel('本轮判断', { exact: true }).fill(judgement);
  await panel.getByLabel('本轮限制与反证', { exact: true }).fill(limits);
  await panel.getByLabel('下一项材料', { exact: true }).fill(next);
}
async function operand(panel, label, materialTitle, quote, low, high) {
  await panel.getByLabel(`${label}来源`, { exact: true }).selectOption({ label: `${materialTitle} · 第 1 页` });
  await panel.getByLabel(`${label}原文引句`, { exact: true }).fill(quote);
  await panel.getByLabel(`${label}证券代码`, { exact: true }).fill('600519');
  await panel.getByLabel(`${label}指标`, { exact: true }).selectOption('归母净利润');
  await panel.getByLabel(`${label}期间类型`, { exact: true }).selectOption('annual');
  await panel.getByLabel(`${label}币种`, { exact: true }).selectOption('CNY');
  await panel.getByLabel(`${label}原单位`, { exact: true }).selectOption('万元');
  await panel.getByLabel(`${label}合并口径`, { exact: true }).selectOption('consolidated');
  await panel.getByLabel(`${label}数据属性`, { exact: true }).selectOption('forecast');
  await panel.getByLabel(`${label}期间开始`, { exact: true }).fill('2024-01-01');
  await panel.getByLabel(`${label}期间结束`, { exact: true }).fill('2024-12-31');
  await panel.getByLabel(`${label}数值一`, { exact: true }).fill(low);
  await panel.getByLabel(`${label}数值二`, { exact: true }).fill(high);
  await panel.getByLabel(`${label}已人工核对口径`, { exact: true }).check();
}
async function loadReport(panel, record) {
  const summary = panel.getByText('MyReports 原文件与指定页（不新建文档仓）', { exact: true });
  if (!(await summary.evaluate(node => node.parentElement.open))) await summary.click();
  await panel.getByRole('button', { name: '读取 / 刷新 MyReports 列表', exact: true }).click();
  await panel.getByLabel('本轮原文件', { exact: true }).selectOption(record.id);
  await panel.getByLabel('原页证券代码', { exact: true }).fill('600519');
  await panel.getByLabel('确认原文件证券归属', { exact: true }).check();
}
try {
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: 'block' });
    const errors = [], external = [], writes = [], reads = []; let phase = 'setup', reportStage = 0, delayed = null;
    await context.routeWebSocket('**/*', socket => { external.push(socket.url()); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
      if (url.origin !== baseURL) { external.push(url.href); return route.abort(); }
      if (!path.startsWith('/api/')) return route.continue();
      const ok = data => route.fulfill({ json: { data } });
      reads.push({ path, method: request.method() });
      if (path === '/api/myreports/page-read' && request.method() === 'POST') {
        const input = request.postDataJSON(), record = input.report_id === originalReport.id ? originalReport : revisedReport;
        assert.ok(record.id === originalReport.id || reportStage === 1, 'T0 cannot retrieve later information');
        assert.equal(input.expected_file_sha256, record.file_sha256);
        assert.deepEqual(input.selected_report_ids, [record.id]);
        if (delayed && record.id === revisedReport.id) { delayed.started(); await delayed.promise; }
        const text = record.id === originalReport.id ? originalText : revisedText;
        const requested = Array.from({ length: input.page_to - input.page_from + 1 }, (_, i) => input.page_from + i);
        return ok({ report_id: record.id, file_sha256: record.file_sha256, scope: 'INDEXED_PAGE_TEXT_ONLY', full_report_read: false, requested, returned_chars: text.length, complete_requested_text: requested.length === 1,
          coverage: { readable: [requested[0]], omitted: requested.slice(1), invalid: [], unreadable: [], error: [] }, items: requested.map((page, i) => i ? ({ page, status: 'omitted', reason: 'BUDGET' }) : ({ page, status: 'readable', reason: 'AVAILABLE', text, returned_chars: text.length, indexed_chars: text.length, truncated: false })) });
      }
      if (request.method() !== 'GET') { writes.push({ path, method: request.method() }); return route.fulfill({ status: 503, json: { detail: 'Synthetic fixture rejects all mutation/model endpoints' } }); }
      if (path === '/api/screener/discovery') return ok(discoverySnapshot);
      if (path === '/api/myreports') return ok(reportStage ? [originalReport, revisedReport] : [originalReport]);
      if (path === '/api/myreports/fulltext-search') return ok([{ report_id: url.searchParams.get('report_ids'), page: 1, snippet: '合成命中仅用于定位，不是已读正文。' }]);
      if (path === '/api/evidence') return ok(navigationEvidencePage([], url.searchParams));
      if (path === '/api/campaigns' || path === '/api/thesis') return ok({ items: [], total: 0 });
      if (path === '/api/native-intel/security-context/600519') return ok({ status: 'normal', security: { code: '600519', company_name: '合成公司' }, mapping: { terms: [], errors: [] }, window_hours: 24, observation: { items: [], item_count: 0 }, rank_history: {} });
      const reply = readReply('GET', path, url.search); if (reply) return route.fulfill({ json: reply });
      return route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable source' } });
    });
    let page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', error => errors.push(error.message));
    try {
      phase = 'T0-first-question';
      await page.goto('/screener?mode=discovery&strategy=SWING');
      await page.getByTestId('discovery-candidate-600519').click();
      await page.getByTestId('candidate-discovery-context').waitFor();
      let panel = page.getByTestId('research-check-panel');
      await panel.getByLabel('核对研究问题', { exact: true }).fill('合成预告是否被修订或兑现？');
      assert.match(await panel.getByLabel('为什么开始研究', { exact: true }).inputValue(), /来自市场发现/);
      await panel.getByTestId('check-discovery-origin').locator(':scope > summary').click();
      assert.match(await panel.getByTestId('check-discovery-origin').innerText(), /synthetic:history-source/);
      assert.match(await panel.getByTestId('check-discovery-origin').innerText(), /公告窗口未证明查全/);
      await loadReport(panel, originalReport);
      assert.equal(await panel.getByLabel('本轮原文件', { exact: true }).locator('option').count(), 2, 'T0 has only original report');
      await panel.getByRole('button', { name: '读取指定页并加入本轮', exact: true }).click();
      await panel.getByLabel(`本轮处理：${originalReport.title} · 第 1 页`, { exact: true }).selectOption('reviewed');
      await panel.getByLabel('本轮判断', { exact: true }).fill('T0：只能确认当时预计盈利，缺实际年报，不能判断兑现。'); // minimal save, no forced why/limits/next question
      phase = 'held-save-discard-race';
      await panel.getByRole('button', { name: '放弃当前核对草稿', exact: true }).click();
      await panel.getByRole('alertdialog', { name: '保留或放弃核对草稿' }).waitFor();
      assert.equal(await panel.getByTestId('check-save-round').isDisabled(), true, 'open discard dialog disables background save');
      await panel.getByRole('button', { name: '留下继续核对', exact: true }).click();
      // Delay delivery of the real local transaction completion, not its writes.
      await page.evaluate(() => {
        const descriptor = Object.getOwnPropertyDescriptor(IDBTransaction.prototype, 'oncomplete');
        let hold = true;
        window.__restoreCompletion = () => Object.defineProperty(IDBTransaction.prototype, 'oncomplete', descriptor);
        Object.defineProperty(IDBTransaction.prototype, 'oncomplete', { ...descriptor, set(listener) {
          if (hold && this.mode === 'readwrite') {
            hold = false; descriptor.set.call(this, event => { window.__releaseCompletion = () => listener.call(this, event); });
          } else descriptor.set.call(this, listener);
        } });
      });
      await panel.getByTestId('check-save-round').click();
      await page.waitForFunction(() => typeof window.__releaseCompletion === 'function');
      assert.equal(await panel.getByRole('alertdialog', { name: '保留或放弃核对草稿' }).count(), 0);
      assert.equal(await panel.getByTestId('check-save-round').isDisabled(), true);
      assert.equal(await panel.getByLabel('本轮判断', { exact: true }).isDisabled(), true);
      assert.equal(await panel.getByLabel('这只股票的研究问题', { exact: true }).isDisabled(), true);
      await page.evaluate(() => { window.__restoreCompletion(); window.__releaseCompletion(); });
      await panel.getByText(/本轮已保存。/).waitFor();
      const T0 = await readDatabase(page), q = T0.questions[0], t0 = T0.rounds[0];
      assert.equal(T0.questions.length, 1); assert.equal(T0.rounds.length, 1); assert.equal(t0.calculation, null);
      assert.equal(t0.materials[0].content, originalText); assert.equal(t0.materials[0].sourceHash, originalReport.file_sha256);
      assert.equal(t0.materials[0].provenance.security_assignment.automatically_verified, false);
      assert.equal(q.reviewedMaterialKeys.length, 1); assert.match(q.origin.label, /来自市场发现/);
      assert.equal(t0.limitations, '未记录 / 待核'); assert.equal(t0.nextMaterial, '');
      assert.equal(q.origin.snapshot.securityCode, '600519'); assert.equal(q.origin.snapshot.strategy, 'SWING');
      assert.deepEqual(q.origin.snapshot.reasonCodes, discoveryItem.reason_codes); assert.deepEqual(q.origin.snapshot.sourceNames, discoveryItem.provenance_refs);
      assert.equal(q.origin.snapshot.observations[0].rawValue, '0.12'); assert.equal(q.origin.snapshot.sourceFetchedAt, discoverySnapshot.fetched_at); assert.equal(q.origin.snapshot.asOf, discoveryItem.as_of);
      assert.ok(q.origin.snapshot.limitations.some(line => line.includes('公告窗口未证明查全')));
      assert.ok(q.origin.snapshot.limitations.some(line => line.includes('有限候选队列')));
      assert.ok(!JSON.stringify(T0).includes(revisedText), 'later content never enters T0');
      const savedT0 = panel.getByTestId('check-saved-round');
      await savedT0.getByText('实际保存的原文与读取范围', { exact: true }).click();
      assert.ok((await savedT0.innerText()).includes(originalText));
      assert.ok((await savedT0.innerText()).includes(originalReport.file_sha256));
      assert.equal(await savedT0.getByRole('link', { name: '在 MyReports 打开原文件', exact: true }).getAttribute('href'), '/my-reports?report=synthetic-original');
      await page.screenshot({ path: join(output, `T0-saved-${width}.png`) });

      phase = 'close-reopen-T0'; await page.close(); page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', error => errors.push(error.message));
      panel = await openQuestion(page, q.id);
      assert.match(await panel.getByTestId('check-saved-round').innerText(), /T0：只能确认/);
      assert.match(await panel.getByTestId('check-question-context').innerText(), /来自市场发现/);
      await panel.getByTestId('check-discovery-origin').locator(':scope > summary').click();
      assert.match(await panel.getByTestId('check-discovery-origin').innerText(), /synthetic:announcement-directory/);
      const reopenedT0 = panel.getByTestId('check-saved-round');
      await reopenedT0.getByText('实际保存的原文与读取范围', { exact: true }).click();
      assert.ok((await reopenedT0.innerText()).includes(originalText));
      assert.ok((await reopenedT0.innerText()).includes(originalReport.file_sha256));
      await panel.getByRole('button', { name: '以此轮材料继续核对', exact: true }).click();
      await panel.getByLabel(`本轮处理：${originalReport.title} · 第 1 页`, { exact: true }).selectOption('reviewed');

      phase = 'SPA-draft-retention';
      await panel.getByLabel('本轮判断', { exact: true }).fill('未保存的核对草稿');
      await page.getByTestId('candidate-stock-data-entry').click();
      const dialog = page.getByRole('dialog', { name: '研究内容尚未保存', exact: true }); await dialog.waitFor();
      await dialog.getByRole('button', { name: '留下继续编辑', exact: true }).click(); await dialog.waitFor({ state: 'hidden' });
      assert.equal(await panel.getByLabel('本轮判断', { exact: true }).inputValue(), '未保存的核对草稿');

      phase = 'T1-availability-and-delayed-read'; reportStage = 1;
      await loadReport(panel, revisedReport);
      let startResolve, releaseResolve; const started = new Promise(resolve => { startResolve = resolve; }), promise = new Promise(resolve => { releaseResolve = resolve; });
      delayed = { started: startResolve, promise, release: releaseResolve };
      await panel.getByRole('button', { name: '读取指定页并加入本轮', exact: true }).click(); await started;
      await panel.getByLabel('本轮原文件', { exact: true }).selectOption(originalReport.id); // invalidate late read ownership
      const lateResponse = page.waitForResponse(response => response.url().includes('/myreports/page-read'));
      delayed.release(); await lateResponse; delayed = null;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(await panel.getByLabel(`本轮处理：${revisedReport.title} · 第 1 页`, { exact: true }).count(), 0, 'late old selection must not join this draft');
      assert.equal(await panel.getByRole('button', { name: '读取指定页并加入本轮', exact: true }).isEnabled(), true, 'cancelled read clears spinner');
      await loadReport(panel, revisedReport);
      phase = 'hit-page-cancels-stale-read';
      await panel.getByRole('button', { name: '在此文件检索关键词', exact: true }).click();
      const hitButton = panel.getByRole('button', { name: '读取命中页及相邻页（命中 1 页）', exact: true }); await hitButton.waitFor();
      let hitStart, hitRelease; const hitStarted = new Promise(resolve => { hitStart = resolve; }), hitPending = new Promise(resolve => { hitRelease = resolve; });
      delayed = { started: hitStart, promise: hitPending, release: hitRelease };
      await panel.getByRole('button', { name: '读取指定页并加入本轮', exact: true }).click(); await hitStarted;
      await hitButton.click();
      const cancelledHitResponse = page.waitForResponse(response => response.url().includes('/myreports/page-read'));
      delayed.release(); await cancelledHitResponse; delayed = null;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(await panel.getByLabel(`本轮处理：${revisedReport.title} · 第 1 页`, { exact: true }).count(), 0, 'changing hit page range must invalidate the in-flight read');
      assert.equal(await panel.getByLabel('核对结束页', { exact: true }).inputValue(), '2');
      assert.equal(await panel.getByRole('button', { name: '读取指定页并加入本轮', exact: true }).isEnabled(), true);
      await panel.getByLabel('核对结束页', { exact: true }).fill('1');
      await panel.getByRole('button', { name: '读取指定页并加入本轮', exact: true }).click();
      await panel.getByLabel(`本轮处理：${revisedReport.title} · 第 1 页`, { exact: true }).selectOption('reviewed');
      await panel.getByLabel('本轮添加区间核对', { exact: true }).check();
      await panel.getByLabel('区间核对类型', { exact: true }).selectOption('revision');
      await operand(panel, '原预告', originalReport.title, originalText, '648.13', '753.93');
      await operand(panel, '修订预告', revisedReport.title, revisedText, '-594.25', '-891.37');
      assert.match(await panel.getByTestId('check-calculation-result').innerText(), /不重叠.*修订预告不是实际业绩/s);
      assert.match(await panel.getByTestId('check-calculation-result').innerText(), /\[-8913700, -5942500\]/);
      phase = 'alignment-fail-closed';
      await panel.getByLabel('修订预告证券代码', { exact: true }).fill('000001'); await panel.getByLabel('修订预告已人工核对口径', { exact: true }).check();
      assert.match(await panel.getByTestId('check-calculation-result').innerText(), /错股/);
      await panel.getByLabel('修订预告证券代码', { exact: true }).fill('600519'); await panel.getByLabel('修订预告期间结束', { exact: true }).fill('2024-09-30'); await panel.getByLabel('修订预告已人工核对口径', { exact: true }).check();
      assert.match(await panel.getByTestId('check-calculation-result').innerText(), /口径不一致/);
      await panel.getByLabel('修订预告期间结束', { exact: true }).fill('2024-12-31'); await panel.getByLabel('修订预告原单位', { exact: true }).selectOption('元'); await panel.getByLabel('修订预告已人工核对口径', { exact: true }).check();
      assert.match(await panel.getByTestId('check-calculation-result').innerText(), /原单位不一致/);
      await panel.getByLabel('修订预告原单位', { exact: true }).selectOption('万元'); await panel.getByLabel('修订预告数据属性', { exact: true }).selectOption('actual'); await panel.getByLabel('修订预告已人工核对口径', { exact: true }).check();
      assert.match(await panel.getByTestId('check-calculation-result').innerText(), /属性不匹配/);
      await panel.getByLabel('修订预告数据属性', { exact: true }).selectOption('forecast'); await panel.getByLabel('修订预告已人工核对口径', { exact: true }).check();
      await writeRound(panel, 'T1：盈利预告已被亏损预告取代；两个版本仍不是经审计实际。');
      phase = 'failed-save-retains-draft';
      await page.evaluate(() => { const native = IDBDatabase.prototype.transaction; IDBDatabase.prototype.transaction = function(...args) { if (this.name === 'vr-research-workflow' && args[1] === 'readwrite' && window.__failResearchWrites) throw new DOMException('Synthetic quota failure', 'QuotaExceededError'); return native.apply(this, args); }; window.__failResearchWrites = true; });
      await panel.getByTestId('check-save-round').click(); await panel.getByTestId('check-error').waitFor();
      assert.match(await panel.getByTestId('check-error').innerText(), /草稿/);
      assert.match(await panel.getByLabel('本轮判断', { exact: true }).inputValue(), /^T1：/);
      const failed = await readDatabase(page); assert.equal(failed.questions[0].headRoundId, q.headRoundId); assert.equal(failed.rounds.length, 1); assert.equal(failed.questions[0].reviewedMaterialKeys.length, 1);
      await page.evaluate(() => { window.__failResearchWrites = false; });
      await panel.getByTestId('check-save-round').click(); await panel.getByText(/本轮已保存。/).waitFor();
      const T1 = await readDatabase(page); assert.equal(T1.rounds.length, 2); assert.equal(T1.questions[0].reviewedMaterialKeys.length, 2);
      assert.deepEqual(T1.rounds.find(round => round.id === t0.id), t0, 'T0 stays byte-equivalent in semantic JSON');
      assert.equal(T1.rounds.find(round => round.id !== t0.id).parentRoundId, t0.id);
      await panel.getByLabel('打开原研究轮次', { exact: true }).selectOption(t0.id);
      assert.match(await panel.getByTestId('check-saved-round').innerText(), /T0：只能确认/);
      assert.ok(!(await panel.getByTestId('check-saved-round').innerText()).includes('T1：'));
      await page.screenshot({ path: join(output, `T1-reopen-T0-${width}.png`) });

      phase = 'two-page-conflict';
      const other = await context.newPage(); other.setDefaultTimeout(15000); const otherPanel = await openQuestion(other, q.id);
      await writeRound(panel, '并发旧页草稿必须保留。');
      await writeRound(otherPanel, '另一页先保存的第三轮。'); await otherPanel.getByTestId('check-save-round').click(); await otherPanel.getByText(/本轮已保存。/).waitFor();
      await panel.getByTestId('check-save-round').click(); await panel.getByTestId('check-error').waitFor();
      assert.match(await panel.getByTestId('check-error').innerText(), /其他页面更新/); assert.equal(await panel.getByLabel('本轮判断', { exact: true }).inputValue(), '并发旧页草稿必须保留。');
      const conflict = await readDatabase(page); assert.equal(conflict.rounds.length, 3);
      await panel.getByRole('button', { name: '查看最新轮次并保留草稿', exact: true }).click(); await panel.getByText(/已显示最新轮次/).waitFor();
      assert.equal(await panel.getByLabel('本轮判断', { exact: true }).inputValue(), '并发旧页草稿必须保留。');
      await panel.getByTestId('check-save-round').click(); await panel.getByText(/本轮已保存。/).waitFor();
      assert.equal((await readDatabase(page)).rounds.length, 4); await other.close();

      phase = 'manual-stage-history-counterexample';
      await panel.getByLabel('这只股票的研究问题', { exact: true }).selectOption('');
      await panel.getByLabel('核对研究问题', { exact: true }).fill('合成重组事项现在处于什么阶段？');
      await panel.getByLabel('为什么开始研究', { exact: true }).fill('阶段语义反例的人工转录测试，不是自动事件识别或严格PIT。');
      await writeRound(panel, '进展轮：公告回述停牌，但当前已经复牌，不能按背景句判断仍停牌。'); await panel.getByTestId('check-save-round').click(); await panel.getByText(/本轮已保存。/).waitFor();
      const stageFirst = (await readDatabase(page)).questions.find(item => item.id !== q.id);
      await panel.getByLabel('本轮判断', { exact: true }).fill('终止轮：新程序文件记载先前的终止决定。'); await panel.getByLabel('保存后的问题状态', { exact: true }).selectOption('resolved'); await panel.getByTestId('check-save-round').click(); await panel.getByText(/本轮已保存。/).waitFor();
      await writeRound(panel, '后续回述轮：再次提及同一终止事实，不是又终止一次。'); await panel.getByTestId('check-save-round').click(); await panel.getByText(/本轮已保存。/).waitFor();
      const stages = await readDatabase(page), stageQuestion = stages.questions.find(item => item.id === stageFirst.id), stageRounds = stages.rounds.filter(item => item.questionId === stageFirst.id);
      assert.equal(stageQuestion.status, 'resolved'); assert.equal(stageRounds.length, 3);
      await panel.getByLabel('打开原研究轮次', { exact: true }).selectOption(stageFirst.headRoundId);
      assert.match(await panel.getByTestId('check-saved-round').innerText(), /不能按背景句判断仍停牌/);
      await panel.getByLabel('保存后的问题状态', { exact: true }).selectOption('paused'); await writeRound(panel, '暂停常规待办，人工打开仍可查看原轮次。'); await panel.getByTestId('check-save-round').click(); await panel.getByText(/本轮已保存。/).waitFor();
      assert.match(await panel.getByTestId('check-question-context').innerText(), /已暂停常规待办/);
      assert.equal((await readDatabase(page)).questions.find(item => item.id === stageFirst.id).status, 'paused');
      phase = 'legacy-explicit-snapshot';
      await page.evaluate(() => localStorage.setItem('vr-notes', JSON.stringify([{ id: 'synthetic-legacy', title: '旧记录合成样本', kind: '问AI', content: '原旧内容，来源正文未保全。', ts: 1, research: { securityCode: '600519', question: '旧问题' } }])));
      await panel.getByText('本地备份与旧记录显式导入', { exact: true }).click();
      await panel.getByRole('button', { name: '预览旧笔记导入', exact: true }).click();
      assert.equal(await panel.getByTestId('check-legacy-snapshot').count(), 0, 'preview must not migrate');
      await panel.getByRole('button', { name: '确认复制 1 条旧记录', exact: true }).click();
      await panel.getByTestId('check-legacy-snapshot').waitFor();
      await panel.getByTestId('check-legacy-snapshot').locator(':scope > summary').click();
      assert.match(await panel.getByTestId('check-legacy-snapshot').innerText(), /原旧内容/);
      await page.evaluate(() => localStorage.setItem('vr-notes', '[]'));
      await panel.getByRole('button', { name: '刷新问题列表', exact: true }).click();
      await panel.getByText(/旧笔记源已变化/).waitFor();
      assert.match(await panel.getByTestId('check-legacy-snapshot').innerText(), /原旧内容/);
      phase = 'minimal-next-question-only';
      await panel.getByLabel('这只股票的研究问题', { exact: true }).selectOption('');
      await panel.getByLabel('核对研究问题', { exact: true }).fill('只有下一步的最小研究问题');
      await panel.getByLabel('下一项材料', { exact: true }).fill('先找原公告核对报告期间。');
      await panel.getByTestId('check-save-round').click(); await panel.getByText(/本轮已保存。/).waitFor();
      const minimal = await readDatabase(page), minimalQuestion = minimal.questions.find(item => item.question === '只有下一步的最小研究问题');
      const minimalRound = minimal.rounds.find(item => item.questionId === minimalQuestion.id);
      assert.equal(minimalRound.judgement, ''); assert.equal(minimalRound.limitations, '未记录 / 待核');
      assert.equal(minimalRound.nextMaterial, '先找原公告核对报告期间。');
      phase = 'layout-and-no-side-effects';
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'responsive page must not overflow horizontally');
      assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(writes, [], 'no formal state, AI, upload, import or index API writes');
      results.push({ width, status: 'PASS', evidence: 'synthetic production-dist UI with real disposable IndexedDB; not natural usage or PDF/PIT proof', reads, writes });
    } catch (error) {
      results.push({ width, status: 'FAIL', phase, error: error.message, stack: error.stack, errors, external, reads, writes });
      await page.screenshot({ path: join(output, `failure-${width}.png`) }).catch(() => {}); throw error;
    } finally { delayed?.release(); await context.close(); }
  }
} finally { writeFileSync(join(output, 'results.json'), JSON.stringify(results, null, 2)); await browser?.close(); server.closeAllConnections(); await new Promise(done => server.close(done)); console.log(output); }
