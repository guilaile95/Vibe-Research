/** Full-app synthetic image-request acceptance. CI only; no backend/provider.
 * Build first and set E2E_MARKDOWN_IMAGES_OUTPUT_DIR. All remote traffic is
 * intercepted before navigation; sentinel requests are counted and aborted.
 */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { ANCILLARY_CLOCK, ancillaryReply, encode, syntheticLlm } from './final-families.fixture.mjs';

const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
assert.ok(process.env.E2E_MARKDOWN_IMAGES_OUTPUT_DIR, 'Set E2E_MARKDOWN_IMAGES_OUTPUT_DIR');
const output = resolve(process.env.E2E_MARKDOWN_IMAGES_OUTPUT_DIR);
mkdirSync(output, { recursive: true });
const sentinel = '__markdown_image_sentinel__';
const markdown = name => `## ${name}\n\n![${name} remote](https://example.invalid/${sentinel}/${name}.png)\n\n![${name} relative](/${sentinel}/${name}.png)\n\n![${name} reference][image]\n\n[image]: //example.invalid/${sentinel}/${name}-ref.png\n\n[Ordinary source](https://example.invalid/source)\n\n\`code stays code\`\n\n| Fact | Value |\n| --- | --- |\n| Synthetic | 1 |`;
const daily = ancillaryReply('GET', '/api/daily-review');
daily.data.sector_rotation.highlights.strongest_industry = { code: 'BK0001', name: 'Synthetic industry', change_pct: 1 };
const savedReview = { id: 'synthetic-review', result_type: 'daily_review_ai', trade_date: '2026-10-08', generated_at: '2026-10-08T16:00:00Z', model_provider: 'synthetic', model_name: 'offline', payload: { markdown: markdown('daily-saved'), source_review_generated_at: '2026-10-08T15:00:00Z' } };
const industry = { key: 'ai', name: 'Synthetic industry', items: [{ title: 'Synthetic source', source: 'Synthetic', url: 'https://example.invalid/article', published_at: '2026-10-08T10:00:00Z', time: '2026-10-08' }] };
const results = { suite: 'markdown-images', transport: 'synthetic local only; no backend/provider', fonts: 'Exact known stylesheet stub; system fallback', cases: [], status: 'running' };
const record = () => writeFileSync(join(output, 'results.json'), JSON.stringify(results, null, 2));
record();
let browser, server, streamResponse, streamTimer;
const finishStream = () => { clearTimeout(streamTimer); streamResponse?.end(encode([{ type: 'done' }])); streamResponse = undefined; };
try {
  assert.ok(existsSync(join(dist, 'index.html')), 'Run npm run build first');
  server = createServer((req, res) => {
    const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
    if (pathname === '/api/daily-review/analyze' && req.method === 'POST') {
      res.writeHead(200, { 'content-type': 'application/x-ndjson', 'cache-control': 'no-store' });
      res.write(encode([{ type: 'delta', text: markdown('daily-stream') }]));
      streamResponse = res;
      // Bound the held real stream even if the assertion never releases it.
      streamTimer = setTimeout(() => res.destroy(), 20000);
      res.on('close', () => clearTimeout(streamTimer));
      return;
    }
    if (pathname.startsWith('/api/') || pathname.includes(sentinel)) { res.writeHead(500).end('Unexpected synthetic dispatch'); return; }
    let target = resolve(dist, '.' + decodeURIComponent(pathname));
    if (target !== resolve(dist) && !target.startsWith(resolve(dist) + sep)) { res.writeHead(403).end(); return; }
    if (!existsSync(target) || !statSync(target).isFile()) target = join(dist, 'index.html');
    res.setHeader('content-type', { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }[extname(target)] || 'application/octet-stream');
    res.end(readFileSync(target));
  });
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  const origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: 'block' });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    const attempts = [], unexpected = [], errors = [], requests = [];
    let releaseSave, saveTimer, caseName = 'initialization', chatName = 'ask-ai';
    await context.addInitScript(({ markdown, llm, sentinel }) => {
      localStorage.setItem('vr-llm', JSON.stringify(llm));
      localStorage.setItem('vr-notes', JSON.stringify([{ id: 'synthetic-note', kind: '问AI', title: 'Synthetic image note', content: markdown, ts: 1 }]));
      window.__markdownResourceNodes = [];
      // Observe transient resource nodes too, including React-generated preloads.
      const inspect = root => {
        if (!(root instanceof Element)) return;
        for (const element of [root, ...root.querySelectorAll('img,source,link')]) {
          if (['IMG', 'SOURCE', 'LINK'].includes(element.tagName)
              && ['src', 'srcset', 'href', 'imagesrcset'].some(attr => (element.getAttribute(attr) || '').includes(sentinel))) {
            window.__markdownResourceNodes.push(element.outerHTML);
          }
        }
      };
      new MutationObserver(records => records.forEach(record => {
        inspect(record.target); record.addedNodes.forEach(inspect);
      })).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['src', 'srcset', 'href', 'imagesrcset'] });
    }, { markdown: markdown('note'), llm: syntheticLlm, sentinel });
    await context.routeWebSocket('**/*', socket => { unexpected.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), method = request.method();
      if (url.href.includes(sentinel)) { attempts.push(url.href); return route.abort(); }
      if (method === 'GET' && request.resourceType() === 'stylesheet' && url.href === 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap') {
        return route.fulfill({ contentType: 'text/css', body: '/* Offline fixture: system fallback font. */' });
      }
      if (url.origin !== origin) { unexpected.push(`${method} ${url.href}`); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      requests.push(`${method} ${url.pathname}`);
      const ndjson = events => route.fulfill({ contentType: 'application/x-ndjson', body: encode(events) });
      const content = markdown(chatName);
      if (method === 'POST' && url.pathname === '/api/chat') return ndjson([{ type: 'delta', text: content }, { type: 'done' }]);
      if (method === 'POST' && url.pathname === '/api/reflect') return ndjson([{ type: 'delta', text: markdown('reflection') }, { type: 'done', content: markdown('reflection'), truncated: false }]);
      if (method === 'POST' && url.pathname === '/api/debate') {
        const stages = ['bull', 'bear', 'referee'].map(stage => ({ stage, content: markdown(`debate-${stage}`) }));
        return ndjson([...stages.flatMap(({ stage, content }) => [{ type: 'stage', stage, label: stage }, { type: 'delta', stage, text: content }, { type: 'stage_done', stage, label: stage, content }]), { type: 'done', code: '600519', stages }]);
      }
      if (method === 'POST' && url.pathname === '/api/daily-review/analyze') return route.continue();
      if (method === 'POST' && url.pathname === '/api/daily-review/lead-analysis') {
        const body = request.postDataJSON();
        return ndjson([{ type: 'lead_context', context: { schema_version: 'daily-review-lead-context.v1', kind: body.kind, subject: { code: body.subject, name: 'Synthetic industry' }, source_path: 'synthetic', source: { status: 'normal', source: 'synthetic', trade_date: '2026-10-08', data_time: null, fetched_at: null, is_stale: false }, review_generated_at: null, cache_stale: false, facts: {}, unknowns: [] } }, { type: 'delta', text: markdown('lead-analysis') }, { type: 'done' }]);
      }
      if (method === 'POST' && url.pathname === '/api/intel-digests') {
        await new Promise(done => { releaseSave = done; saveTimer = setTimeout(() => { errors.push('Synthetic digest save hold expired'); done(); }, 20000); });
        clearTimeout(saveTimer);
        return route.fulfill({ json: { data: { digest: { summary_text: markdown('digest-new'), digest_date: '2026-10-08' }, deduped: false } } });
      }
      if (method !== 'GET') { unexpected.push(`${method} ${url.pathname}`); return route.fulfill({ status: 500, json: { detail: 'Unexpected synthetic mutation' } }); }
      if (url.pathname === '/api/daily-review') return route.fulfill({ json: daily });
      if (url.pathname === '/api/ai-results/daily_review_ai') return route.fulfill({ json: { data: savedReview } });
      if (url.pathname === '/api/radar') return route.fulfill({ json: { data: { industries: [industry], stats: { total_sources: 1 }, generated_at: '2026-10-08T16:00:00Z' } } });
      if (url.pathname === '/api/intel-digests/latest') return route.fulfill({ json: { digest: { summary_text: markdown('digest-saved'), digest_date: '2026-10-08' } } });
      if (url.pathname === '/api/agent-runtime/status') return route.fulfill({ json: { available: true, installed: true, authenticated: true, status: 'ready', runtime: 'Codex Subscription' } });
      const common = ancillaryReply(method, url.pathname, url.search);
      if (common) return route.fulfill({ json: common });
      // Unrelated read-only bootstrap panels are explicitly unavailable. Never
      // forward an unknown API to a backend or misrepresent it as successful data.
      return route.fulfill({ status: 503, json: { detail: 'Synthetic unrelated panel unavailable' } });
    });
    const page = await context.newPage();
    await page.clock.setFixedTime(new Date(ANCILLARY_CLOCK));
    page.setDefaultTimeout(10000); page.setDefaultNavigationTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    const verify = async (name, scope = page) => {
      caseName = name;
      const prose = scope.locator('.prose').filter({ has: page.getByRole('heading', { name, exact: true }) });
      await prose.getByText(`[图片未加载：${name} remote]`, { exact: true }).waitFor();
      await prose.getByText(`[图片未加载：${name} relative]`, { exact: true }).waitFor();
      await prose.getByText(`[图片未加载：${name} reference]`, { exact: true }).waitFor();
      assert.equal(await prose.locator('a').getAttribute('href'), 'https://example.invalid/source');
      assert.equal(await prose.locator('code').innerText(), 'code stays code');
      assert.equal(await prose.locator('table tbody tr').innerText(), 'Synthetic\t1');
      assert.equal(await prose.locator('img,source,link[rel="preload"]').count(), 0);
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
      assert.deepEqual(attempts, [], 'No sentinel request may reach dispatch');
      assert.deepEqual(await page.evaluate(() => window.__markdownResourceNodes), [], 'No transient resource-bearing sentinel node');
      assert.deepEqual(unexpected, []); assert.deepEqual(errors, []);
      await prose.scrollIntoViewIfNeeded();
      await page.screenshot({ path: join(output, `${width}-${name}.png`), fullPage: true });
      results.cases.push({ width, name, status: 'passed', sentinelAttempts: 0, resourceNodes: 0 }); record();
    };
    try {
      await page.goto(origin + '/notes?note=synthetic-note', { waitUntil: 'domcontentloaded' });
      await verify('note');
      await page.getByRole('button', { name: '反思审计', exact: true }).click();
      await verify('reflection');
      await page.goto(origin + '/debate', { waitUntil: 'domcontentloaded' });
      await page.getByPlaceholder('6 位代码，如 600519').fill('600519');
      await page.locator('select').selectOption('1');
      await page.getByRole('button', { name: '开始辩论', exact: true }).click();
      await page.getByText('辩论完成', { exact: true }).waitFor();
      for (const role of ['bull', 'bear', 'referee']) await verify(`debate-${role}`);
      await page.goto(origin + '/daily-review', { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: 'AI 梳理行业表现', exact: true }).click();
      await verify('lead-analysis', page.getByTestId('lead-analysis-dialog'));
      await page.getByRole('button', { name: '关闭线索分析', exact: true }).click();
      await page.getByTestId('today-ai-review').locator(':scope > summary').click();
      await verify('daily-saved', page.getByTestId('today-ai-review'));
      await page.getByRole('button', { name: '重新复盘', exact: true }).click();
      await verify('daily-stream', page.getByTestId('today-ai-review'));
      // Close the fixture stream without saved-result metadata; it cannot
      // fabricate a persisted successful review. Continue with the next page.
      finishStream();
      await page.goto(origin + '/intel', { waitUntil: 'domcontentloaded' });
      await verify('digest-saved', page.getByTestId('market-intel-panel'));
      chatName = 'digest-new';
      await page.getByRole('button', { name: '重新提炼', exact: true }).click();
      await page.getByText('摘要已生成，正在保存到数据库…', { exact: true }).waitFor();
      await verify('digest-new', page.getByTestId('market-intel-panel'));
      releaseSave(); releaseSave = undefined;
      await page.getByRole('button', { name: '重新提炼', exact: true }).waitFor();
      chatName = 'ask-ai';
      await page.goto(origin + '/sectors/ai-computing/industry', { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: '问 AI', exact: true }).first().click();
      await page.getByPlaceholder('询问 Vibe...').fill('Synthetic render-only question');
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await verify('ask-ai', page.getByRole('complementary', { name: 'Vibe AI 对话' }));
      assert.deepEqual(errors, []); assert.deepEqual(unexpected, []); assert.deepEqual(attempts, []);
    } catch (error) {
      results.cases.push({ width, name: caseName, status: 'failed', error: String(error), attempts, unexpected, errors, requests });
      await page.screenshot({ path: join(output, `${width}-failure.png`), fullPage: true }).catch(() => {});
      writeFileSync(join(output, `${width}-failure.html`), await page.content().catch(() => 'Page unavailable'));
      throw error;
    } finally {
      finishStream(); releaseSave?.(); clearTimeout(saveTimer);
      await context.tracing.stop({ path: join(output, `${width}-trace.zip`) });
      await context.close(); record();
    }
  }
  results.status = 'passed';
} catch (error) { results.status = 'failed'; results.error = String(error); process.exitCode = 1; }
finally {
  finishStream(); await browser?.close();
  if (server) { server.closeAllConnections(); await new Promise(done => server.close(done)); }
  record(); console.log(JSON.stringify(results, null, 2));
}
