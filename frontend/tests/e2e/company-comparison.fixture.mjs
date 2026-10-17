/** Registered API goldens only. Every comparison read/write needs an explicit UI expectation. */
import { readFileSync } from 'node:fs';
import { isDeepStrictEqual } from 'node:util';
import { createExtendedPageFixture, CLOCK } from './extended-page.fixture.mjs';

const load = suffix => JSON.parse(readFileSync(new URL(`../../../backend/tests/fixtures/company_comparison/US-AAPL--HK-00700${suffix}.json`, import.meta.url), 'utf8'));
export const comparisonGoldens = { complete: load(''), missing: load('-failed-quote') };
export const comparisonHistoryGolden = JSON.parse(readFileSync(new URL('../../../backend/tests/fixtures/company_comparison/history-states.json', import.meta.url), 'utf8'));
export const comparisonEmptyGolden = JSON.parse(readFileSync(new URL('../../../backend/tests/fixtures/company_comparison/empty-bundle-lists.json', import.meta.url), 'utf8'));
export const comparisonPagedHistory = JSON.parse(readFileSync(new URL('../../../backend/tests/fixtures/company_comparison/paged-history.json', import.meta.url), 'utf8'));
export const comparisonFailures = JSON.parse(readFileSync(new URL('../../../backend/tests/fixtures/company_comparison/failure-categories.json', import.meta.url), 'utf8'));
export const comparisonLlm = comparisonGoldens.complete.request.llm;
export const comparisonCutoff = comparisonGoldens.complete.request.as_of;
export { CLOCK };
const ancillary = ['valuation', 'financials', 'reports', 'announcements', 'margin', 'block-trade', 'holders', 'dividend', 'fund-flow', 'dragon-tiger', 'lockup', 'blocks', 'hot-concepts', 'investor-qa', 'valuation/percentile', 'news', 'stock-relative-context', 'stock-valuation-context', 'market/top-risk', 'market/technical-indicators', 'research-events'];
const stockReads = new Set(['/api/watchlist', '/api/global/stock', '/api/global/hk/cashflow', ...ancillary.map(name => '/api/' + name)]);
const json = (data, status = 200) => ({ kind: 'json', status, body: { data: structuredClone(data) } });
const listPath = ref => `/api/company-comparison/bundles?market=${ref.market}&symbol=${ref.symbol}&as_of=${comparisonCutoff}`;
export const bundleListPaths = comparisonGoldens.complete.request.subjects.map(listPath);
export const generationPath = '/api/company-comparison/generate';
export const historyPath = '/api/company-comparison/runs?first_market=US&first_symbol=AAPL&second_market=HK&second_symbol=00700&as_of=' + comparisonCutoff;
export function createComparisonFixture(origin) {
  const base = createExtendedPageFixture(origin), calls = [], violations = [], expected = [];
  const deny = reason => { violations.push(reason); return { kind: 'deny', reason }; };
  const expect = (method, key, reply, body) => expected.push({ method, key, reply, body });
  return {
    base, calls, violations, expected,
    expectBundles(scenario = 'complete') {
      const g = comparisonGoldens[scenario];
      g.request.subjects.forEach((ref, i) => expect('GET', listPath(ref), json(g.bundle_lists[i])));
    },
    expectEmptyBundles() {
      for (const item of comparisonEmptyGolden.cases) expect('GET', item.url, { kind: 'json', status: item.status_code, body: structuredClone(item.response) });
    },
    expectGeneration(scenario = 'complete', delivery = 'complete') {
      const g = comparisonGoldens[scenario];
      for (const bundle of g.bundles) expect('GET', `/api/company-research/bundles/${bundle.bundle_id}`, json(bundle));
      // A truncated transport replays only the actual run_started receipt. It is not a new success contract.
      const events = delivery === 'truncated' ? g.events.slice(0, -1) : delivery === 'failed' ? comparisonHistoryGolden.failed_events : comparisonFailures.events[delivery] ?? g.events;
      if (!['complete', 'truncated', 'failed', ...Object.keys(comparisonFailures.events)].includes(delivery) || (delivery === 'failed' && scenario !== 'complete')) throw Error('Unknown delivery fault');
      expect('POST', generationPath, { kind: 'stream', body: events.map(e => JSON.stringify(e)).join('\n') + '\n' }, g.request);
    },
    expectEvidence(index = 0, scenario = 'complete') {
      const bundle = comparisonGoldens[scenario].bundles[index];
      expect('GET', `/api/company-research/bundles/${bundle.bundle_id}`, json(bundle));
    },
    expectHistory(scenario = 'complete') {
      const g = comparisonGoldens[scenario];
      expect('GET', historyPath, json({records:g.history ?? [g.record],next_cursor:null}));
    },
    expectHistoryPage(index = 0) {
      const before = index === 0 ? '' : '&before=' + comparisonPagedHistory.pages[index - 1].data.next_cursor;
      expect('GET', historyPath + before, { kind: 'json', status: 200, body: structuredClone(comparisonPagedHistory.pages[index]) });
    },
    expectHistoryState(state) {
      const envelope = comparisonHistoryGolden[state + '_history'];
      if (!envelope) throw Error('Unknown history state');
      expect('GET', historyPath, { kind: 'json', status: 200, body: {data:{records:structuredClone(envelope.data),next_cursor:null}} });
    },
    handle(rawUrl, method = 'GET', body) {
      let u;
      try { u = new URL(rawUrl); } catch { return deny('malformed URL'); }
      const call = { method, path: u.pathname, search: u.search, ...(body === undefined ? {} : { body: structuredClone(body) }) };
      calls.push(call);
      if (u.origin !== origin || u.username || u.password || u.hash) return deny('foreign origin or noncanonical URL');
      const key = u.pathname + u.search;
      if (u.pathname.startsWith('/api/company-comparison/') || u.pathname.startsWith('/api/company-research/')) {
        const index = expected.findIndex(item => item.method === method && item.key === key);
        const wanted = expected[index];
        if (!wanted || !isDeepStrictEqual(body, wanted.body)) return deny(`unexpected comparison method/query/body ${method} ${key}`);
        if (method === 'POST' && expected.some(item => item.method === 'GET' && item.key.startsWith('/api/company-research/bundles/'))) return deny('generation before frozen bundle readback');
        expected.splice(index, 1);
        return structuredClone(wanted.reply);
      }
      if (method !== 'GET' || body !== undefined) return deny(`unplanned write ${method} ${key}`);
      // Reuse the full-page stock responses, but do not inherit unrelated DailyReview or archive permissions.
      if (u.pathname.startsWith('/api/') && !stockReads.has(u.pathname)) return deny(`unlisted StockData API ${key}`);
      if (u.pathname === '/debate') return u.search === '?code=600000' ? { kind: 'static' } : deny('debate identity/query');
      const reply = base.handle(rawUrl, method, body);
      if (reply.kind === 'deny') return deny(`StockData allowlist ${method} ${key}`);
      if (reply.kind === 'static' && !['/stock-data', '/index.html', '/favicon.svg'].includes(u.pathname) && !/^\/assets\/[A-Za-z0-9_.-]+\.(?:js|css|woff2|svg|png)$/.test(u.pathname)) return deny('unlisted static document');
      return reply;
    },
  };
}
