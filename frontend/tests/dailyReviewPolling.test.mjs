import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

// Execute actual production callbacks with a controlled clock and deferred requests.
// This is not a React mount or a browser/backend integration test.
const source = readFileSync(new URL('../src/pages/DailyReview.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('DailyReview.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ['clearPoll', 'applyDailyReviewPayload', 'startStalePoll', 'loadDailyReview', 'refreshDailyReview'];
const declarations = new Map();
function visit(node) {
  if (ts.isVariableDeclaration(node) && names.includes(node.name.getText(ast))) declarations.set(node.name.getText(ast), `const ${node.getText(ast)};`);
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(declarations.size, names.length);
const js = ts.transpileModule(names.map(n => declarations.get(n)).join('\n') + '\n exports.callbacks = {clearPoll, startStalePoll, loadDailyReview, refreshDailyReview};', {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
function harness() {
  let done = false;
  let now = 0, note = 'old result', data = { id: 'old' }, timerId = 0;
  const timers = new Map(), calls = [], exports = {};
  const mountedRef = { current: true };
  const request = method => new Promise((resolve, reject) => calls.push({ method, resolve, reject }));
  vm.runInNewContext(js, {
    exports, Date: { now: () => now }, ApiError: Error,
    useCallback: fn => fn, mountedRef,
    pollTimerRef: { current: null }, pollDeadlineRef: { current: 0 }, pollGenerationRef: { current: 0 },
    drRefreshingRef: { current: false }, dailyRequestRef: { current: 0 },
    setInterval: fn => { timers.set(++timerId, fn); return timerId; }, clearInterval: id => timers.delete(id),
    setStaleRefreshNote: value => { note = typeof value === 'function' ? value(note) : value; },
    setDr: value => { data = typeof value === 'function' ? value(data) : value; },
    setDrDone: value => { done = value; }, setCacheMeta: () => {}, setDrErr: () => {}, setDrRefreshing: () => {},
    api: { dailyReview: () => request('GET'), dailyReviewRefresh: () => request('POST') },
  });
  return { ...exports.callbacks, calls, mountedRef, get done() { return done; }, get note() { return note; }, get data() { return data; }, get timers() { return timers.size; },
    tick(ms) { now = ms; for (const fn of [...timers.values()]) void fn(); },
    async flush() { await new Promise(resolve => setImmediate(resolve)); },
  };
}
const reply = (id, meta = { stale: false }) => ({ data: { id }, cache_meta: meta });
test('119s completion is applied and polling stops', async () => {
  const h = harness(); h.startStalePoll(); h.tick(118000); h.tick(119000);
  h.calls[0].resolve(reply('fresh')); await h.flush();
  assert.equal(h.data.id, 'fresh'); assert.equal(h.note, null); assert.equal(h.timers, 0);
});
test('deadline stops waiting without claiming backend failure; 121s late response is ignored', async () => {
  const h = harness(); h.startStalePoll(); h.tick(118000); h.tick(120000);
  assert.equal(h.timers, 0); assert.match(h.note, /停止等待.*后台可能仍在刷新/);
  h.tick(121000); h.calls[0].resolve(reply('late')); await h.flush();
  assert.equal(h.data.id, 'old'); assert.equal(h.calls.length, 1);
});
test('slow polls do not overlap and read errors do not claim refresh failure', async () => {
  const h = harness(); h.startStalePoll(); h.tick(2000); h.tick(4000);
  assert.equal(h.calls.length, 1);
  h.calls[0].reject(new Error('network')); await h.flush();
  assert.match(h.note, /读取刷新状态失败/); assert.equal(h.data.id, 'old');
  h.tick(6000); h.calls[1].resolve(reply('old', { stale: true, refresh_failed: true, refresh_error: 'confirmed failure' })); await h.flush();
  assert.match(h.note, /confirmed failure/); assert.equal(h.timers, 0);
});
test('manual refresh invalidates earlier poll results', async () => {
  const h = harness(); h.startStalePoll(); h.tick(2000); h.refreshDailyReview();
  assert.equal(h.calls[1].method, 'POST'); h.calls[1].resolve(reply('manual')); await h.flush();
  h.calls[0].resolve(reply('outdated', { stale: true, refreshing: true })); await h.flush();
  assert.equal(h.data.id, 'manual'); assert.equal(h.note, null); assert.equal(h.timers, 0);
});
test('cancelled poll errors cannot replace a newer result or restarted poll state', async () => {
  const h = harness(); h.startStalePoll(); h.tick(2000); h.clearPoll(); h.startStalePoll();
  h.calls[0].reject(new Error('late')); await h.flush();
  assert.equal(h.note, 'old result'); assert.equal(h.timers, 1);
});
test('unmount ignores in-flight results and clears timers', async () => {
  const h = harness(); h.startStalePoll(); h.tick(2000); h.mountedRef.current = false; h.clearPoll();
  h.calls[0].resolve(reply('late')); await h.flush(); assert.equal(h.data.id, 'old'); assert.equal(h.timers, 0);
});

test('initial cold successful GET never enters background polling; stale GET does', async () => {
  const cold = harness(); cold.loadDailyReview(); cold.calls[0].resolve(reply('cold')); await cold.flush();
  assert.equal(cold.data.id, 'cold'); assert.equal(cold.timers, 0); assert.equal(cold.done, true);
  const stale = harness(); stale.loadDailyReview(); stale.calls[0].resolve(reply('cached', { stale: true, refreshing: true })); await stale.flush();
  assert.equal(stale.timers, 1); assert.equal(stale.done, true); stale.tick(2000);
  stale.calls[1].resolve(reply('cached', { stale: true, refreshing: true })); await stale.flush();
  assert.equal(stale.timers, 1); assert.match(stale.note, /后台正在刷新/);
  stale.clearPoll();
});

for (const outcome of ['resolve', 'reject']) test(`initial GET ${outcome} cannot overwrite a subsequent manual refresh`, async () => {
  const h = harness(); h.loadDailyReview(); h.refreshDailyReview();
  h.calls[1].resolve(reply('manual')); await h.flush();
  if (outcome === 'resolve') h.calls[0].resolve(reply('old', { stale: true, refreshing: true }));
  else h.calls[0].reject(new Error('late error'));
  await h.flush(); assert.equal(h.data.id, 'manual'); assert.equal(h.note, null);
  assert.equal(h.timers, 0); assert.equal(h.done, true);
});
for (const method of ['loadDailyReview', 'refreshDailyReview']) test(`${method} ignores a response after unmount`, async () => {
  const h = harness(); h[method](); h.mountedRef.current = false; h.clearPoll();
  h.calls[0].resolve(reply('unmounted', { stale: true, refreshing: true })); await h.flush();
  assert.equal(h.data.id, 'old'); assert.equal(h.timers, 0); assert.equal(h.done, false);
});
