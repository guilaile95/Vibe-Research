import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { buildTradeListQuery, validateTradeListFilters } from '../src/lib/tradeLedgerView.ts';

const source = readFileSync(new URL('../src/pages/Trades.tsx', import.meta.url), 'utf8');
const part = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const body = part('  const selectListScope =', '  // 加载单条详情')
  + part('  const handleFilterSubmit =', '  // 打开与关闭新建')
  + part('  // 分页', '  const executionTimePreview =');
function harness() {
  const calls = [], state = {}, effects = [];
  const scope = {
    useCallback: (fn) => fn, useEffect: (fn) => effects.push(fn), PAGE_LIMIT: 10, Error, ApiError: class extends Error {},
    buildTradeListQuery, validateTradeListFilters,
    filters: { code: '000001' }, appliedFilters: { code: '000001' }, offset: 0, trades: [],
    listMountedRef: { current: true }, listRequestRef: { current: 0 }, listScopeRef: { current: { filters: { code: '000001' }, offset: 0 } },
    api: { listTrades: (query) => new Promise((resolve, reject) => calls.push({ query, resolve, reject })) },
  };
  for (const name of ['Loading', 'Error', 'FilterError']) scope['set' + name] = (value) => { state[name] = value; };
  for (const [name, variable] of [['Trades', 'trades'], ['Filters', 'filters'], ['AppliedFilters', 'appliedFilters'], ['Offset', 'offset']]) scope['set' + name] = (value) => { state[name] = value; scope[variable] = value; };
  const mount = part('  useEffect(() => {\n    listMountedRef.current = true;', '  // 详情 modal state');
  vm.runInNewContext(ts.transpileModule(mount + body + ';globalThis.actions={loadTrades,selectListScope,handleFilterSubmit,handleFilterReset,handleNextPage,handlePrevPage};', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, scope);
  const unmount = effects[0]();
  return { calls, state, scope, unmount, ...scope.actions };
}
function apply(h, code) { h.scope.filters = { code }; h.handleFilterSubmit(); }

for (const reject of [false, true]) test(`older code-filter ${reject ? 'error' : 'success'} cannot replace newest result`, async () => {
  const h = harness(); const a = h.loadTrades(); apply(h, '000002'); const b = h.loadTrades();
  h.calls[1].resolve([{ trade_id: 'B', code: '000002' }]); await b;
  if (reject) h.calls[0].reject(new Error('OLD')); else h.calls[0].resolve([{ trade_id: 'A', code: '000001' }]); await a;
  assert.equal(h.state.Trades[0].code, '000002'); assert.equal(h.state.AppliedFilters.code, '000002'); assert.equal(h.state.Error, null);
});
for (const reject of [false, true]) test(`old ${reject ? 'error' : 'success'} finalizer cannot stop a newer pending request`, async () => {
  const h = harness(); const a = h.loadTrades(); apply(h, '000002'); const b = h.loadTrades();
  if (reject) h.calls[0].reject(new Error('OLD')); else h.calls[0].resolve([]); await a;
  assert.equal(h.state.Loading, true); assert.equal(h.state.Error, null);
  h.calls[1].resolve([{ trade_id: 'B' }]); await b; assert.equal(h.state.Loading, false);
});
test('same-query retry is also latest-request-wins', async () => {
  const h = harness(); const a = h.loadTrades(); const b = h.loadTrades();
  h.calls[1].resolve([{ trade_id: 'NEW' }]); await b; h.calls[0].resolve([{ trade_id: 'OLD' }]); await a;
  assert.equal(h.state.Trades[0].trade_id, 'NEW');
});
test('reset invalidates filtered read synchronously before its new effect runs', async () => {
  const h = harness(); const a = h.loadTrades(); h.handleFilterReset(); h.calls[0].resolve([{ code: '000001' }]); await a;
  assert.equal(h.state.Trades.length, 0); assert.equal(h.state.Loading, true); assert.equal(h.state.Filters.code, '');
  const b = h.loadTrades(); assert.equal(h.calls[1].query.code, undefined); assert.equal(h.calls[1].query.offset, 0);
  h.calls[1].resolve([{ code: 'ALL' }]); await b; assert.equal(h.state.Trades[0].code, 'ALL');
});
test('invalid draft filters do not start a read or invalidate accepted results', () => {
  const h = harness(); h.scope.filters = { code: 'bad' }; const generation = h.scope.listRequestRef.current; h.handleFilterSubmit();
  assert.ok(h.state.FilterError); assert.equal(h.scope.listRequestRef.current, generation); assert.equal(h.calls.length, 0);
});
test('editing filter inputs without applying does not change the read scope', async () => {
  const h = harness(); h.scope.filters = { code: '000002' }; const request = h.loadTrades();
  assert.equal(h.calls[0].query.code, '000001'); h.calls[0].resolve([]); await request;
});
test('saved refresh callback uses latest applied filters rather than old write-time closure', async () => {
  const h = harness(); const savedRefresh = h.loadTrades; apply(h, '000002');
  const request = savedRefresh(); assert.equal(h.calls[0].query.code, '000002'); h.calls[0].resolve([]); await request;
});
test('new filter application resets pagination to zero and preserves actual query contract', async () => {
  const h = harness(); h.scope.offset = 20; h.scope.filters = { code: '000002', operation: 'sell', include_voided: true }; h.handleFilterSubmit();
  const request = h.loadTrades(); assert.deepEqual({ ...h.calls[0].query }, { code: '000002', operation: 'sell', include_voided: true, limit: 10, offset: 0 }); h.calls[0].resolve([]); await request;
});
test('page transition invalidates its older page response', async () => {
  const h = harness(); const first = h.loadTrades(); h.scope.trades = Array(10).fill({}); h.handleNextPage(); const next = h.loadTrades();
  assert.equal(h.calls[1].query.offset, 10); h.calls[1].resolve([{ trade_id: 'PAGE2' }]); await next;
  h.calls[0].resolve([{ trade_id: 'PAGE1' }]); await first; assert.equal(h.state.Trades[0].trade_id, 'PAGE2');
  h.handlePrevPage(); const prev = h.loadTrades(); assert.equal(h.calls[2].query.offset, 0); h.calls[2].resolve([]); await prev;
});
for (const reject of [false, true]) test(`unmount rejects pending ${reject ? 'error' : 'success'} and later refresh cannot issue a read`, async () => {
  const h = harness(); const a = h.loadTrades(); h.unmount(); const before = { ...h.state };
  if (reject) h.calls[0].reject(new Error('OLD')); else h.calls[0].resolve([{ code: 'OLD' }]); await a;
  assert.deepEqual(h.state, before); await h.loadTrades(); assert.equal(h.calls.length, 1);
});
test('current read failure clears prior rows and shows its own error', async () => {
  const h = harness(); const a = h.loadTrades(); h.calls[0].resolve([{ code: 'A' }]); await a;
  const b = h.loadTrades(); h.calls[1].reject(new Error('CURRENT')); await b;
  assert.equal(h.state.Trades.length, 0); assert.equal(h.state.Error, 'CURRENT'); assert.equal(h.state.Loading, false);
});
test('scope identity guard also protects the render-to-effect boundary', async () => {
  const h = harness(); const a = h.loadTrades(); h.scope.listScopeRef.current = { filters: { code: '000002' }, offset: 0 };
  h.calls[0].resolve([{ code: 'OLD' }]); await a; assert.equal(h.state.Trades.length, 0); assert.equal(h.state.Loading, true);
});
