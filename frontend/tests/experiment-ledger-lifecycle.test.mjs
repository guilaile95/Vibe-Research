import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import * as ledger from '../src/lib/experimentLedger.ts';

const nodes = value => !value || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
for (const outcome of ['success', 'failure', 'cancel', 'older-read', 'older-error']) test(`record lifecycle ${outcome}: no mid-execution read, cancellable pending and settled readback`, async () => {
  let cursor = 0, effects = [], release, rejectExecution, releaseArchive, rejectArchive;
  let stored = [];
  const slots = [], requests = [];
  const created = { id: 'synthetic-record', status: 'PENDING', kind: 'signal', created_at: '2026-01-01T00:00:00Z' };
  const react = {
    useState: initial => { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; },
    useRef: initial => { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useEffect: (fn, deps) => { const i = cursor++; if (!slots[i] || deps.some((v, n) => !Object.is(v, slots[i][n]))) { slots[i] = deps; effects.push(fn); } },
  };
  const mods = { react, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, '@/lib/experimentLedger': ledger,
    '@/lib/api': { request: async (path, method = 'GET') => {
      requests.push({ path, method });
      if (path === '/research-experiments' && method === 'GET') {
        if (outcome.startsWith('older-') && requests.length === 1) return new Promise((resolve, reject) => { releaseArchive = resolve; rejectArchive = reject; });
        return { records: stored };
      }
      if (path === '/research-experiments' && method === 'POST') { stored = [created]; return created; }
      if (path === '/research-experiments/synthetic-record/cancel') { stored = [{ ...created, status: 'CANCELLED' }]; return stored[0]; }
      if (path === '/signals/validation/evaluate?record_id=synthetic-record') return new Promise((resolve, reject) => { release = resolve; rejectExecution = reject; });
      throw Error(`Unexpected request ${method} ${path}`);
    } },
  };
  const exports = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/research/ExperimentLedger.tsx', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText, { exports, require: name => { assert.ok(name in mods, name); return mods[name]; }, JSON, Error, encodeURIComponent });
  const render = () => { cursor = 0; const tree = exports.ExperimentLedger({ kind: 'signal', input: '{}' }); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; };
  let tree = render(); await Promise.resolve(); tree = render();
  const button = nodes(tree).find(x => x.type === 'button' && x.props.children === '运行当前输入并记录实验');
  const operation = button.props.onClick();
  await new Promise(setImmediate); tree = render();
  assert.equal(typeof release, 'function', JSON.stringify({ requests, slots }));
  assert.equal(requests.filter(x => x.method === 'GET').length, 1, 'no mid-execution snapshot GET');
  if (outcome.startsWith('older-')) {
    if (outcome === 'older-read') releaseArchive({ records: [] }); else rejectArchive(Error('older archive read failed'));
    await new Promise(setImmediate); tree = render();
    assert.equal(slots[0][0]?.id, created.id, 'older archive success/error cannot replace authoritative pending receipt');
    assert.ok(!nodes(tree).some(x => x.props?.role === 'alert'), 'older archive error cannot replace current state');
  }
  assert.ok(nodes(tree).some(x => x.type === 'button' && x.props.children === '取消接收结果并留档'), 'created pending record remains cancellable');
  if (outcome === 'cancel') {
    await nodes(tree).find(x => x.type === 'button' && x.props.children === '取消接收结果并留档').props.onClick();
    render(); await new Promise(setImmediate);
  } else stored = [{ ...created, status: outcome === 'failure' ? 'FAILED' : 'COMPLETED' }];
  if (outcome === 'failure') rejectExecution(Error('synthetic execution failure')); else release({});
  await operation; render(); await new Promise(setImmediate); tree = render();
  assert.equal(requests.filter(x => x.method === 'GET').length, outcome === 'cancel' ? 3 : 2, 'settled execution refreshes authoritative archive');
  assert.equal(slots[0][0].status, outcome === 'cancel' ? 'CANCELLED' : outcome === 'failure' ? 'FAILED' : 'COMPLETED', 'display reads final authoritative status');
  if (outcome === 'failure') assert.ok(nodes(tree).some(x => x.props?.role === 'status' && x.props.children.includes('实验未完成')));
  const refresh = nodes(tree).find(x => x.type === 'button' && x.props.children === '刷新归档');
  refresh.props.onClick(); render(); await new Promise(setImmediate); render();
  assert.equal(slots[0][0].status, stored[0].status, 'explicit reload preserves terminal result');
});
