import { readCalendarStatusReply } from "./calendar-status.fixture.mjs";
// Full production Settings route; synthetic noncredential APIs only. No backend/provider.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { platformScenario } from './platform-settings.scenario.mjs';
import { readReply } from './ai-settings-storage.fixture.mjs';
const frontend = fileURLToPath(new URL('../../', import.meta.url));
const dist = join(frontend, 'dist');
const profile = { profile_id: 'default', name: 'SYNTHETIC', method: 'keyword', interests_text: '', min_score: 0.7,
  keyword_rules: { global_excludes: ['KEEP'], filter_terms: [], groups: [] }, tags: [] };
const config = { rss_freshness_enabled: false, rss_global_max_age_days: 9, crawler_proxy_enabled: false, crawler_proxy_url: '', rss_proxy_enabled: false, rss_proxy_url: '',
  standalone_enabled: true, standalone_source_ids: [], standalone_max_items: 31, region_order: ['hotlist', 'rss', 'standalone'],
  regions_enabled: { hotlist: true, rss: true, standalone: true, new_items: false, ai_analysis: false }, ai_analysis_enabled: false,
  ai_analysis_max_news: 50, ai_analysis_include_rss: true, ai_analysis_include_standalone: false, ai_translation_enabled: false, ai_translation_target_language: 'English' };
const specs = [
  { name: 'filter', path: '/api/native-intel/filter/profile', search: '?profile_id=default', initial: profile, field: 'settings-filter-global-excludes', before: 'KEEP', draft: 'DRAFT_EXCLUDE', save: '保存筛选设置', retry: '重试', error: '读取筛选配置失败，请重试后再编辑。', success: '资讯筛选偏好已保存' },
  { name: 'display', path: '/api/native-intel/config', search: '', initial: config, field: 'wave3-standalone-max-items', before: '31', draft: '47', save: '保存展示与抓取设置', retry: '刷新配置', error: '读取展示与抓取配置失败，请重试后再编辑。', success: '已保存展示与抓取高级设置' },
];
async function staticServer(unexpected) {
  const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };
  const server = createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (pathname.startsWith('/api/')) { unexpected.push(`${request.method} ${pathname}`); response.writeHead(503).end(); return; }
    let target = resolve(dist, `.${decodeURIComponent(pathname)}`);
    if (!target.startsWith(dist + sep) || !existsSync(target) || !extname(target)) target = join(dist, 'index.html');
    response.setHeader('Content-Type', mime[extname(target)] || 'application/octet-stream');
    createReadStream(target).pipe(response);
  });
  await new Promise((done, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', done); });
  return server;
}
async function scenario(browser, baseURL, spec, width, evidenceDir) {
  const requests = [], writes = [], unexpected = [], external = [], errors = [], expectedFailures = [], dismissedToasts = [];
  let context, page, reads = 0, failReads = true, failWrite = true, saved = structuredClone(spec.initial);
  const prefix = `${spec.name}-${width}`;
  const shot = phase => page.screenshot({ path: join(evidenceDir, `${prefix}-${phase}.png`), fullPage: true });
  try {
    context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: 'block' });
    await context.routeWebSocket('**/*', socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), method = request.method();
      if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
      if (url.origin !== baseURL) { external.push(url.origin); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const key = `${method} ${url.pathname}${url.search}`; requests.push(key);
      if (url.pathname === spec.path && url.search === spec.search) {
        if (method === 'GET') {
          reads++;
          if (failReads) { expectedFailures.push(key); return route.fulfill({ status: 503, json: { detail: 'SYNTHETIC_READ_FAILURE' } }); }
          return route.fulfill({ json: saved });
        }
        if (method === 'PUT') {
          const body = request.postDataJSON();
          const expected = spec.name === 'filter'
            ? { name: profile.name, method: 'keyword', interests_text: '', min_score: 0.7, keyword_rules: { ...profile.keyword_rules, global_excludes: [spec.draft] }, tags: [] }
            : { ...config, standalone_max_items: Number(spec.draft) };
          // Reject every unexpected field/value; never pass a write to a real backend.
          if (JSON.stringify(Object.keys(body).sort()) !== JSON.stringify(Object.keys(expected).sort()) || Object.keys(expected).some(key => JSON.stringify(body[key]) !== JSON.stringify(expected[key]))) {
            unexpected.push(`INVALID_SYNTHETIC_BODY ${key}`); return route.fulfill({ status: 400, json: { detail: 'INVALID_SYNTHETIC_BODY' } });
          }
          writes.push(body);
          if (failWrite) { expectedFailures.push(key); return route.fulfill({ status: 503, json: { detail: 'SYNTHETIC_SAVE_FAILURE' } }); }
          saved = { ...saved, ...body }; return route.fulfill({ json: saved });
        }
      }
      // Status is inert metadata, not a credential read. No credential/probe/runtime APIs allowed.
      const allowed = ['/api/settings/platform', '/api/health', '/api/runtime-info', '/api/calendar-status', '/api/ai/credential-status', '/api/native-intel/sources', '/api/native-intel/config', '/api/native-intel/filter/profile'];
      const reply = url.pathname === '/api/calendar-status'
        ? readCalendarStatusReply(method, url.pathname, url.search, width === 390 ? 'EXPIRING' : 'SUPPORTED')
        : allowed.includes(url.pathname) ? readReply(method, url.pathname, url.search) : null;
      if (reply) return route.fulfill({ json: reply });
      unexpected.push(key); return route.fulfill({ status: 503, json: { detail: 'UNEXPECTED_SYNTHETIC_REQUEST' } });
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error' && !/^Failed to load resource: the server responded with a status of 503/.test(message.text())) errors.push(message.text()); });
    // A user can dismiss the app's existing accessible close buttons. Clear each
    // asserted error before retrying so hovering an obscured mobile Save button
    // cannot expand the toast stack and indefinitely pause its expiry timer.
    const dismissError = async message => {
      const toast = page.locator('[data-sonner-toast]').filter({ has: page.getByText(message, { exact: true }) });
      await toast.getByRole('button', { name: 'Close toast', exact: true }).click();
      await toast.waitFor({ state: 'detached' });
      dismissedToasts.push(message);
    };
    await page.goto('/settings');
    await page.getByTestId('calendar-coverage-status').getByRole('status').filter({
      hasText: `${width === 390 ? '覆盖即将到期' : '已确认范围'}：截至 2026-12-31`,
    }).waitFor();
    assert.ok(requests.includes('GET /api/calendar-status'), 'Settings reads bounded calendar metadata');
    const error = page.getByRole('alert').filter({ hasText: spec.error });
    const save = page.getByRole('button', { name: spec.save, exact: true });
    const field = page.getByTestId(spec.field);
    const gated = async () => {
      await error.waitFor(); assert.equal(await field.count(), 0);
      assert.ok(await save.count() === 0 || await save.isDisabled()); assert.equal(writes.length, 0);
    };
    await gated(); assert.equal(reads, 1);
    await dismissError('SYNTHETIC_READ_FAILURE'); await shot('initial-failure');
    await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === spec.path && response.status() === 503),
      page.getByRole('button', { name: spec.retry, exact: true }).click(),
    ]);
    await gated(); assert.equal(reads, 2);
    await dismissError('SYNTHETIC_READ_FAILURE'); await shot('retry-failure');
    failReads = false;
    await page.getByRole('button', { name: spec.retry, exact: true }).click(); await field.waitFor();
    assert.equal(await field.inputValue(), spec.before); assert.equal(await save.isEnabled(), true); assert.equal(writes.length, 0);
    await field.fill(spec.draft); await save.click();
    await page.getByText('SYNTHETIC_SAVE_FAILURE', { exact: true }).waitFor();
    assert.equal(await field.inputValue(), spec.draft); assert.equal(await save.isEnabled(), true); assert.equal(writes.length, 1);
    await dismissError('SYNTHETIC_SAVE_FAILURE');
    assert.equal(await field.inputValue(), spec.draft, 'dismissing the error cannot discard the draft');
    assert.equal(writes.length, 1, 'dismissing the error cannot retry the write');
    failWrite = false; await save.click(); await page.getByText(spec.success, { exact: true }).waitFor();
    await field.waitFor(); assert.equal(await field.inputValue(), spec.draft); assert.equal(writes.length, 2);
    await page.reload(); await field.waitFor(); assert.equal(await field.inputValue(), spec.draft);
    assert.equal(writes.length, 2, 'reopening cannot perform a write');
    assert.equal(new URL(page.url()).pathname, '/settings'); assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []); assert.deepEqual(external, []);
    assert.equal(expectedFailures.length, 3);
    assert.deepEqual(dismissedToasts, ['SYNTHETIC_READ_FAILURE', 'SYNTHETIC_READ_FAILURE', 'SYNTHETIC_SAVE_FAILURE']);
    await shot('pass');
    return { scenario: spec.name, width, status: 'PASS', reads, writes, requests, expectedFailures, dismissedToasts };
  } catch (error) {
    await shot('failure').catch(() => {});
    const failure = { scenario: spec.name, width, status: 'FAIL', error: error.message, reads, writes, requests, expectedFailures, dismissedToasts, errors, unexpected, external };
    writeFileSync(join(evidenceDir, `${prefix}-failure.json`), JSON.stringify(failure, null, 2)); return failure;
  } finally { await context?.close(); }
}
// Runtime detection is mocked at the HTTP boundary, never by executing a CLI.
// Keep this separate from settings write/recovery scenarios: every API is GET-only.
async function runtimeScenario(browser, baseURL, width, evidenceDir) {
  const requests = [], unexpected = [], external = [], errors = [], observations = [];
  const common = { runtime: 'Codex Subscription', installed: true, authenticated: false, available: false, version: 'codex-cli 0.149.0' };
  const states = [
    { name: 'timeout', payload: { ...common, status: 'probe_failed', auth_kind: 'unknown', probe_error: 'timeout' }, label: '登录状态检测未完成，请重试（现有登录不会被清除）' },
    { name: 'outer-timeout', payload: { ...common, installed: false, version: null, status: 'probe_failed', auth_kind: 'unknown', probe_error: 'timeout' }, label: '登录状态检测未完成，请重试（现有登录不会被清除）' },
    { name: 'malformed', payload: { ...common, status: 'probe_failed', auth_kind: 'unknown', probe_error: 'malformed_output' }, label: '登录状态检测未完成，请重试（现有登录不会被清除）' },
    { name: 'api-key', payload: { ...common, status: 'not_authenticated', auth_kind: 'api_key', probe_error: null }, label: '当前为 API key 登录，订阅接入需要 ChatGPT 登录' },
    { name: 'chatgpt', payload: { ...common, authenticated: true, available: false, dispatch_available: true, modelConnectivity: 'unknown', lastProbe: null, status: 'authenticated_unprobed', auth_kind: 'chatgpt', probe_error: null }, label: '已登录 · 模型连通性未验证' },
    { name: 'logged-out', payload: { ...common, status: 'not_authenticated', auth_kind: 'logged_out', probe_error: null }, label: '未连接' },
    { name: 'legacy-ready', payload: { ...common, authenticated: true, available: true, status: 'ready' }, label: '已登录 · 模型连通性未验证' },
    { name: 'legacy-logged-out', payload: { ...common, status: 'not_authenticated' }, label: '未连接' },
  ];
  let context, page, active = states[0], statusReads = 0;
  const prefix = `runtime-classification-${width}`;
  const shot = phase => page.screenshot({ path: join(evidenceDir, `${prefix}-${phase}.png`), fullPage: true });
  try {
    context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: 'block' });
    await context.routeWebSocket('**/*', socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), method = request.method();
      if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
      if (url.origin !== baseURL) { external.push(url.origin); return route.abort(); }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const key = `${method} ${url.pathname}${url.search}`; requests.push(key);
      if (method === 'GET' && url.pathname === '/api/agent-runtime/status' && !url.search) {
        statusReads++; return route.fulfill({ json: active.payload });
      }
      const allowed = ['/api/settings/platform', '/api/health', '/api/runtime-info', '/api/calendar-status', '/api/ai/credential-status', '/api/native-intel/sources', '/api/native-intel/config', '/api/native-intel/filter/profile'];
      const reply = url.pathname === '/api/calendar-status'
        ? readCalendarStatusReply(method, url.pathname, url.search, width === 390 ? 'EXPIRING' : 'SUPPORTED')
        : allowed.includes(url.pathname) ? readReply(method, url.pathname, url.search) : null;
      if (reply) return route.fulfill({ json: reply });
      unexpected.push(key); return route.fulfill({ status: 503, json: { detail: 'UNEXPECTED_SYNTHETIC_REQUEST' } });
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto('/settings');
    await page.getByTestId('calendar-coverage-status').getByRole('status').filter({
      hasText: `${width === 390 ? '覆盖即将到期' : '已确认范围'}：截至 2026-12-31`,
    }).waitFor();
    assert.ok(requests.includes('GET /api/calendar-status'), 'Settings reads bounded calendar metadata');
    await page.getByRole('heading', { name: '订阅接入', exact: true }).waitFor();
    assert.equal(statusReads, 0, 'API mode must not probe the subscription runtime');
    const runtimeLine = page.locator('span').filter({ hasText: /^Runtime：Codex Subscription · / });
    const refresh = page.getByRole('button', { name: '检查', exact: true });
    for (const [index, state] of states.entries()) {
      active = state;
      const before = statusReads;
      const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/agent-runtime/status' && r.request().method() === 'GET');
      if (index === 0) await page.getByRole('heading', { name: '订阅接入', exact: true }).click();
      else await refresh.click();
      assert.equal((await response).status(), 200);
      // Actionability waits for the async refresh to finish, including consecutive
      // timeout/malformed cases that intentionally have the same visible label.
      await refresh.click({ trial: true });
      await runtimeLine.filter({ hasText: state.label }).waitFor();
      const text = await runtimeLine.innerText();
      assert.equal(text, `Runtime：Codex Subscription · ${state.label}${state.payload.version ? ` · ${state.payload.version}` : ''}`);
      assert.equal(statusReads, before + 1, 'one explicit action must produce exactly one status read');
      if (state.payload.status === 'probe_failed') assert.doesNotMatch(text, /未连接|未登录|Runtime 未启动|已连接/);
      if (state.name === 'api-key') assert.doesNotMatch(text, /已连接/);
      assert.equal(await page.getByRole('button', { name: '连接 Codex', exact: true }).count(), state.payload.authenticated ? 0 : 1);
      assert.ok(requests.every(key => key.startsWith('GET ')), 'status display cannot trigger login, model calls, or writes');
      await shot(state.name);
      observations.push({ name: state.name, label: text, status: state.payload.status, authKind: state.payload.auth_kind ?? 'legacy-absent', probeError: state.payload.probe_error ?? null, statusReads });
    }
    assert.equal(new URL(page.url()).pathname, '/settings');
    assert.equal(await page.locator('vite-error-overlay').count(), 0);
    assert.deepEqual(unexpected, []); assert.deepEqual(external, []); assert.deepEqual(errors, []);
    return { scenario: 'runtime-classification', width, status: 'PASS', statusReads, requests, observations, boundary: 'Synthetic GET-only status; no runtime process, login, credentials, model call or writes' };
  } catch (error) {
    await shot('failure').catch(() => {});
    const failure = { scenario: 'runtime-classification', width, status: 'FAIL', error: error.message, statusReads, requests, observations, unexpected, external, errors };
    writeFileSync(join(evidenceDir, `${prefix}-failure.json`), JSON.stringify(failure, null, 2)); return failure;
  } finally { await context?.close(); }
}

async function main() {
  const evidenceDir = process.env.SETTINGS_RECOVERY_EVIDENCE_DIR || mkdtempSync(join(tmpdir(), 'vr-settings-recovery-'));
  mkdirSync(evidenceDir, { recursive: true });
  const git = arg => execFileSync('git', ['rev-parse', arg], { cwd: frontend, encoding: 'utf8' }).trim();
  const result = { checkoutHead: git('HEAD'), checkoutTree: git('HEAD^{tree}'), frontendSourceTree: git('HEAD:frontend/src'), pullRequestHead: process.env.SETTINGS_RECOVERY_PR_HEAD || null, results: [] };
  const serverUnexpected = []; let browser, server;
  try {
    assert.ok(existsSync(join(dist, 'index.html')), 'Run npm run build first');
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
    server = await staticServer(serverUnexpected); const baseURL = `http://127.0.0.1:${server.address().port}`;
    for (const width of [1440, 390]) for (const spec of specs) {
      const row = await scenario(browser, baseURL, spec, width, evidenceDir); result.results.push(row);
      console.log(`[SETTINGS-RECOVERY] ${spec.name} ${width}px ${row.status}${row.error ? `: ${row.error}` : ''}`);
    }
    for (const width of [1440, 390]) {
      const row = await runtimeScenario(browser, baseURL, width, evidenceDir); result.results.push(row);
      console.log(`[SETTINGS-RECOVERY] runtime-classification ${width}px ${row.status}${row.error ? `: ${row.error}` : ''}`);
    }
    for (const width of [1440, 390]) result.results.push(await platformScenario(browser, baseURL, width, evidenceDir));
    assert.deepEqual(serverUnexpected, []); assert.equal(result.results.length, 8);
    assert.equal(result.results.filter(row => row.status !== 'PASS').length, 0, 'all settings recovery cases must pass');
  } catch (error) { result.error = error.message; throw error; }
  finally {
    result.serverUnexpected = serverUnexpected;
    try { writeFileSync(join(evidenceDir, 'results.json'), JSON.stringify(result, null, 2)); }
    finally { try { await browser?.close(); } finally { server?.closeAllConnections(); if (server) await new Promise(done => server.close(done)); } }
  }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
