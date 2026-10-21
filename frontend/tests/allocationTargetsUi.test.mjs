import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';

// Execute the real component with deterministic hooks, deferred reads and clock.
// This is component logic coverage, not browser/runtime acceptance.
const source = ts.transpileModule(readFileSync(new URL('../src/components/portfolio/PortfolioAllocationCard.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const tick = () => new Promise(done => setImmediate(done));
const text = value => value == null || typeof value === 'boolean' ? '' : typeof value !== 'object' ? String(value) : Array.isArray(value) ? value.map(text).join('') : text(value.props?.children);
const nodes = value => !value || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
const NOW = Date.parse('2026-10-19T12:00:00Z');
function comparison(actual = 60, lifetime = 300_000) {
  return { latest_version: 1, active_version: 1, versions: [], status: 'COMPARABLE', as_of: new Date(NOW).toISOString(),
    valid_until: new Date(NOW + lifetime).toISOString(), denominator: 100, reasons: [], limitations: [],
    coverage: { holding_count: 1, priced_count: 1, unknown_industry_count: 1 },
    rows: [{ key: '600000', target_pct: 50, actual_pct: actual, drift_pp: actual - 50, reason: null }] };
}
function harness() {
  let cursor = 0, dirty = true, tree, snapshotToken = {}, now = NOW, nextTimer = 0;
  const cells = [], effects = [], reads = [], timers = new Map();
  const same = (a, b) => a?.length === b?.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(initial) { const i = cursor++; if (!(i in cells)) cells[i] = typeof initial === 'function' ? initial() : initial; return [cells[i], value => { const next = typeof value === 'function' ? value(cells[i]) : value; if (!Object.is(next, cells[i])) { cells[i] = next; dirty = true; } }]; },
    useRef(initial) { return cells[cursor++] ??= { current: initial }; },
    useEffect(fn, deps) { const i = cursor++; if (!cells[i] || !same(cells[i].deps, deps)) { const old = cells[i]; cells[i] = { deps }; effects.push(() => { old?.cleanup?.(); cells[i].cleanup = fn(); }); } },
  };
  class Clock extends Date { static now() { return now; } }
  const modules = { react, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    '@/components/ui/GlassCard': { GlassCard: 'card' },
    '@/lib/allocationTargets': {
      readAllocation: () => new Promise((resolve, reject) => reads.push({ resolve, reject })),
      saveAllocation: () => assert.fail('No write expected in read-only comparison tests'),
      parseTargets: () => assert.fail('No editor action expected'),
    },
  };
  const exports = {};
  vm.runInNewContext(source, { exports, Error, Date: Clock, require: name => { assert.ok(modules[name], `Unexpected dependency ${name}`); return modules[name]; },
    setTimeout(fn, delay) { const id = ++nextTimer; timers.set(id, { fn, at: now + delay }); return id; }, clearTimeout(id) { timers.delete(id); },
  });
  return { reads, get tree() { return tree; }, get timerCount() { return timers.size; },
    changePortfolio() { snapshotToken = {}; dirty = true; },
    advance(ms) { now += ms; for (const [id, timer] of timers) if (timer.at <= now) { timers.delete(id); timer.fn(); } },
    refresh() { nodes(tree).find(n => n.type === 'button' && text(n) === '刷新比较').props.onClick(); },
    unmount() { cells.forEach(cell => cell?.cleanup?.()); },
    async flush() { await tick(); for (let i = 0; i < 20 && dirty; i++) { dirty = false; cursor = 0; tree = exports.PortfolioAllocationCard({ snapshotToken }); for (const effect of effects.splice(0)) effect(); await tick(); } assert.equal(dirty, false, 'component must settle'); },
  };
}

test('portfolio change ignores old success and preserves the newest response', async () => {
  const h = harness(); await h.flush(); assert.equal(h.reads.length, 1);
  h.changePortfolio(); await h.flush(); assert.equal(h.reads.length, 2);
  h.reads[1].resolve(comparison(70)); await h.flush();
  assert.match(text(h.tree), /实际 70\.00% · 偏离 \+20\.00 pp/);
  h.reads[0].resolve(comparison(91)); await h.flush();
  assert.match(text(h.tree), /实际 70\.00% · 偏离 \+20\.00 pp/);
  assert.doesNotMatch(text(h.tree), /91\.00%|\+41\.00 pp/); h.unmount();
});

test('portfolio change clears displayed values while loading and ignores old failure', async () => {
  const h = harness(); await h.flush(); h.reads[0].resolve(comparison()); await h.flush();
  assert.match(text(h.tree), /实际 60\.00%/);
  h.refresh(); await h.flush(); assert.doesNotMatch(text(h.tree), /实际 60\.00%/);
  h.changePortfolio(); await h.flush(); assert.equal(h.reads.length, 3);
  h.reads[1].reject(new Error('OBSOLETE READ FAILURE')); await h.flush();
  assert.doesNotMatch(text(h.tree), /OBSOLETE READ FAILURE|实际 60\.00%/);
  assert.match(text(h.tree), /读取或保存中/);
  h.reads[2].resolve(comparison(80)); await h.flush();
  assert.match(text(h.tree), /实际 80\.00% · 偏离 \+30\.00 pp/); h.unmount();
});

test('earliest quote expiry hides actual and drift, keeps target, and fresh read restores comparison', async () => {
  const h = harness(); await h.flush(); h.reads[0].resolve(comparison(60, 1000)); await h.flush();
  assert.equal(h.timerCount, 1); h.advance(999); await h.flush();
  assert.match(text(h.tree), /目标 50\.00% · 实际 60\.00% · 偏离 \+10\.00 pp/);
  h.advance(1); await h.flush();
  assert.match(text(h.tree), /比较已过期/);
  assert.match(text(h.tree), /目标 50\.00% · 实际 未知 · 偏离 未知/);
  assert.doesNotMatch(text(h.tree), /实际 60\.00%|\+10\.00 pp|同口径可比较/);
  h.refresh(); await h.flush(); h.reads[1].resolve(comparison(75)); await h.flush();
  assert.match(text(h.tree), /实际 75\.00% · 偏离 \+25\.00 pp/);
  assert.doesNotMatch(text(h.tree), /比较已过期/);
  h.unmount(); assert.equal(h.timerCount, 0);
});
