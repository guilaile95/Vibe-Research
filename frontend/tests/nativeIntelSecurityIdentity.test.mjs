import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
import { ApiError } from '../src/lib/api.ts';
const source = ts.transpileModule(readFileSync(new URL('../src/components/native-intel/NativeIntelSecurityContext.tsx', import.meta.url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function harness(request) {
  const slots = [], effects = [], callbacks = []; let cursor = 0, pending = [], code = '600519';
  const onContextChange = (value, code) => callbacks.push({ value, code });
  const React = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useEffect(fn, deps) { const i = cursor++; if (!effects[i] || deps.some((d, n) => !Object.is(d, effects[i].deps[n]))) pending.push(() => { effects[i]?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; }); },
  };
  const stub = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : () => null });
  const modules = { react: React, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, '@/lib/api': { ApiError, api: { nativeIntelSecurityContext: request } } };
  const exports = {}; vm.runInNewContext(source, { exports, require: name => modules[name] ?? stub, AbortController });
  return { callbacks, code(value) { code = value; }, render() { cursor = 0; const tree = exports.NativeIntelSecurityContext({ code, onContextChange }); const queue = pending; pending = []; queue.forEach(fn => fn()); return tree; } };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const data = (code, name) => ({ status: 'normal', security: { code, company_name: name }, mapping: { terms: [], errors: [] }, window_hours: 24, observation: { items: [], item_count: 0 }, rank_history: {} });
function text(tree) { if (tree == null || typeof tree === 'boolean') return ''; if (typeof tree !== 'object') return String(tree); return Array.isArray(tree) ? tree.map(text).join('') : text(tree.props?.children); }
test('security mapping is bound to requested code across failed and late responses', async () => {
  let finishOld;
  const h = harness(code => code === '600519' ? new Promise(resolve => { finishOld = resolve; }) : Promise.reject(new Error('new failure')));
  h.render(); h.code('600520'); h.render(); await tick(); finishOld(data('600519', 'OLD_NAME')); await tick();
  assert.doesNotMatch(text(h.render()), /OLD_NAME|读取中/);
  assert.match(text(h.render()), /读取失败/);
  assert.equal(h.callbacks.filter(row => row.value).length, 0);
});
test('a mismatched successful response is an explicit failure, never a name or perpetual loading', async () => {
  const h = harness(async () => data('600520', 'WRONG_NAME'));
  h.render(); await tick(); const body = text(h.render());
  assert.match(body, /读取失败/); assert.doesNotMatch(body, /WRONG_NAME|读取中/);
  assert.equal(h.callbacks.filter(row => row.value).length, 0);
});
test('matching existing mapping supplies its name without a new search service', async () => {
  const h = harness(async code => data(code, 'SYNTHETIC_NAME'));
  h.render(); await tick(); assert.match(text(h.render()), /SYNTHETIC_NAME/);
  assert.equal(h.callbacks.at(-1).code, '600519');
  assert.equal(h.callbacks.at(-1).value.security.company_name, 'SYNTHETIC_NAME');
  h.code('600520'); assert.doesNotMatch(text(h.render()), /SYNTHETIC_NAME/);
});
