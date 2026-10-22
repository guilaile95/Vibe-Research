import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { addCodes, parseCodes } from '../src/lib/watchlist.ts';
import * as snapshot from '../src/lib/quoteSnapshot.ts';

function harness(quoteState, live = false, anomalyItems = []) {
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
    "react-router-dom": { Link: "Link", useLocation: () => ({ pathname: "/watchlist", search: "", hash: "" }), useSearchParams: () => [new URLSearchParams(), () => {}] },
    react: React,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    '@/lib/watchlist': {
      loadWatchAuthoritative: async () => { loads++; if (failRetryReadback && loads > 1) { draft.length = 0; throw new Error('READBACK_FAILED_AFTER_IMPORT'); } return { codes: ['600000','600001','600002'], etag:'current', status:'valid', migrated:false }; },
      loadLocalDraft: () => [...draft], addCodes, parseCodes,
      saveWatchAuthoritative: async (codes, etag) => { saves.push({ codes, etag }); return { codes, etag: 'saved' }; },
      filterAndSortWatchlistCodes: codes => codes,
    },
    '@/lib/decisionCockpit': { getWatchlistAnomalies: async () => ({ items: anomalyItems, unavailable_codes: [] }) },
    '@/hooks/useLiveQuotes': { useLiveQuotes: () => ({refresh:()=>{},...quoteState}), isTradingHours:()=>false },
    '@/lib/quoteSnapshot': snapshot,
    '@/lib/candidateCampaign': { candidateWorkspaceHref: code => `/candidate?code=${code}` },
  };
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL('../src/pages/Watchlist.tsx', import.meta.url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(source, { URLSearchParams, exports, require: name => modules[name] ?? stub, localStorage: { getItem: () => live ? "on" : null } });
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

test('quote status layout stacks readable mobile blocks and wraps compact desktop items', async () => {
  const h = harness({...quoteState, updatedAt: instant}, true);
  h.render(); await tick(); const tree = h.render();
  const all = nodes(tree);
  const group = all.find(node => node.props?.['data-testid'] === 'quote-refresh-layout');
  const provenance = nodes(group).find(node => node.props?.['data-testid'] === 'quote-provenance');
  assert.ok(group); assert.ok(provenance);
  const items = nodes(provenance).filter(node => node.props?.className?.split(' ').includes('quote-status-item'));
  assert.equal(items.length, 6, 'error, coverage, polling, session rule, source time and completion remain separate blocks');
  const error = items.find(node => node.props?.role === 'status');
  assert.ok(error?.props.className.includes('quote-status-error'));
  const labels = nodes(provenance).filter(node => node.props?.className === 'quote-status-label');
  assert.deepEqual(labels.map(text), ['快照覆盖 ', '已显示快照最早行情时间 ', '上次请求完成 ']);
  const refresh = nodes(group).find(node => node.props?.['aria-label'] === '刷新行情与异动');
  assert.ok(refresh); assert.equal(nodes(provenance).includes(refresh), false, 'button has its own column outside status blocks');
  assert.match(refresh.props.className, /min-h-11 min-w-11 shrink-0/);
  const css = all.filter(node => node.type === 'style').map(text).join('\n');
  assert.match(css, /\.quote-refresh-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) 44px/);
  assert.match(css, /\.quote-provenance\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(css, /\.quote-status-label\s*\{\s*display:\s*block/);
  assert.match(css, /@media \(min-width: 768px\)[\s\S]*\.quote-provenance\s*\{[^}]*display:\s*flex;[^}]*flex-wrap:\s*wrap/);
  assert.match(css, /\.quote-status-item\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;[^}]*overflow-wrap:\s*anywhere/);
});

test('separate refresh control retains action and loading accessibility behavior', async () => {
  let refreshes = 0;
  for (const loading of [false, true]) {
    const h = harness({...quoteState, loading, refresh: () => { refreshes++; }});
    h.render(); await tick(); const tree = h.render();
    const button = nodes(tree).find(node => node.props?.['aria-label'] === '刷新行情与异动');
    assert.equal(button.props.disabled, loading);
    if (!loading) button.props.onClick();
  }
  assert.equal(refreshes, 1);
});

const nameProjection = (tree) => nodes(tree).find(node => typeof node.props?.onContextChange === 'function').props;
const stockRow = (tree, code) => nodes(tree).find(node => node.props?.['data-watchlist-code'] === code);

test('missing quote and event use existing security metadata by code, including refreshed names and unknowns', async () => {
  const h = harness({ ...quoteState, quotes: {} }); h.render(); await tick();
  const initial = h.render();
  const projection = nameProjection(initial);
  projection.onContextChange({ securities: [
    { code: '600002', company_name: '元数据名称' },
    { code: '600000', company_name: '另一公司' },
    { code: '999999', company_name: '无关公司' },
  ] }, projection.codes);
  let tree = h.render();
  assert.match(text(stockRow(tree, '600002')), /元数据名称/);
  assert.doesNotMatch(text(stockRow(tree, '600001')), /元数据名称|另一公司|无关公司/);
  assert.ok(nodes(stockRow(tree, '600002')).some(node => node.props?.['aria-label'] === '移除 元数据名称（600002）'));
  assert.deepEqual(h.saves, [], 'display metadata cannot write watchlist authority');
  projection.onContextChange({ securities: [{ code: '600002', company_name: '更名后名称' }] }, projection.codes);
  tree = h.render();
  assert.match(text(stockRow(tree, '600002')), /更名后名称/);
  assert.doesNotMatch(text(stockRow(tree, '600002')), /元数据名称/);
  projection.onContextChange(null, projection.codes);
  assert.doesNotMatch(text(stockRow(h.render(), '600002')), /更名后名称/);
});

test('list changes reject late old metadata, even for a code still in the new list', async () => {
  const h = harness({ ...quoteState, quotes: {} }); h.render(); await tick();
  let tree = h.render(); const old = nameProjection(tree);
  nodes(stockRow(tree, '600000')).find(node => node.props?.['aria-label'] === '移除 股票（600000）').props.onClick();
  await tick(); tree = h.render();
  old.onContextChange({ securities: [{ code: '600002', company_name: '迟到旧名称' }] }, old.codes);
  assert.doesNotMatch(text(stockRow(h.render(), '600002')), /迟到旧名称/);
  const current = nameProjection(h.render());
  current.onContextChange({ securities: [{ code: '600002', company_name: '当前名称' }] }, current.codes);
  assert.match(text(stockRow(h.render(), '600002')), /当前名称/);
});

test('quote and anomaly name behavior remains primary over metadata fallback', async () => {
  const h = harness(quoteState); h.render(); await tick();
  const projection = nameProjection(h.render());
  projection.onContextChange({ securities: [{ code: '600000', company_name: '后备名称' }] }, projection.codes);
  const row = text(stockRow(h.render(), '600000'));
  assert.match(row, /Old/); assert.doesNotMatch(row, /后备名称/);
});


test('event name remains the fallback before metadata when quote is absent', async () => {
  const h = harness({ ...quoteState, quotes: {} }, false, [{ code: '600002', name: '异动名称', type: 'price', reason: '测试' }]);
  h.render(); await tick(); h.render(); await tick();
  const projection = nameProjection(h.render());
  projection.onContextChange({ securities: [{ code: '600002', company_name: '后备名称' }] }, projection.codes);
  const row = text(stockRow(h.render(), '600002'));
  assert.match(row, /异动名称/); assert.doesNotMatch(row, /后备名称/);
});
