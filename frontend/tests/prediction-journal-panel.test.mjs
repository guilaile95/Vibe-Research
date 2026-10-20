import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import * as journal from '../src/lib/predictionJournal.ts';
// Actual component with synthetic hooks and transport; not DOM/browser acceptance.
const source = readFileSync(new URL('../src/components/personal-review/PredictionJournal.tsx', import.meta.url), 'utf8');
const label = x => x == null ? '' : typeof x === 'object' ? Array.isArray(x) ? x.map(label).join(' ') : label(x.props?.children) : String(x);
const nodes = x => !x || typeof x !== 'object' ? [] : Array.isArray(x) ? x.flatMap(nodes) : [x, ...nodes(x.props?.children)];
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
function empty() { return { schema_version: 'manual-prediction.v1', as_of: '2026-01-01T00:00:00Z', records: [], summary: { total: 0, resolved_binary: 0, unresolved: 0, indeterminate: 0, brier: null, benchmark_count: 0, benchmark_brier: null, matched_forecast_brier: null, sample_caution: true, display_caution_minimum: 20, bins: Array.from({ length: 10 }, (_, i) => ({ lower: i / 10, upper: (i + 1) / 10, upper_inclusive: i === 9, count: 0, mean_probability: null, observed_frequency: null, sample_caution: true })) } }; }
function withForecast(body) { const data = empty(); data.records.push({ schema_version: data.schema_version, forecast: body, locked_at: data.as_of, revision: 0, outcome: 'UNRESOLVED', history: [] }); data.summary.total = data.summary.unresolved = 1; return data; }
function harness() {
  const slots = [], effects = [], calls = []; let cursor = 0, pending = [], tree, writes = 0;
  const hooks = {
    useId: () => 'journal',
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { writes++; slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(initial) { const i = cursor++; return slots[i] ?? (slots[i] = { current: initial }); },
    useEffect(fn, deps) { const i = cursor++; if (!effects[i] || deps.some((d, j) => d !== effects[i].deps[j])) pending.push(() => { effects[i]?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; }); },
  };
  const request = (...args) => new Promise((resolve, reject) => calls.push({ args, resolve, reject }));
  const exports = {}, jsx = (type, props) => ({ type, props });
  const modules = { react: hooks, 'react/jsx-runtime': { jsx, jsxs: jsx }, '@/lib/api': { request }, '@/lib/predictionJournal': journal };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText, { exports, require: name => modules[name], AbortController, crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000001' } });
  return {
    calls, render() { cursor = 0; tree = exports.PredictionJournal(); const next = pending; pending = []; next.forEach(f => f()); return tree; },
    get tree() { return tree; }, get writes() { return writes; },
    find(type, predicate = () => true) { return nodes(tree).find(n => n.type === type && predicate(n)); },
    button(text) { return nodes(tree).find(n => n.type === 'button' && label(n) === text); },
    change(type, predicate, value, checked) { this.find(type, predicate).props.onChange({ target: { value, checked } }); this.render(); },
    submit() { this.find('form').props.onSubmit({ preventDefault() {} }); },
    unmount() { effects.forEach(e => e?.cleanup?.()); },
  };
}
async function loaded() { const h = harness(); h.render(); h.calls[0].resolve(empty()); await flush(); h.render(); return h; }
function fill(h) {
  for (const [key, value] of [['subject', 'Synthetic'], ['question', 'Will the fixture criterion hold?'], ['evidence_context', 'Fixture context']]) h.change('textarea', n => n.props.id === `journal-${key}`, value);
  h.change('input', n => n.props.type === 'number' && n.props.required, '70');
  h.change('input', n => n.props.type === 'datetime-local' && n.props.required, '2026-01-02T12:00');
  h.change('input', n => n.props.type === 'checkbox', undefined, true);
}
test('actual journal submits once and verifies authoritative readback before success', async () => {
  const h = await loaded(); fill(h); h.submit(); h.submit();
  assert.equal(h.calls.length, 2); assert.equal(h.calls[1].args[1], 'POST'); assert.equal(h.calls[1].args[2].probability, .7);
  const body = h.calls[1].args[2]; h.calls[1].resolve({}); await flush(); h.render();
  assert.equal(h.calls.length, 3); assert.doesNotMatch(label(h.tree), /原预测已锁定/);
  h.calls[2].resolve(withForecast(body)); await flush(); h.render();
  assert.match(label(h.tree), /原预测已锁定/); assert.equal(h.find('textarea').props.value, ''); h.unmount();
});
test('failed readback retains draft and identity and disables retries until reload', async () => {
  const h = await loaded(); fill(h); h.submit(); const identity = h.calls[1].args[2].id;
  h.calls[1].resolve({}); await flush(); h.calls[2].reject(new Error('readback failed')); await flush(); h.render();
  assert.equal(h.find('textarea').props.value, 'Synthetic'); assert.equal(h.button('锁定预测到本地归档').props.disabled, true);
  assert.match(label(h.tree), /草稿保留/); h.submit(); assert.equal(h.calls.length, 3);
  h.button('重新读取核对').props.onClick(); h.render(); h.calls[3].resolve(empty()); await flush(); h.render(); h.submit();
  assert.equal(h.calls[4].args[2].id, identity); h.unmount();
});
test('filter change ignores old read and historical mode disables writes', async () => {
  const h = harness(); h.render(); h.change('input', n => n.props.id === 'journal-asof', '2025-12-31T12:00');
  h.calls[0].resolve(withForecast({})); await flush(); h.render(); assert.doesNotMatch(label(h.tree), /预测响应不可核对/);
  const past = empty(); past.as_of = '2025-12-31T12:00:00Z'; h.calls[1].resolve(past); await flush(); h.render();
  assert.equal(h.button('锁定预测到本地归档').props.disabled, true); assert.match(label(h.tree), /历史视图/); h.unmount();
});
test('unmount suppresses late read and write-success state updates', async () => {
  const h = harness(); h.render(); h.unmount(); const before = h.writes; h.calls[0].resolve(empty()); await flush(); assert.equal(h.writes, before);
  const writing = await loaded(); fill(writing); writing.submit(); writing.unmount(); const during = writing.writes;
  writing.calls[1].resolve({}); await flush(); writing.calls[2].resolve(withForecast(writing.calls[1].args[2])); await flush(); assert.equal(writing.writes, during);
});
