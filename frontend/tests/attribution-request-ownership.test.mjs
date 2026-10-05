import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/pages/PerformanceAttribution.tsx', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const startIndex = source.indexOf('  useEffect(() => {\n    mountedRef.current = true;');
assert.notEqual(startIndex, -1, 'Missing attribution ownership effect');
const endIndex = source.indexOf('  const positions:', startIndex);
assert.notEqual(endIndex, -1, 'Missing attribution render boundary');
const body = source.slice(startIndex, endIndex);
const tick = () => new Promise((resolve) => setImmediate(resolve));
function harness() {
  const state = {}, calls = [], notifications = [], effects = [];
  const scope = {
    dateFrom: '2026-07-01', dateTo: '2026-07-31',
    mountedRef: { current: true }, viewRequestRef: { current: 0 }, snapshotListRequestRef: { current: 0 }, freezeInFlightRef: { current: false },
    useCallback: (fn) => fn, useEffect: (effect) => effects.push(effect),
    toast: { success: (message) => notifications.push(['success', message]), error: (message) => notifications.push(['error', message]) },
    api: new Proxy({}, { get: (_, kind) => (params) => new Promise((resolve, reject) => calls.push({ kind, params, resolve, reject })) }),
  };
  for (const key of ['Loading', 'Error', 'Result', 'ViewingSnapshotId', 'Snapshots', 'SnapshotListError', 'Freezing', 'Notice', 'FreezeError', 'SnapshotsOpen']) scope['set' + key] = (value) => { state[key] = value; };
  scope.setDateFrom = (value) => { scope.dateFrom = value; };
  scope.setDateTo = (value) => { scope.dateTo = value; };
  vm.runInNewContext(ts.transpileModule(body + ';globalThis.actions={fetchAttribution,handleOpenSnapshot,handleFreeze,loadSnapshots,changeDate};', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, scope);
  const unmount = effects[0]();
  return { state, calls, notifications, scope, unmount, ...scope.actions };
}
const snapshot = (id) => ({ snapshot: { payload: { marker: id } }, positions: [] });
const frozen = (id = 'frozen-A') => ({ snapshot: { snapshot_id: id, as_of_date: '2026-07-31' }, attribution: { marker: id } });

test('late live response cannot appear under a newer historical snapshot label', async () => {
  const h = harness(); const a = h.fetchAttribution(); const b = h.handleOpenSnapshot('B');
  h.calls[1].resolve(snapshot('B')); await b; h.calls[0].resolve({ marker: 'A' }); await a;
  assert.equal(h.state.Result.marker, 'B'); assert.equal(h.state.ViewingSnapshotId, 'B');
});
test('late snapshot A cannot replace user-selected snapshot B', async () => {
  const h = harness(); const a = h.handleOpenSnapshot('A'); const b = h.handleOpenSnapshot('B');
  h.calls[1].resolve(snapshot('B')); await b; h.calls[0].resolve(snapshot('A')); await a;
  assert.equal(h.state.Result.marker, 'B'); assert.equal(h.state.ViewingSnapshotId, 'B');
});
test('return to live calculation rejects an older snapshot response', async () => {
  const h = harness(); const a = h.handleOpenSnapshot('A'); const b = h.fetchAttribution();
  h.calls[1].resolve({ marker: 'LIVE' }); await b; h.calls[0].resolve(snapshot('A')); await a;
  assert.equal(h.state.Result.marker, 'LIVE'); assert.equal(h.state.ViewingSnapshotId, null);
});
for (const fail of [false, true]) test(`obsolete ${fail ? 'error' : 'success'} and finalizer cannot stop a newer loading state`, async () => {
  const h = harness(); const a = h.fetchAttribution(); const b = h.handleOpenSnapshot('B');
  if (fail) h.calls[0].reject(new Error('STALE')); else h.calls[0].resolve({ marker: 'STALE' });
  await a; assert.equal(h.state.Loading, true); assert.equal(h.state.Error, null); assert.equal(h.state.Result, null);
  h.calls[1].resolve(snapshot('B')); await b; assert.equal(h.state.Loading, false);
});
test('date input invalidates before the next fetch effect, and new request uses the new date', async () => {
  const h = harness(); const a = h.fetchAttribution(); h.changeDate('from', '2026-07-15');
  h.calls[0].resolve({ marker: 'OLD' }); await a; assert.equal(h.state.Result, null); assert.equal(h.state.Loading, true);
  const b = h.fetchAttribution(); assert.equal(h.calls[1].params.date_from, '2026-07-15');
  h.calls[1].resolve({ marker: 'NEW' }); await b; assert.equal(h.state.Result.marker, 'NEW');
});
for (const kind of ['fetchAttribution', 'handleOpenSnapshot']) test(`${kind} cannot mutate state after real effect cleanup`, async () => {
  const h = harness(); const pending = h[kind]('A'); h.unmount(); const before = { ...h.state };
  h.calls[0].resolve(kind === 'fetchAttribution' ? { marker: 'OLD' } : snapshot('OLD')); await pending;
  assert.deepEqual(h.state, before); assert.equal(h.scope.mountedRef.current, false);
});
test('current snapshot error clears previous values rather than mixing old result and new selection', async () => {
  const h = harness(); const a = h.handleOpenSnapshot('A'); h.calls[0].resolve(snapshot('A')); await a;
  const b = h.handleOpenSnapshot('B'); h.calls[1].reject(new Error('B failed')); await b;
  assert.equal(h.state.Result, null); assert.equal(h.state.ViewingSnapshotId, null); assert.equal(h.state.Error, 'B failed');
});
test('missing snapshot payload reports unreadable and never labels old data as that snapshot', async () => {
  const h = harness(); const a = h.handleOpenSnapshot('A'); h.calls[0].resolve({ snapshot: {} }); await a;
  assert.equal(h.state.Result, null); assert.equal(h.state.ViewingSnapshotId, null); assert.match(h.state.Error, /没有可读取/);
});
test('confirmed freeze after view change keeps latest snapshot while acknowledging the real write', async () => {
  const h = harness(); const freeze = h.handleFreeze(); const view = h.handleOpenSnapshot('B');
  h.calls[1].resolve(snapshot('B')); await view; h.calls[0].resolve(frozen()); await tick();
  assert.equal(h.state.Result.marker, 'B'); assert.equal(h.state.ViewingSnapshotId, 'B'); assert.match(h.state.Notice, /已冻结快照 frozen-A/);
  assert.equal(h.notifications.length, 1); assert.equal(h.notifications[0][0], "success");
  assert.equal(h.calls[2].kind, 'listAttributionSnapshots'); h.calls[2].resolve({ items: [{ snapshot_id: 'frozen-A' }] }); await freeze;
  assert.equal(h.calls.filter((call) => call.kind === 'createAttributionSnapshot').length, 1);
});
test('freeze completion invalidates reads started before that confirmed same-view write', async () => {
  const h = harness(); const read = h.fetchAttribution(); const freeze = h.handleFreeze();
  h.calls[1].resolve(frozen()); await tick(); h.calls[2].resolve({ items: [] }); await freeze;
  h.calls[0].resolve({ marker: 'OLD LIVE' }); await read;
  assert.equal(h.state.Result.marker, 'frozen-A'); assert.equal(h.state.Loading, false);
});
test('list refresh failure does not turn a confirmed freeze into a failed or repeated write', async () => {
  const h = harness(); const freeze = h.handleFreeze(); h.calls[0].resolve(frozen()); await tick();
  h.calls[1].reject(new Error('list failed')); await freeze;
  assert.match(h.state.Notice, /已冻结快照 frozen-A/); assert.equal(h.state.FreezeError, null); assert.match(h.state.SnapshotListError, /列表刷新失败/);
  assert.equal(h.calls.filter((call) => call.kind === 'createAttributionSnapshot').length, 1);
});
test('rapid double freeze only submits once before React can render disabled state', async () => {
  const h = harness(); const a = h.handleFreeze(); const b = h.handleFreeze(); assert.equal(h.calls.length, 1);
  h.calls[0].resolve(frozen()); await tick(); h.calls[1].resolve({ items: [] }); await Promise.all([a, b]);
  assert.equal(h.state.Freezing, false);
});
for (const fail of [false, true]) test(`freeze ${fail ? 'uncertainty' : 'confirmed completion'} after unmount still notifies without retry or page mutation`, async () => {
  const h = harness(); const a = h.handleFreeze(); h.unmount(); const before = { ...h.state };
  if (fail) h.calls[0].reject(new Error('connection lost')); else h.calls[0].resolve(frozen());
  await a; assert.deepEqual(h.state, before); assert.equal(h.calls.length, 1); assert.equal(h.notifications.length, 1);
  assert.equal(h.notifications[0][0], fail ? 'error' : 'success'); assert.match(h.notifications[0][1], fail ? /未确认.*不会自动/ : /frozen-A/);
});
test('freeze error is separate from the latest successfully selected view', async () => {
  const h = harness(); const a = h.handleFreeze(); const b = h.handleOpenSnapshot('B');
  h.calls[1].resolve(snapshot('B')); await b; h.calls[0].reject(new Error('uncertain write')); await a;
  assert.equal(h.state.Result.marker, 'B'); assert.equal(h.state.Error, null); assert.match(h.state.FreezeError, /未确认/);
});
for (const fail of [false, true]) test(`older list ${fail ? 'failure' : 'success'} cannot replace the latest list or error state`, async () => {
  const h = harness(); const a = h.loadSnapshots(); const b = h.loadSnapshots();
  h.calls[1].resolve({ items: [{ snapshot_id: 'NEW' }] }); await b;
  if (fail) h.calls[0].reject(new Error('OLD')); else h.calls[0].resolve({ items: [{ snapshot_id: 'OLD' }] }); await a;
  assert.equal(h.state.Snapshots[0].snapshot_id, 'NEW'); assert.equal(h.state.SnapshotListError, null);
});
