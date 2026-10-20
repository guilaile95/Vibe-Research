import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const tick = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree) { if (tree == null || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }

function harness() {
  const slots = [], effects = [], requests = [], published = [];
  let cursor = 0, pending = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const React = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { deps, value: fn() }; return slots[i].value; },
    useEffect(fn, deps) { const i = cursor++; if (!effects[i] || !same(effects[i].deps, deps)) pending.push(() => { effects[i]?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; }); },
  };
  const stub = new Proxy({}, { get: () => () => null });
  const modules = {
    react: React,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    '@/lib/api': { ApiError: Error, api: { nativeIntelWatchlistContext: signal => new Promise((resolve, reject) => requests.push({ signal, resolve, reject })) } },
  };
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL('../src/components/native-intel/NativeIntelWatchlistContext.tsx', import.meta.url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(source, { exports, require: name => modules[name] ?? stub, AbortController });
  const onContextChange = (context, codes) => published.push({ context, codes });
  return {
    requests, published,
    render(codes) { cursor = 0; const tree = exports.NativeIntelWatchlistContext({ codes, onContextChange }); const queue = pending; pending = []; queue.forEach(fn => fn()); return tree; },
    unmount() { effects.forEach(effect => effect.cleanup?.()); },
  };
}

test('existing request publishes code-bound metadata, ignores late responses and refreshes renamed metadata', async () => {
  const h = harness(); const oldCodes = ['600000'], codes = ['600001'];
  h.render(oldCodes); h.render(codes);
  assert.equal(h.requests.length, 2, 'one existing context request per code-list change');
  assert.equal(h.requests[0].signal.aborted, true);
  const stale = { status: 'normal', securities: [{ code: '600000', company_name: '旧公司' }] };
  h.requests[0].resolve(stale); await tick();
  assert.equal(h.published.some(item => item.context === stale), false);
  const current = { status: 'normal', securities: [{ code: '600001', company_name: '当前公司' }] };
  h.requests[1].resolve(current); await tick();
  assert.equal(h.published.at(-1).context, current);
  assert.equal(h.published.at(-1).codes, codes);
  const tree = h.render(codes);
  nodes(tree).find(node => node.props?.['aria-label'] === '刷新自选公开资讯上下文').props.onClick();
  h.render(codes);
  assert.equal(h.published.at(-1).context, null, 'refresh clears old display projection');
  assert.equal(h.requests.length, 3);
  const renamed = { ...current, securities: [{ code: '600001', company_name: '更名公司' }] };
  h.requests[2].resolve(renamed); await tick();
  assert.equal(h.published.at(-1).context, renamed);
  h.render([]); assert.equal(h.published.at(-1).context, null);
  assert.equal(h.requests.length, 3, 'empty list does not fetch');
});

test('failed or unmounted context cannot publish a stale name', async () => {
  const h = harness(); const codes = ['600000'];
  h.render(codes); h.requests[0].reject(new Error('offline')); await tick();
  assert.equal(h.published.at(-1).context, null);
  const tree = h.render(codes);
  nodes(tree).find(node => node.props?.['aria-label'] === '刷新自选公开资讯上下文').props.onClick();
  h.render(codes); h.unmount();
  const count = h.published.length;
  h.requests[1].resolve({ securities: [{ code: '600000', company_name: '迟到公司' }] }); await tick();
  assert.equal(h.published.length, count);
});
