// Imported only by the existing Intel recovery CI entry. Synthetic GET-only data.
import assert from 'node:assert/strict';
import { join } from 'node:path';

export function rssCoverageFixture(mode) {
  assert.ok(['partial', 'unavailable', 'empty'].includes(mode));
  const requests = [], unexpected = [];
  const failed = mode === 'unavailable' ? 2 : mode === 'partial' ? 1 : 0;
  const items = mode === 'partial' ? [{ title: 'SYNTHETIC_RETAINED_RSS', source: 'SYNTHETIC_SOURCE', url: 'https://synthetic.invalid/rss', time: '10-11 10:00', published_at: '2026-10-11T10:00:00Z' }] : [];
  // Backend industry.total counts configured sources, independently of articles.
  const radar = { status: mode === 'empty' ? 'normal' : mode, generated_at: '2026-10-11T10:00:00Z', recent_days: 7,
    stats: { industries: 2, total_sources: 2, failed_sources: failed },
    source_coverage: { scope: 'cached_fetch_all_configured_sources', state: mode === 'empty' ? 'normal' : mode, expected_sources: 2, attempted_sources: 2, succeeded_sources: 2 - failed, failed_sources: failed },
    industries: [{ key: 'ai', name: 'SYNTHETIC_LIVE_TRACK', accent: '#f97316', total: 2, items }, { key: 'saved', name: 'SYNTHETIC_SAVED_TRACK', accent: '#f97316', total: 0, items: [] }],
  };
  return { requests, unexpected, radar,
    reply(method, path, search = '') {
      const key = `${method} ${path}${search}`; requests.push(key);
      if (method === 'GET') {
        if (path === '/api/radar' && !search) return { status: 200, json: { data: radar } };
        if (path === '/api/native-intel/status' && !search) return { status: 200, json: { status: 'normal', sources: { total: 2, healthy: 2, failing: 0, failing_names: [] }, store: { readable: true, item_count: 0 } } };
        if (path === '/api/native-intel/items' && search === '?limit=40&order_by=last_seen') return { status: 200, json: { status: 'normal', items: [], total: 0 } };
        if (path === '/api/native-intel/trending' && search === '?window_hours=24&top_n=20') return { status: 200, json: { status: 'normal', entities: [] } };
        if (path === '/api/intel-digests/latest' && ['?sector_key=ai', '?sector_key=saved'].includes(search)) return { status: 200, json: { digest: search.endsWith('saved') ? { summary_text: 'SYNTHETIC_SAVED_SUMMARY_STILL_READABLE', digest_date: '2026-10-10' } : null } };
      }
      unexpected.push(key); return { status: 503, json: { detail: 'UNEXPECTED_SYNTHETIC_REQUEST' } };
    },
  };
}

export async function runRssCoverageScenario(browser, baseURL, width, mode, evidenceDir) {
  const fixture = rssCoverageFixture(mode), errors = [], external = [];
  const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: 'block' });
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await context.routeWebSocket('**/*', socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== baseURL) {
      if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
      external.push(url.origin); return route.abort();
    }
    if (url.pathname.startsWith('/api/')) return route.fulfill(fixture.reply(request.method(), url.pathname, url.search));
    return route.continue();
  });
  const screenshot = phase => page.screenshot({ path: join(evidenceDir, `rss-${mode}-${width}-${phase}.png`), fullPage: true });
  try {
    await page.goto('/intel');
    const panel = page.getByTestId('market-intel-panel');
    await panel.waitFor();
    const generate = panel.getByRole('button', { name: '让 AI 提炼今日要点', exact: true });
    await generate.waitFor();
    const bulk = panel.getByRole('button', { name: '提炼全部赛道', exact: true });
    await bulk.waitFor();
    const notice = mode === 'partial' ? '赛道来源部分可用：1/2 个来源成功；结果不完整。' : '赛道来源全部未取得可用响应，不能把空列表当成没有资讯。';
    if (mode !== 'empty') await panel.getByRole('alert').getByText(notice, { exact: true }).waitFor();
    else {
      await panel.getByText('NORMAL · 可用', { exact: true }).waitFor();
      assert.doesNotMatch(await panel.innerText(), /赛道来源部分可用|全部未取得可用响应|赛道来源覆盖未知/);
    }
    assert.equal(await generate.isDisabled(), mode === 'unavailable');
    assert.equal(await bulk.isDisabled(), mode === 'unavailable');
    const track = panel.getByRole('button', { name: new RegExp(`^SYNTHETIC_LIVE_TRACK\\s*${mode === 'partial' ? 1 : 0}$`) });
    await track.waitFor();
    await screenshot('live-track');
    // Read saved history with source coverage unavailable; no generation/save action.
    await panel.getByRole('button', { name: /^SYNTHETIC_SAVED_TRACK\s*0$/ }).click();
    await panel.getByText('SYNTHETIC_SAVED_SUMMARY_STILL_READABLE', { exact: true }).waitFor();
    await panel.getByText('已保存', { exact: true }).waitFor();
    const regenerate = panel.getByRole('button', { name: '重新提炼', exact: true });
    assert.equal(await regenerate.isDisabled(), mode === 'unavailable');
    await screenshot('saved-summary');
    if (mode === 'unavailable') {
      // A browser DOM click on an actually disabled button does not dispatch a
      // generation event. Prove all three disabled entry points stay inert.
      await bulk.evaluate(button => button.click());
      await regenerate.evaluate(button => button.click());
      await track.click(); await generate.waitFor();
      await generate.evaluate(button => button.click());
      assert.equal(await generate.isDisabled(), true);
    }
    assert.ok(fixture.requests.every(key => key.startsWith('GET ')), 'zero model, save or refresh writes');
    assert.deepEqual(fixture.unexpected, []); assert.deepEqual(external, []); assert.deepEqual(errors, []);
    assert.equal(new URL(page.url()).pathname, '/intel');
    await screenshot('pass');
    return { scenario: `rss-${mode}`, width, status: 'PASS', sourceCoverage: fixture.radar.source_coverage, requests: fixture.requests, generationDisabled: mode === 'unavailable', savedSummaryReadable: true };
  } catch (error) {
    await screenshot('failure').catch(() => {});
    throw new Error(`RSS ${mode} ${width}px: ${error.message}; ${JSON.stringify({ requests: fixture.requests, unexpected: fixture.unexpected, external, errors })}`, { cause: error });
  } finally { await context.close(); }
}
