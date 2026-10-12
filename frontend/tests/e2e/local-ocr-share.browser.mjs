// Actual production components + exact API fixtures. No backend/model/provider;
// real Tesseract/PDF/index source-to-sink is verified separately in Python.
import assert from 'node:assert/strict';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
const frontend = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const dist = join(tmpdir(), `vr-ocr-share-dist-${process.pid}`);
await build({ configFile: false, root: join(frontend, 'tests/e2e/local-ocr-share-adapter'), plugins: [react()], resolve: { alias: { '@': join(frontend, 'src') } }, css: { postcss: frontend }, build: { outDir: dist, emptyOutDir: true } });
if (process.argv.includes('--build-only')) { console.log('Production OCR/share adapter built; browser NOT_RUN'); process.exit(0); }
const evidence = process.env.LOCAL_OCR_SHARE_EVIDENCE_DIR || join(tmpdir(), `vr-ocr-share-${process.pid}`);
mkdirSync(evidence, { recursive: true });
const errors = [], requests = [], violations = [], results = [];
let origin, browser, context, page;
const server = createServer((req, res) => {
  const url = new URL(req.url, origin);
  const target = resolve(dist, url.pathname === '/' ? 'index.html' : '.' + url.pathname);
  if (req.method !== 'GET' || !target.startsWith(dist + sep) || !existsSync(target) || url.pathname.startsWith('/api/')) { violations.push(req.url); res.writeHead(403).end(); return; }
  res.writeHead(200, { 'content-type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(target)] || 'application/octet-stream' }); res.end(readFileSync(target));
});
await new Promise(done => server.listen(0, '127.0.0.1', done)); origin = `http://127.0.0.1:${server.address().port}`;
try {
  browser = await chromium.launch({ headless: true });
  for (const viewport of [{ width: 1365, height: 900 }, { width: 390, height: 844 }]) {
    context = await browser.newContext({ viewport, acceptDownloads: true, serviceWorkers: 'block' });
    let mode = 'normal', pageMode = 'normal', capabilityMode = 'normal', release, observed, releaseCapability, capabilityObserved;
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== origin) { violations.push(req.url()); await route.abort(); return; }
      if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
      if (url.search) { violations.push(`unexpected query ${req.method()} ${url.pathname}${url.search}`); await route.abort(); return; }
      requests.push({ method: req.method(), path: url.pathname });
      if (url.pathname === '/api/local-ocr/capability' && req.method() === 'GET') {
        if (capabilityMode === 'held') {
          capabilityObserved?.(); await new Promise(done => { releaseCapability = done; });
          await route.fulfill({ json: { data: { image: 'late-malformed' } } }); return;
        }
        if (capabilityMode === 'malformed') { await route.fulfill({ json: { data: { image: {}, pdf: true } } }); return; }
        await route.fulfill({ json: { data: { image: true, pdf: true, engine: 'local-tesseract', status: 'AVAILABLE', english_language_status: 'INSTALLED_QUALITY_NOT_VERIFIED', chinese_language_status: 'CHINESE_LANGUAGE_UNAVAILABLE', automatic_language_fallback: false } } }); return;
      }
      if (url.pathname === '/api/local-ocr/reports/synthetic' && req.method() === 'POST') {
        assert.deepEqual(req.postDataJSON(), { expected_file_sha256: 'a'.repeat(64), language: 'eng', confirm_local_processing: true });
        observed?.();
        if (mode === 'held') await new Promise(done => { release = done; });
        if (mode === 'malformed') { await route.fulfill({ json: { data: { status: 'SEARCHABLE', report_id: 'wrong-report' } } }); return; }
        if (mode === 'unavailable') { await route.fulfill({ status: 400, json: { detail: 'OCR_DEPENDENCY_UNAVAILABLE' } }); return; }
        await route.fulfill({ json: { data: { schema_version: 'local_ocr_report_receipt.v1', report_id: 'synthetic', file_sha256: 'a'.repeat(64), status: 'SEARCHABLE', indexed_at: '2026-10-12T10:00:00+00:00', extraction: { schema_version: 'local_ocr_preview.v1', status: 'OCR_UNVERIFIED', source_sha256: 'a'.repeat(64), engine: 'local-tesseract', language: 'eng', source_truth_verified: false, limitations: ['synthetic OCR only'], pages: [{ page_number: 1, source_sha256: 'a'.repeat(64), image_sha256: 'b'.repeat(64), text_sha256: 'c'.repeat(64), mean_word_confidence: 93 }] } } } }).catch(() => {}); return;
      }
      if (url.pathname === '/api/local-ocr/reports/legacy' && req.method() === 'POST') {
        assert.deepEqual(req.postDataJSON(), { expected_file_sha256: 'c'.repeat(64), language: 'eng', confirm_local_processing: true });
        await route.fulfill({ json: { data: { status: 'SEARCHABLE', report_id: 'wrong' } } }); return;
      }
      if (url.pathname === '/api/local-ocr/reports/legacy/identity' && req.method() === 'GET') { await route.fulfill({ json: { data: { report_id: 'legacy', file_sha256: 'c'.repeat(64), extension: '.pdf', writes: 0 } } }); return; }
      if (url.pathname === '/api/local-ocr/reports/synthetic/identity' && req.method() === 'GET') { await route.fulfill({ json: { data: { report_id: 'synthetic', file_sha256: 'a'.repeat(64), extension: '.pdf', writes: 0 } } }); return; }
      if (url.pathname === '/api/myreports' && req.method() === 'GET') { if (mode === 'reread-fail') { await route.fulfill({ status: 500, json: { detail: 'synthetic index unavailable' } }); return; } await route.fulfill({ json: { data: [{ id: 'synthetic', file_sha256: 'a'.repeat(64), text_index_status: 'SEARCHABLE', text_index_error: 'LOCAL_OCR_UNVERIFIED' }, { id: 'legacy', file_sha256: 'c'.repeat(64), text_index_status: 'SEARCHABLE', text_index_error: 'LOCAL_OCR_UNVERIFIED' }] } }); return; }
      if (url.pathname === '/api/myreports/page-read' && req.method() === 'POST') {
        if (pageMode === 'malformed') { await route.fulfill({ json: { data: { report_id: 'synthetic', file_sha256: 'a'.repeat(64), extraction: { pages: null, engine: {} } } } }); return; }
        assert.deepEqual(req.postDataJSON(), { report_id: 'synthetic', selected_report_ids: ['synthetic'], expected_file_sha256: 'a'.repeat(64), page_from: 1, page_to: 1 });
        await route.fulfill({ json: { data: { report_id: 'synthetic', file_sha256: 'a'.repeat(64), scope: 'INDEXED_PAGE_TEXT_ONLY', full_report_read: false,
          requested: [1], returned_chars: 16, complete_requested_text: true, coverage: { readable: [1], omitted: [], invalid: [], unreadable: [], error: [] },
          items: [{ page: 1, status: 'readable', text: 'SYNTHETIC REPORT', returned_chars: 16, indexed_chars: 16, truncated: false, reason: 'INDEXED_TEXT' }],
          extraction: { schema_version: 'local_ocr_preview.v1', status: 'OCR_UNVERIFIED', source_truth_verified: false, limitations: ['synthetic only'], engine: 'local-tesseract', language: 'eng', source_sha256: 'a'.repeat(64), pages: [{ page_number: 1, source_sha256: 'a'.repeat(64), image_sha256: 'b'.repeat(64), text_sha256: 'c'.repeat(64), mean_word_confidence: 93 }] } } } }); return;
      }
      violations.push(`${req.method()} ${url.pathname}`); await route.abort();
    });
    await context.addInitScript(() => {
      const original = window.fetch.bind(window);
      window.__lateCapabilityParsed = false; window.__capabilityAborts = 0;
      window.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        if (url.pathname !== '/api/local-ocr/capability') return original(input, init);
        init?.signal?.addEventListener('abort', () => { window.__capabilityAborts++; });
        // Deliberately deliver an aborted old response to verify ownership,
        // rather than passing solely because transport cancelled first.
        const response = await original(input, { ...init, signal: undefined });
        const json = response.json.bind(response);
        response.json = async () => { const data = await json(); if (data.data?.image === 'late-malformed') window.__lateCapabilityParsed = true; return data; };
        return response;
      };
    });
    page = await context.newPage(); page.on('pageerror', e => errors.push(e.message));
    await page.goto(origin, { waitUntil: 'networkidle' });
    assert.equal(requests.filter(r => r.path.includes('ocr') && r.method === 'POST').length, results.length * 6, 'no mount-triggered OCR');
    const ocr = page.getByTestId('primary-ocr').getByTestId('local-report-ocr');
    await ocr.getByRole('button', { name: '本机 OCR', exact: true }).click();
    await ocr.getByText(/CHINESE_LANGUAGE_UNAVAILABLE/).waitFor();
    assert.equal(await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).isDisabled(), true);
    await ocr.getByRole('button', { name: '收起 OCR', exact: true }).click();
    await ocr.getByRole('button', { name: '本机 OCR', exact: true }).click();
    await ocr.getByText(/CHINESE_LANGUAGE_UNAVAILABLE/).waitFor();
    await ocr.getByRole('combobox').selectOption('eng');
    await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).click();
    await ocr.getByRole('status').getByText(/已保存 1 页/).waitFor();
    await page.getByTestId('index-refresh-count').getByText('刷新次数 1', { exact: true }).waitFor();
    await page.getByTestId('report-page-reader').locator('summary').click();
    await page.getByRole('button', { name: '读取指定页', exact: true }).click();
    await page.getByTestId('report-ocr-provenance').getByText(/平均词识别分数 93/).waitFor();
    pageMode = 'malformed';
    await page.getByRole('button', { name: '读取指定页', exact: true }).click();
    await page.getByTestId('report-page-reader').getByRole('alert').getByText(/读取失败/).waitFor();
    assert.equal(await page.getByTestId('report-ocr-provenance').count(), 0);
    pageMode = 'normal';
    await page.getByRole('button', { name: '读取指定页', exact: true }).click();
    await page.getByTestId('report-ocr-provenance').getByText(/平均词识别分数 93/).waitFor();
    mode = 'unavailable';
    await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).click();
    await ocr.getByRole('status').getByText(/OCR_DEPENDENCY_UNAVAILABLE/).waitFor();
    assert.equal(await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).isDisabled(), true);
    await ocr.getByRole('button', { name: '重新读取索引状态' }).click();
    await ocr.getByRole('status').getByText(/已重新读取/).waitFor();
    mode = 'malformed';
    await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).click();
    await ocr.getByRole('status').getByText(/回执无法核验/).waitFor();
    assert.equal(await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).isDisabled(), true);
    mode = 'reread-fail';
    await ocr.getByRole('button', { name: '重新读取索引状态' }).click();
    await ocr.getByRole('status').getByText(/索引状态仍不确定/).waitFor();
    assert.equal(await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).isDisabled(), true);
    mode = 'normal';
    await ocr.getByRole('button', { name: '重新读取索引状态' }).click();
    await ocr.getByRole('status').getByText(/已重新读取/).waitFor();
    mode = 'held';
    const started = new Promise(done => { observed = done; });
    await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).click(); await started;
    await ocr.getByRole('button', { name: '取消 OCR' }).click();
    await ocr.getByRole('status').getByText(/已请求取消/).waitFor();
    release(); await page.getByRole('button', { name: '切换资料面板' }).click();
    await page.getByRole('button', { name: '切换资料面板' }).click();
    assert.equal(await page.getByTestId('index-refresh-count').innerText(), '刷新次数 1');
    // A newer source identity owns its busy/message state even while an old POST is held.
    await ocr.getByRole('button', { name: '本机 OCR', exact: true }).click();
    await ocr.getByRole('combobox').selectOption('eng');
    await ocr.getByRole('button', { name: '重新读取索引状态' }).click();
    await ocr.getByRole('status').getByText(/已重新读取/).waitFor();
    const identityStarted = new Promise(done => { observed = done; });
    await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).click(); await identityStarted;
    await page.getByRole('button', { name: '切换原文件版本' }).click(); release();
    await ocr.getByText(new RegExp('源 SHA256：' + 'b'.repeat(64))).waitFor();
    await page.waitForFunction(element => element && !element.disabled, await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).elementHandle());
    assert.equal(await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).isEnabled(), true);
    assert.equal(await ocr.getByRole('status').count(), 0);
    assert.equal(await page.getByTestId('index-refresh-count').innerText(), '刷新次数 1');
    // A legacy report can reconcile its completed server write using the digest
    // obtained before POST, even though its original prop has no file digest.
    const legacy = page.getByTestId('legacy-ocr');
    await legacy.getByRole('button', { name: '本机 OCR', exact: true }).click();
    await legacy.getByRole('combobox').selectOption('eng');
    await legacy.getByRole('button', { name: '确认本机识别并建立索引' }).click();
    await legacy.getByRole('status').getByText(/回执无法核验/).waitFor();
    await legacy.getByRole('button', { name: '重新读取索引状态' }).click();
    await legacy.getByRole('status').getByText(/已重新读取/).waitFor();
    assert.equal(await legacy.getByRole('button', { name: '确认本机识别并建立索引' }).isEnabled(), true);
    const share = page.getByTestId('research-share-card');
    await share.locator('summary').click(); await share.getByLabel('PE-TTM', { exact: true }).check();
    const [download] = await Promise.all([page.waitForEvent('download'), share.getByRole('button', { name: '下载公开数据 JSON' }).click()]);
    const raw = readFileSync(await download.path(), 'utf8'), card = JSON.parse(raw);
    assert.equal(card.security_code, '600000'); assert.equal(card.data_kind, 'FIXTURE');
    assert.equal(card.facts[1].status, 'MISSING'); assert.equal(card.facts[1].as_of, null);
    assert.doesNotMatch(raw, /SECRET_|PRIVATE_NAME|\/home\/private/);
    const [svgDownload] = await Promise.all([page.waitForEvent('download'), share.getByRole('button', { name: '下载研究卡 SVG' }).click()]);
    const svg = readFileSync(await svgDownload.path(), 'utf8');
    assert.match(svg, /FIXTURE/); assert.doesNotMatch(svg, /SECRET_|<script|href=/);
    assert.equal(await page.evaluate(text => new DOMParser().parseFromString(text, 'image/svg+xml').querySelector('parsererror') === null, svg), true);
    assert.equal(await share.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
    await share.screenshot({ path: join(evidence, `${viewport.width}-share.png`) });
    await share.getByLabel('报价', { exact: true }).uncheck(); await share.getByLabel('PE-TTM', { exact: true }).uncheck();
    assert.equal(await share.getByRole('button', { name: '下载公开数据 JSON' }).isDisabled(), true);
    capabilityMode = 'malformed';
    await ocr.getByRole('button', { name: '收起 OCR', exact: true }).click();
    await ocr.getByRole('button', { name: '本机 OCR', exact: true }).click();
    await ocr.getByText(/本机 OCR 能力无法核验/).waitFor();
    assert.equal(await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).isDisabled(), true);
    capabilityMode = 'held';
    await ocr.getByRole('button', { name: '收起 OCR', exact: true }).click();
    const capabilityStarted = new Promise(done => { capabilityObserved = done; });
    await ocr.getByRole('button', { name: '本机 OCR', exact: true }).click(); await capabilityStarted;
    capabilityMode = 'normal';
    await page.getByRole('button', { name: '切换原文件版本' }).click();
    await ocr.getByText(/CHINESE_LANGUAGE_UNAVAILABLE/).waitFor();
    // The earlier cancelled write is deliberately still uncertain for identity A.
    await ocr.getByRole('button', { name: '重新读取索引状态' }).click();
    await ocr.getByRole('status').getByText(/已重新读取/).waitFor();
    releaseCapability(); await page.waitForFunction(() => window.__lateCapabilityParsed);
    assert.equal(await ocr.getByText(/本机 OCR 能力无法核验/).count(), 0);
    assert.ok(await page.evaluate(() => window.__capabilityAborts > 0));
    assert.equal(await ocr.getByRole('button', { name: '确认本机识别并建立索引' }).isEnabled(), true);
    results.push({ viewport, ocr: 'success-error-malformed-reread-failure-cancel-no-late-refresh', share: 'json-svg-missing-private-exclusion' });
    await context.close(); context = null;
  }
  assert.deepEqual(errors, []); assert.deepEqual(violations, []);
} catch (error) { console.error(error); process.exitCode = 1; }
finally {
  writeFileSync(join(evidence, 'results.json'), JSON.stringify({ results, requests, violations, errors, passed: !process.exitCode }, null, 2));
  await context?.close(); await browser?.close(); await new Promise(done => server.close(done));
}
