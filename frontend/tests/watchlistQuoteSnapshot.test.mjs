import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { addCodes, parseCodes } from '../src/lib/watchlist.ts';
import * as snapshot from '../src/lib/quoteSnapshot.ts';

function harness(quoteState, live = false) {
  const failRetryReadback = false;
  const slots = [], effects = [];
  let cursor = 0, pending = [], loads = 0;
  const saves = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const React = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; },
    useRef(initial) { const i = cursor++; return slots[i] ??= { current: initial }; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { deps, value: fn() }; return slots[i].value; },
    useCallback(fn, deps) { return this.useMemo(() => fn, deps); },
    useEffect(fn, deps) { const i = cursor++; if (!effects[i] || !same(effects[i].deps, deps)) pending.push(() => { effects[i] = { deps }; fn(); }); },
  };
  // Hook imports are called unbound by the compiled component.
  React.useCallback = (fn, deps) => React.useMemo(() => fn, deps);
  const stub = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : () => null });
  const draft = Array.from({ length: 51 }, (_, i) => String(600000 + i));
  const modules = {
    react: React,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    '@/lib/watchlist': {
      loadWatchAuthoritative: async () => { loads++; if (failRetryReadback && loads > 1) { draft.length = 0; throw new Error('READBACK_FAILED_AFTER_IMPORT'); } return { codes: ['600000','600001','600002'], etag:'current', status:'valid', migrated:false }; },
      loadLocalDraft: () => [...draft], addCodes, parseCodes,
      saveWatchAuthoritative: async (codes, etag) => { saves.push({ codes, etag }); return { codes, etag: 'saved' }; },
      filterAndSortWatchlistCodes: codes => codes,
    },
    '@/lib/decisionCockpit': { getWatchlistAnomalies: async () => ({ items: [], unavailable_codes: [] }) },
    '@/hooks/useLiveQuotes': { useLiveQuotes: () => ({refresh:()=>{},...quoteState}), isTradingHours:()=>false },
    '@/lib/quoteSnapshot': snapshot,
    '@/lib/candidateCampaign': { candidateWorkspaceHref: code => `/candidate?code=${code}` },
  };
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL('../src/pages/Watchlist.tsx', import.meta.url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(source, { exports, require: name => modules[name] ?? stub, localStorage: { getItem: () => live ? "on" : null } });
  return { render() { cursor = 0; const tree = exports.Watchlist(); const queue = pending; pending = []; queue.forEach(fn => fn()); return tree; }, loads: () => loads, saves, draft };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree) { if (tree == null || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
function text(tree) { if (tree == null || typeof tree === 'boolean') return ''; if (typeof tree !== 'object') return String(tree); return Array.isArray(tree) ? tree.map(text).join('') : text(tree.props?.children); }


const instant = Date.parse('2026-10-09T07:00:00Z');
const quoteState = {
  quotes: {'600000':{name:'Old',price:10,change_pct:-1,amount_wan:0},'600001':{name:'Unknown',price:20}},
  snapshots:{'600000':{available:true,quoteTime:instant,stale:true,timeIssue:null},'600001':{available:true,quoteTime:null,stale:false,timeIssue:'unknown'},'600002':{available:false,quoteTime:null,stale:false,timeIssue:'unknown'}},
  updatedAt:null, requestCompletedAt:Date.parse('2026-10-12T02:00:00Z'), polling:false,
  error:'行情刷新失败，可点刷新重试；已有报价仅为旧快照',
};
test('actual Watchlist render discloses stale/unknown/missing, coverage and separate completion; AI carries same provenance', async () => {
  const h = harness(quoteState); h.render(); await tick(); const tree = h.render();
  const body = text(tree);
  assert.match(body,/快照覆盖 2\/3/); assert.match(body,/自动刷新已关闭/);
  assert.match(body,/上次请求完成.*不是行情时间/); assert.match(body,/汇总行情时间未知/);
  assert.match(body,/旧快照 · 刷新失败 · 行情时间.*2026.*北京时间/);
  assert.match(body,/行情时间未知/); assert.match(body,/行情未获取/);
  assert.doesNotMatch(body,/最新价|实时 ·/);
  const actions = nodes(tree).find(node => node.props?.title === '自选股')?.props.actions;
  const context = nodes(actions).find(node=>typeof node.props?.context === 'string')?.props.context;
  assert.match(context,/快照价格10（旧快照.*北京时间/); assert.match(context,/Unknown.*行情时间未知/);
  assert.match(context,/600002（行情未取到）/); assert.doesNotMatch(context,/现价/);
});
test('paused automatic refresh reason survives an error without claiming a retry', async () => {
  const h = harness({...quoteState,error:'自动行情获取失败，已有报价仅为旧快照'},true);
  h.render(); await tick(); const body=text(h.render());
  assert.match(body,/非轮询时段 · 自动刷新已暂停/); assert.match(body,/时段规则不含节假日/);
  assert.match(body,/自动行情获取失败/); assert.doesNotMatch(body,/正在重试/);
});

test('automatic error header discloses backoff instead of promising fixed three-second retries', async () => {
  const h = harness({...quoteState,polling:true,error:'自动行情获取失败，已有报价仅为旧快照'},true);
  h.render(); await tick(); const tree=h.render();
  assert.match(text(tree),/常规请求间隔 3 秒，失败时退避/);
  assert.doesNotMatch(text(tree),/请求结束后等待 3 秒/);
  const actions=nodes(tree).find(node=>node.props?.title==='自选股')?.props.actions;
  assert.ok(nodes(actions).some(node=>node.props?.title==='关闭自动刷新'));
});
