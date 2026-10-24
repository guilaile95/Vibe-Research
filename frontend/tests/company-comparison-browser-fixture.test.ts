import { installCredentialFixture, withCredentialStatus } from './credentialTransportFixture.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { isDeepStrictEqual } from 'node:util';
import { comparisonRefs, generateComparison, parseComparisonRecord, readComparisonBundle, readComparisonBundles, readComparisonRunPage } from '../src/lib/companyComparison.ts';
import { parseResearchBundle } from '../src/lib/companyResearch.ts';
import { createComparisonFixture, comparisonGoldens, comparisonHistoryGolden, comparisonEmptyGolden, comparisonLlm, comparisonCutoff, bundleListPaths, generationPath, historyPath } from './e2e/company-comparison.fixture.mjs';
const origin = 'http://127.0.0.1:8911';
const signal = () => new AbortController().signal;
const storedComparisonLlm = { ...comparisonLlm, revision: '1' };
function mockApi(t: any, fixture: any) {
  installCredentialFixture(t, storedComparisonLlm);
  t.mock.method(globalThis, 'fetch', withCredentialStatus(async (url: string | URL, init?: RequestInit) => {
    const body = init?.body === undefined ? undefined : JSON.parse(String(init.body));
    const response = fixture.handle(new URL(String(url), origin).href, init?.method || 'GET', body);
    assert.notEqual(response.kind, 'deny', JSON.stringify(fixture.violations));
    assert.notEqual(response.kind, 'static', 'parser tests may read fixture APIs only');
    return new Response(response.kind === 'stream' ? response.body : JSON.stringify(response.body), { status: response.status || 200 });
  }));
}
test('actual empty-store registered selectors pass production parser without enabling generation', async t => {
  const f = createComparisonFixture(origin); mockApi(t, f); f.expectEmptyBundles();
  assert.equal(comparisonEmptyGolden.fixture_only, true);
  for (const item of comparisonEmptyGolden.cases) {
    assert.ok(bundleListPaths.includes(item.url)); assert.equal(item.status_code, 200);
    const { market, symbol, as_of } = item.query;
    assert.deepEqual(await readComparisonBundles({ market, symbol }, as_of, signal()), item.response.data);
    assert.deepEqual(item.response.data, []);
  }
  assert.deepEqual(f.expected, []); assert.deepEqual(f.violations, []);
  assert.equal(f.calls.some((call: any) => call.method !== 'GET'), false);
});
for (const scenario of ['complete', 'missing']) test(`actual registered ${scenario} golden through every production browser parser`, async t => {
  const g = comparisonGoldens[scenario], f = createComparisonFixture(origin);
  assert.equal(g.fixture_only, true); assert.deepEqual(g.request.llm, comparisonLlm);
  assert.ok(comparisonLlm.apiKey, 'loadLlm requires a nonempty synthetic credential');
  assert.equal(new URL(comparisonLlm.baseURL).hostname, 'fixture.example');
  assert.equal(new Set(g.request.subjects.map((s: any) => s.bundle_id)).size, 2);
  for (const b of g.bundles) assert.deepEqual(parseResearchBundle(b, b.subject, comparisonCutoff), b);
  assert.deepEqual(comparisonRefs(g.bundles), g.request.subjects);
  assert.deepEqual(parseComparisonRecord(g.record), g.record);
  mockApi(t, f); f.expectBundles(scenario);
  const lists = await Promise.all(g.request.subjects.map(({ market, symbol }: any) => readComparisonBundles({ market, symbol }, comparisonCutoff, signal())));
  assert.deepEqual(lists, g.bundle_lists); assert.deepEqual(f.expected, []);
  f.expectGeneration(scenario);
  const bundles = await Promise.all(lists.map((list: any) => readComparisonBundle(list[0], signal())));
  const result = await generateComparison(bundles, comparisonCutoff, storedComparisonLlm, signal());
  assert.deepEqual(result, g.record); assert.deepEqual(f.expected, []);
  f.expectHistory(scenario); assert.deepEqual((await readComparisonRunPage({market:'US',symbol:'AAPL'},{market:'HK',symbol:'00700'},comparisonCutoff,signal())).records, [g.record]);
  assert.deepEqual(f.expected, []); assert.deepEqual(f.violations, []);
  assert.equal(f.calls.filter((call: any) => call.method === 'POST').length, 1);
  for (let i = 0; i < result.evidence.length; i++) for (let j = 0; j < result.evidence[i].sources.length; j++) {
    const source = result.evidence[i].sources[j], frozen = bundles[i].sources[j];
    assert.equal(source.status, frozen.status); assert.equal(source.payload_sha256, frozen.payload_sha256);
    assert.equal(source.fixture, frozen.payload?.block?.fixture === true);
  }
  if (scenario === 'missing') assert.equal(result.evidence[0].sources.find((s: any) => s.evidence_id === 'global_quote_ref')?.status, 'ERROR');
});
for (const state of ['running', 'cancelled', 'failed']) test(`actual ${state} history retains terminal distinction and no output`, async t => {
  const f = createComparisonFixture(origin); mockApi(t, f); f.expectHistoryState(state);
  const records = (await readComparisonRunPage({market:'US',symbol:'AAPL'},{market:'HK',symbol:'00700'},comparisonCutoff,signal())).records;
  assert.deepEqual(records, comparisonHistoryGolden[state + '_history'].data);
  assert.ok(records.every(record => record.output === null && record.status !== 'COMPLETED'));
  assert.deepEqual(f.expected, []); assert.deepEqual(f.violations, []);
});
for (const delivery of ['truncated', 'failed']) test(`actual stream ${delivery} never becomes a complete report`, async t => {
  const f = createComparisonFixture(origin); mockApi(t, f); f.expectGeneration('complete', delivery);
  const g = comparisonGoldens.complete;
  const bundles = await Promise.all(g.bundle_lists.map((list: any) => readComparisonBundle(list[0], signal())));
  await assert.rejects(generateComparison(bundles, comparisonCutoff, storedComparisonLlm, signal()), delivery === 'truncated' ? /未收到完整报告/ : /对比未完成/);
  assert.equal(f.calls.filter((c: any) => c.method === 'POST').length, 1); assert.deepEqual(f.expected, []);
});
test('manual list, readback, history and generate all fail closed without a corresponding click', () => {
  const g = comparisonGoldens.complete;
  for (const [method, url, body] of [
    ['GET', bundleListPaths[0], undefined], ['GET', `/api/company-research/bundles/${g.bundles[0].bundle_id}`, undefined],
    ['GET', historyPath, undefined], ['POST', generationPath, g.request],
    ['POST', '/api/company-research/capture', { market: 'US', symbol: 'AAPL', as_of: comparisonCutoff, confirm_public_fetch: true }],
    ['POST', '/api/company-research/generate', {}], ['POST', '/api/debate', { code: '600000' }], ['POST', '/api/chat', {}],
  ] as const) {
    const f = createComparisonFixture(origin); assert.equal(f.handle(origin + url, method, body).kind, 'deny'); assert.equal(f.violations.length, 1);
  }
});
for (const suffix of ['&live=1', '&symbol=AAPL', '&as_of=2026-09-30', '#hash']) test('extra or duplicate comparison selectors rejected ' + suffix, () => {
  const f = createComparisonFixture(origin); f.expectBundles(); const count = f.expected.length;
  assert.equal(f.handle(origin + bundleListPaths[0] + suffix).kind, 'deny'); assert.equal(f.expected.length, count);
});
for (const change of [
  (p: string) => p.replace('2026-09-30', '2026-09-29'), (p: string) => p.replace('AAPL', 'MSFT'),
  (p: string) => p.replace('market=US', 'market=HK'), (p: string) => p.replace('market=US&symbol=AAPL', 'symbol=AAPL&market=US'),
]) test('comparison list binds exact market/code/day and query ordering', () => {
  const f = createComparisonFixture(origin); f.expectBundles();
  assert.equal(f.handle(origin + change(bundleListPaths[0])).kind, 'deny'); assert.equal(f.expected.length, 2);
});
for (const method of ['POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS']) test('comparison GET rejects ' + method, () => {
  const f = createComparisonFixture(origin); f.expectBundles(); assert.equal(f.handle(origin + bundleListPaths[0], method).kind, 'deny');
});
for (const badOrigin of ['https://fixture.example', 'http://localhost:8911', 'http://127.0.0.1:8912', 'http://user@127.0.0.1:8911']) test('reject origin or authority ' + badOrigin, () => {
  const f = createComparisonFixture(origin); f.expectBundles(); assert.equal(f.handle(badOrigin + bundleListPaths[0]).kind, 'deny');
});
for (const mutation of ['subject', 'hash', 'cutoff', 'budget', 'provider', 'key', 'extra']) test('generation payload rejects changed ' + mutation, () => {
  const f = createComparisonFixture(origin), g = comparisonGoldens.complete; f.expectGeneration();
  for (const b of g.bundles) assert.equal(f.handle(origin + `/api/company-research/bundles/${b.bundle_id}`).kind, 'json');
  const savedRequest = { ...g.request, llm: { ...g.request.llm, revision: '1' } };
  const body = structuredClone(savedRequest);
  if (mutation === 'subject') body.subjects[0].symbol = 'MSFT';
  if (mutation === 'hash') body.subjects[0].expected_bundle_sha256 = '0'.repeat(64);
  if (mutation === 'cutoff') body.as_of = '2026-09-29';
  if (mutation === 'budget') body.confirm_model_calls = false;
  if (mutation === 'provider') body.llm.provider = 'cli-codex';
  if (mutation === 'key') body.llm.apiKey = 'unexpected';
  if (mutation === 'extra') body.retry = true;
  assert.equal(f.handle(origin + generationPath, 'POST', body).kind, 'deny'); assert.equal(f.expected.length, 1);
  assert.equal(f.handle(origin + generationPath, 'POST', savedRequest).kind, 'stream'); assert.deepEqual(f.expected, []);
  assert.equal(f.handle(origin + generationPath, 'POST', g.request).kind, 'deny', 'a confirmed budget cannot authorize retry');
});
test('generation cannot skip selected frozen bundle identity/version readback', () => {
  const f = createComparisonFixture(origin); f.expectGeneration();
  assert.equal(f.handle(origin + generationPath, 'POST', comparisonGoldens.complete.request).kind, 'deny'); assert.equal(f.expected.length, 3);
});
for (const [method, url] of [
  ['GET', '/stock-data?code=MSFT'], ['GET', '/stock-data?code=AAPL&live=1'], ['POST', '/stock-data?code=AAPL'],
  ['GET', '/debate?code=600001'], ['GET', '/debate?code=600000&code=600000'], ['GET', '/assets/test.js?live=1'],
  ['GET', '/daily-review'], ['GET', '/api/public-research/company-inputs?as_of=2026-09-30&market=US&symbol=AAPL'],
  ['GET', '/api/global/stock?symbol=MSFT'], ['GET', '/api/global/stock?symbol=AAPL&live=1'],
  ['GET', '/api/research-events?security_code=600001'], ['GET', '/api/market/top-risk?code=600000&days=121'],
  ['GET', '/api/watchlist?live=1'], ['POST', '/api/watchlist'],
]) test(`mounted-page exact deny ${method} ${url}`, () => {
  const f = createComparisonFixture(origin); assert.equal(f.handle(origin + url, method).kind, 'deny');
});
test('only three selected-stock identities and one canonical Debate handoff are permitted', () => {
  const f = createComparisonFixture(origin);
  for (const path of ['/stock-data?code=AAPL', '/stock-data?code=00700', '/stock-data?code=600000', '/debate?code=600000', '/assets/application.js']) assert.equal(f.handle(origin + path).kind, 'static');
  assert.deepEqual(f.violations, []);
});
test('CI harness uses real built pages, reports failed evidence and never launches locally', () => {
  const source = readFileSync(new URL('./e2e/company-comparison.browser.mjs', import.meta.url), 'utf8');
  assert.ok(source.indexOf("process.env.CI !== 'true'") < source.indexOf('chromium.launch('));
  assert.match(source, /\[1440, 390\]/); assert.match(source, /routeWebSocket/); assert.match(source, /serviceWorkers: 'block'/);
  assert.match(source, /captureBrowserFailure/); assert.match(source, /requests: fixture.calls/); assert.match(source, /'results.json'/);
  assert.match(source, /confirmClick = accept => observedBrowserAction\(async/);
  assert.match(source, /bounds\.x >= -1 && bounds\.x \+ bounds\.width <= width \+ 1/);
  assert.match(source, /\$\{name\}-card\.png/); assert.match(source, /height: Math\.min\(innerHeight, b\.bottom, main\.bottom\) - y/);
  assert.doesNotMatch(source, /vite.*adapter|\.route\([^\n]*company-comparison/);
  assert.equal(isDeepStrictEqual(comparisonHistoryGolden.request, comparisonGoldens.complete.request), true);
});

test('capture retains real viewport evidence and measures complete tall-content coverage', () => {
  const source = readFileSync(new URL('./e2e/company-comparison.browser.mjs', import.meta.url), 'utf8');
  assert.match(source, /fullPage: false/);
  assert.match(source, /name}-card\.png/);
  assert.match(source, /name}\.html/);
  assert.match(source, /name}-full-element\.png/);
  assert.match(source, /name}-tile-/);
  assert.match(source, /tile\.start <= covered \+ 1/);
  assert.match(source, /covered >= tile\.total - 1/);
  assert.match(source, /scroll must advance full-content coverage/);
  assert.match(source, /main\.scrollBy/);
  assert.match(source, /nav-drawer-trigger/);
  assert.match(source, /titleHitDrawer/);
  assert.match(source, /framing, bounds, clip, tiles, fullElementError/);
  const pending = source.indexOf('await chooseBundles(); await hold(); await begin(); await held();');
  const active = source.indexOf("await shot(card(), 'active-generation-cancel-available');");
  const cancel = source.indexOf('await cancel.click();');
  assert.ok(pending >= 0 && active > pending && cancel > active);
  assert.match(source, /cancel\.isEnabled\(\)/);
  assert.doesNotMatch(source, /setViewportSize|addStyleTag|\.style\.(?:height|overflow|position)\s*=/);
});

test('browser frozen drilldown fixture is an explicit read of exact registered evidence',async t=>{
 const {readComparisonEvidence}=await import('../src/lib/companyComparison.ts');
 const g=comparisonGoldens.complete,f=createComparisonFixture(origin);mockApi(t,f);
 f.expectEvidence(0);
 const source=g.record.output.subjects[0].citations[0].evidence_id;
 assert.deepEqual(await readComparisonEvidence(g.record,0,source,signal()),g.bundles[0]);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].method,'GET');assert.deepEqual(f.expected,[]);assert.deepEqual(f.violations,[]);
});

test('actual paged-history goldens exclude 51 newer foreign runs, advance cursor and restart latest',async t=>{
 const {comparisonPagedHistory}=await import('./e2e/company-comparison.fixture.mjs');
 const f=createComparisonFixture(origin);mockApi(t,f);
 assert.equal(comparisonPagedHistory.newer_other_pair_count,51);
 let before: string | undefined;const ids=new Set<string>();
 for(let index=0;index<2;index++){
  f.expectHistoryPage(index);
  const page=await readComparisonRunPage({market:'US',symbol:'AAPL'},{market:'HK',symbol:'00700'},comparisonCutoff,signal(),before);
  assert.deepEqual(page,comparisonPagedHistory.pages[index].data);
  assert.equal(page.records.length,index===0?50:1);
  for(const record of page.records){assert.ok(!ids.has(record.run_id));ids.add(record.run_id);}
  before=page.next_cursor??undefined;
 }
 assert.equal(ids.size,51);assert.equal(before,undefined);
 f.expectHistoryPage(0);
 const restarted=await readComparisonRunPage({market:'US',symbol:'AAPL'},{market:'HK',symbol:'00700'},comparisonCutoff,signal());
 assert.deepEqual(restarted,comparisonPagedHistory.pages[0].data);assert.deepEqual(f.expected,[]);assert.deepEqual(f.violations,[]);
});
for(const category of ['TIMEOUT','UPSTREAM','OUTPUT_INVALID','PERSISTENCE'])test(`actual safe ${category} browser fixture retains run identity and never retries`,async t=>{
 const {comparisonFailures}=await import('./e2e/company-comparison.fixture.mjs');
 const f=createComparisonFixture(origin);mockApi(t,f);f.expectGeneration('complete',category);
 const g=comparisonGoldens.complete;
 const bundles=await Promise.all(g.bundle_lists.map((list:any)=>readComparisonBundle(list[0],signal())));
 await assert.rejects(generateComparison(bundles,comparisonCutoff,storedComparisonLlm,signal()),e=>{
  assert.match(String(e),new RegExp(category));assert.ok(String(e).includes(comparisonFailures.events[category][0].run_id));
  assert.match(String(e),/可能已产生模型费用/);assert.doesNotMatch(String(e),/private/);return true;
 });
 assert.equal(f.calls.filter((c:any)=>c.method==='POST').length,1);assert.deepEqual(f.expected,[]);assert.deepEqual(f.violations,[]);
});
