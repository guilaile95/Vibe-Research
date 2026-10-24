import { routeCredentialStatus } from './credential-generation.fixture.mjs';
// CI-only production component + exact API fixtures; no backend/provider/model.
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
const dist = join(tmpdir(), `vr-campaign-consent-dist-${process.pid}`);
const evidence = process.env.CAMPAIGN_AI_CONSENT_EVIDENCE_DIR || join(tmpdir(), `vr-campaign-consent-${process.pid}`);
mkdirSync(evidence, { recursive: true });
const audit = { requests: [], violations: [], errors: [] }, results = [];
let phase = 'build', status = 'FAIL', failure = null, origin, browser, context, page, held;
const receipt = campaign => ({ campaign_id: campaign, context_fingerprint: 'a'.repeat(64), scope: 'FULL_HOLDINGS_ACCOUNT_CAMPAIGN_THESIS_CRITICAL_DATA' });
const draftId = 'campaign_ai_draft_' + 'd'.repeat(32);
const generatedFields = { asset_view: { view: 'ASSET', stance: 'WAIT' }, trade_view: { view: 'TRADE', stance: 'WAIT' }, portfolio_view: { view: 'PORTFOLIO', constraint: 'synthetic' }, review_by: '2027-01-01T00:00:00.000000Z', key_assumptions: [], event_invalidation_conditions: [], strategy_horizon: 'synthetic' };
function generation(campaign) {
  const shared = { draft_id: draftId, campaign_id: campaign, thesis_id: 'b'.repeat(32), thesis_revision: 1, context_fingerprint: 'a'.repeat(64), generated_fields: generatedFields };
  return { ...shared, schema_version: 'campaign_ai_draft.v0.1', draft_status: 'AI_DRAFT', proposal_status: 'UNCOMMITTED', draft_witness: { ...shared, schema_version: 'campaign_ai_draft.witness.v0.1' } };
}
function latch(label) {
  let resolve, timer;
  const promise = new Promise((done, reject) => { resolve = () => { clearTimeout(timer); done(); }; timer = setTimeout(() => reject(new Error(`${label} timed out`)), 15000); });
  promise.catch(() => {}); // Held observers are handled immediately, before triggering actions.
  return { promise, resolve };
}
async function consentAction(page, accept) {
  const dialog = page.waitForEvent('dialog', { timeout: 10000 }).then(async value => {
    assert.ok(value.message().includes('https://model.example/v1'));
    for (const word of ['完整持仓', '全部证券', '账户资金与资产', '当前投资逻辑', '整个账户']) assert.ok(value.message().includes(word));
    await (accept ? value.accept() : value.dismiss());
  });
  await Promise.all([dialog, page.getByTestId('generate-ai-draft').click()]);
}
const server = createServer((req, res) => {
  const url = new URL(req.url, origin);
  if (url.pathname === '/favicon.ico') { res.writeHead(204).end(); return; }
  const target = resolve(dist, url.pathname === '/' ? 'index.html' : '.' + url.pathname);
  if (req.method !== 'GET' || !target.startsWith(dist + sep) || !existsSync(target) || url.pathname.startsWith('/api/')) { audit.violations.push(req.url); res.writeHead(403).end(); return; }
  res.writeHead(200, { 'content-type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(target)] || 'application/octet-stream' });
  res.end(readFileSync(target));
});
try {
  await build({ configFile: false, root: join(frontend, 'tests/e2e/campaign-ai-consent-adapter'), plugins: [react()], resolve: { alias: { '@': join(frontend, 'src') } }, css: { postcss: frontend }, build: { outDir: dist, emptyOutDir: true } });
  if (process.argv.includes('--build-only')) { status = 'BUILD_ONLY'; console.log('Production Campaign consent adapter built; browser NOT_RUN'); }
  else {
    if (process.env.GITHUB_ACTIONS !== 'true') throw new Error('Actual browser acceptance is restricted to existing GitHub CI');
    phase = 'browser';
    await new Promise(done => server.listen(0, '127.0.0.1', done)); origin = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({ headless: true, args: ['--disable-background-networking', '--dns-prefetch-disable'] });
    for (const viewport of [{ width: 1365, height: 900 }, { width: 390, height: 844 }]) {
      context = await browser.newContext({ viewport, serviceWorkers: 'block' });
      await context.routeWebSocket('**/*', socket => { audit.violations.push(`WebSocket ${socket.url()}`); socket.close(); });
      let mode = 'normal', generations = 0;
      await context.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url());
        try {
          if (url.origin !== origin) { audit.violations.push(url.origin); await route.abort(); return; }
          if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
          const match = /^\/api\/campaigns\/(campaign-one|campaign-two)\/ai-draft\/(consent-preview|generate)$/.exec(url.pathname);
          if (!match || req.method() !== 'POST' || url.search) { audit.violations.push(`${req.method()} ${url.pathname}`); await route.abort(); return; }
          audit.requests.push({ method: req.method(), path: url.pathname });
          const [, campaign, action] = match;
          if (action === 'consent-preview') {
            assert.equal(req.postData(), null);
            if (mode === 'held-preview') { held.started.resolve(); await held.release.promise; }
            await route.fulfill({ json: { data: receipt(mode === 'wrong-receipt' ? 'wrong' : campaign) } }); return;
          }
          const body = req.postDataJSON();
          assert.deepEqual(Object.keys(body).sort(), ['confirm_private_context', 'expected_context_fingerprint', 'llm']);
          assert.equal(body.confirm_private_context, true); assert.equal(body.expected_context_fingerprint, 'a'.repeat(64));
          assert.deepEqual(body.llm, { revision: '1', provider: 'api-compatible', model: 'synthetic-model', baseURL: 'https://model.example/v1', apiKey: 'synthetic' });
          generations++;
          if (mode === 'held-generate') { held.started.resolve(); await held.release.promise; }
          await route.fulfill({ json: { data: generation(campaign) } });
        } catch (error) { audit.errors.push(String(error)); await route.abort().catch(() => {}); }
      });
      await routeCredentialStatus(context, { provider: 'api-compatible', model: 'synthetic-model', baseURL: 'https://model.example/v1', apiKey: 'synthetic' });
      await context.addInitScript(() => {
        localStorage.setItem('vr-llm', JSON.stringify({ revision: '1', provider: 'api-compatible', model: 'synthetic-model', baseURL: 'https://model.example/v1', apiKey: 'synthetic' }));
        window.__consentParsed = { preview: 0, generate: 0 }; window.__consentAborts = 0;
        const original = window.fetch.bind(window);
        window.fetch = async (input, init) => {
          const url = new URL(typeof input === 'string' ? input : input.url, location.href);
          if (!url.pathname.includes('/ai-draft/')) return original(input, init);
          init?.signal?.addEventListener('abort', () => { window.__consentAborts++; });
          // Deliberately deliver old responses despite cancellation; test ownership, not only transport.
          const response = await original(input, { ...init, signal: undefined });
          const parse = response.json.bind(response);
          response.json = async () => { const value = await parse(); window.__consentParsed[url.pathname.endsWith('/generate') ? 'generate' : 'preview']++; return value; };
          return response;
        };
      });
      page = await context.newPage(); page.on('pageerror', error => audit.errors.push(String(error)));
      const go = async () => { mode = 'normal'; await page.goto(origin, { waitUntil: 'networkidle' }); await page.getByTestId('generate-ai-draft').waitFor(); };
      const idle = () => page.waitForFunction(() => document.querySelector('[data-testid="busy"]')?.textContent === 'false');
      const settled = async key => { await page.waitForFunction(key => window.__consentParsed[key] >= 1, key); await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))); };
      await go(); assert.equal(generations, 0);
      phase = `decline-${viewport.width}`; await consentAction(page, false); await idle(); assert.equal(generations, 0);
      mode = 'wrong-receipt'; await page.getByTestId('generate-ai-draft').click(); await page.getByRole('alert').filter({ hasText: '确认回执无效' }).waitFor(); assert.equal(generations, 0);
      await go(); phase = `stale-preview-${viewport.width}`; mode = 'held-preview'; held = { started: latch('preview arrival'), release: latch('preview release') };
      await Promise.all([held.started.promise, page.getByTestId('generate-ai-draft').click()]);
      await page.getByRole('button', { name: '切换投资计划' }).click(); held.release.resolve(); await settled('preview'); await idle();
      assert.equal(generations, 0); assert.equal(await page.getByTestId('result').innerText(), ''); assert.ok(await page.evaluate(() => window.__consentAborts > 0));
      await go(); phase = `stale-generation-${viewport.width}`; mode = 'held-generate'; held = { started: latch('generation arrival'), release: latch('generation release') };
      await Promise.all([held.started.promise, consentAction(page, true)]); assert.equal(generations, 1);
      await page.getByRole('button', { name: '切换模型' }).click(); held.release.resolve(); await settled('generate'); await idle();
      assert.equal(await page.getByTestId('result').innerText(), ''); assert.ok(await page.evaluate(() => window.__consentAborts > 0));
      await go(); phase = `accept-${viewport.width}`; await consentAction(page, true);
      await page.getByTestId('result').filter({ hasText: draftId }).waitFor(); await idle(); assert.equal(generations, 2);
      await page.screenshot({ path: join(evidence, `campaign-consent-${viewport.width}.png`), fullPage: true });
      results.push({ viewport, declineModelRequests: 0, wrongReceiptModelRequests: 0, stalePreviewModelRequests: 0, lateResultDeliveredAndSuppressed: true, confirmedGenerations: 2 });
      await context.close(); context = null; page = null;
    }
    assert.deepEqual(audit.violations, []); assert.deepEqual(audit.errors, []); status = 'PASS';
  }
} catch (error) {
  failure = String(error?.stack || error); process.exitCode = 1;
  if (page) { await page.screenshot({ path: join(evidence, 'failure.png'), fullPage: true }).catch(() => {}); const dom = await page.content().catch(() => 'unavailable'); writeFileSync(join(evidence, 'failure.html'), dom); }
  console.error(failure);
} finally {
  held?.release.resolve(); held?.started.resolve();
  writeFileSync(join(evidence, 'result.json'), JSON.stringify({ status, phase, failure, viewport: page?.viewportSize() || null, results, audit, actualModels: 0, actualProviders: 0 }, null, 2));
  await context?.close(); await browser?.close(); if (server.listening) await new Promise(done => server.close(done));
}
