import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const nodes = value => !value || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
function harness() {
  let cursor = 0, pending = [], location = { key: 'factor', pathname: '/signals/factor-validation', search: '?keep=yes&from=old', hash: '', state: { kept: true } }, mounted = true;
  const slots = [], cleanups = [], calls = [], navigations = [], lateWrites = [];
  const effect = (fn, deps) => { const i = cursor++; if (!slots[i] || deps.some((v, n) => !Object.is(v, slots[i][n]))) { slots[i] = deps; pending.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); } };
  const react = {
    useState: initial => { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], next => { if (!mounted) lateWrites.push(i); slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; },
    useRef: initial => { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useEffect: effect, useLayoutEffect: effect,
  };
  const mods = {
    react, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    'react-router-dom': { useLocation: () => location, useSearchParams: () => [new URLSearchParams(location.search), (params, options) => navigations.push({ params, options })] },
    '@/components/research/ExperimentLedger': { ExperimentLedger: () => null },
    '@/lib/api': { ApiError: Error, api: {
      factorValidationRegistry: async () => ({ factors: [{ factor_id: 'return_5d', label: 'Return' }] }),
      factorValidationEvaluate: (payload, signal) => new Promise((resolve, reject) => calls.push({ payload, signal, resolve, reject })),
    } },
    '@/lib/utils': { cn: (...values) => values.join(' ') },
    '@/lib/factorValidationView': new Proxy({}, { get: () => () => '' }),
    'lucide-react': new Proxy({}, { get: (_, name) => name }),
  };
  const exports = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/signals/FactorValidationPanel.tsx', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText,
    { exports, require: name => { assert.ok(name in mods, name); return mods[name]; }, URLSearchParams, AbortController });
  const render = () => { cursor = 0; const tree = exports.FactorValidationPanel(); const effects = pending; pending = []; effects.forEach(fn => fn()); return tree; };
  const submit = () => nodes(render()).find(x => x.type === 'form').props.onSubmit({ preventDefault() {} });
  return { render, submit, calls, navigations, lateWrites,
    navigate: next => { location = { ...location, ...next }; render(); },
    input: (label, value) => { nodes(render()).find(x => x.props?.['aria-label'] === label).props.onChange({ target: { value } }); render(); },
    unmount: () => { cleanups.forEach(fn => fn?.()); mounted = false; },
  };
}
const tick = () => new Promise(setImmediate);
const report = label => ({ status: 'unavailable', results: {}, limitations: [label] });
for (const exit of ['unmount', 'navigate', 'query', 'input']) for (const failure of [false, true]) test(`factor late ${failure ? 'error' : 'success'} after ${exit} cannot own state or navigation`, async () => {
  const h = harness(); h.render(); await tick(); h.submit(); assert.equal(h.calls.length, 1);
  if (exit === 'unmount') h.unmount();
  if (exit === 'navigate') h.navigate({ key: 'other', pathname: '/research-analytics' });
  if (exit === 'query') h.navigate({ key: 'new-query', search: '?keep=new' });
  if (exit === 'input') h.input('因子验证起始日期', '2025-01-01');
  assert.equal(h.calls[0].signal.aborted, true);
  if (failure) h.calls[0].reject(Error('stale error')); else h.calls[0].resolve(report('stale result'));
  await tick();
  assert.deepEqual(h.navigations, []); assert.deepEqual(h.lateWrites, []);
  if (exit !== 'unmount') assert.ok(!JSON.stringify(h.render()).includes('stale'));
});

test('new factor request owns success and finalizer, router update preserves unrelated query and state', async () => {
  const h = harness(); h.render(); await tick(); h.submit(); h.submit();
  assert.equal(h.calls[0].signal.aborted, true);
  h.calls[0].reject(Error('old error')); await tick();
  assert.ok(JSON.stringify(h.render()).includes('计算中'));
  h.calls[1].resolve(report('new result')); await tick();
  assert.equal(h.navigations.length, 1);
  const { params, options } = h.navigations[0];
  assert.equal(params.get('keep'), 'yes'); assert.equal(params.get('factor'), 'return_5d'); assert.equal(params.has('from'), false);
  assert.equal(options.replace, true); assert.equal(options.state.kept, true);
  assert.ok(JSON.stringify(h.render()).includes('new result'));
  assert.ok(!JSON.stringify(h.render()).includes('计算中'));
});
