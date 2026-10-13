import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the real noncredential Settings sections using the existing deterministic
// hook/JSX harness pattern. No Settings root, browser storage, or live API is used.
const source = ts.transpileModule(readFileSync(new URL('../src/pages/Settings.tsx', import.meta.url), 'utf8') + '\nexport { NativeIntelFilterSettingsSection, NativeIntelDisplayAndProxySection };', {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const tick = () => new Promise(done => setImmediate(done));
const nodes = v => !v || typeof v !== 'object' ? [] : Array.isArray(v) ? v.flatMap(nodes) : [v, ...nodes(v.props?.children)];
const text = v => v == null || typeof v === 'boolean' ? '' : typeof v === 'string' || typeof v === 'number' ? String(v) : Array.isArray(v) ? v.map(text).join('') : text(v.props?.children);
const cases = [
  { section: 'NativeIntelFilterSettingsSection', read: 'nativeIntelFilterProfile', write: 'updateNativeIntelFilterProfile', save: '保存筛选设置', retry: '重试', field: 'settings-filter-global-excludes', draft: 'DRAFT_EXCLUDE', fixture: { profile_id: 'default', name: 'SYNTHETIC', method: 'keyword', keyword_rules: { global_excludes: ['KEEP'], filter_terms: [], groups: [] }, tags: [] } },
  { section: 'NativeIntelDisplayAndProxySection', read: 'nativeIntelConfig', write: 'updateNativeIntelConfig', save: '保存展示与抓取设置', retry: '刷新配置', field: 'wave3-standalone-max-items', draft: '47', fixture: { rss_global_max_age_days: 9, standalone_max_items: 31 } },
];
function harness(spec, read) {
  let cursor = 0, dirty = true, tree;
  const cells = [], effects = [], writes = [], notices = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(initial) { const i = cursor++; if (!(i in cells)) cells[i] = typeof initial === 'function' ? initial() : initial; return [cells[i], next => { const v = typeof next === 'function' ? next(cells[i]) : next; if (!Object.is(v, cells[i])) { cells[i] = v; dirty = true; } }]; },
    useEffect(fn, deps) { const i = cursor++; if (!cells[i] || !same(cells[i].deps, deps)) { const old = cells[i]; cells[i] = { deps }; effects.push(() => { old?.cleanup?.(); cells[i].cleanup = fn(); }); } },
  };
  let saveFailure = false;
  const api = new Proxy({ [spec.read]: read, nativeIntelSources: async () => ({ sources: [] }), [spec.write]: async payload => { writes.push(payload); if (saveFailure) throw new Error('SYNTHETIC_SAVE_FAILURE'); return spec.fixture; } }, { get: (obj, key) => obj[key] ?? (() => { throw new Error(`Unexpected API: ${String(key)}`); }) });
  const forbidden = new Proxy({}, { get: (_, key) => () => { throw new Error(`Credential access forbidden: ${String(key)}`); } });
  const modules = { react, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, '@/lib/api': { ApiError: Error, api }, '@/lib/llm': forbidden, sonner: { toast: { error: msg => notices.push(['error', msg]), success: msg => notices.push(['success', msg]) } } };
  const exports = {}, generic = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) });
  vm.runInNewContext(source, { exports, Error, require: name => modules[name] ?? generic });
  return { writes, notices, get tree() { return tree; }, button(label) { return nodes(tree).find(n => n.type === 'button' && text(n).trim() === label); },
    failSave(value) { saveFailure = value; },
    unmount() { cells.forEach(cell => cell?.cleanup?.()); },
    async flush() { await tick(); for (let i = 0; i < 20 && dirty; i++) { dirty = false; cursor = 0; tree = exports[spec.section](); for (const effect of effects.splice(0)) effect(); await tick(); } assert.equal(dirty, false); },
  };
}
for (const spec of cases) {
  test(`${spec.section}: initial read failure cannot save unverified defaults`, async () => {
    const h = harness(spec, async () => { throw new Error('SYNTHETIC_READ_FAILURE'); }); await h.flush();
    const save = h.button(spec.save);
    assert.ok(!save || save.props.disabled, 'unknown configuration must not be editable/saveable');
    save?.props.onClick(); await h.flush(); assert.equal(h.writes.length, 0);
    assert.match(text(h.tree), /读取.*失败/); h.unmount();
  });
}

for (const spec of cases) {
  test(`${spec.section}: retry loads persisted settings before enabling save`, async () => {
    let failed = true;
    const h = harness(spec, async () => { if (failed) throw new Error('SYNTHETIC_READ_FAILURE'); return spec.fixture; });
    await h.flush(); failed = false; h.button(spec.retry).props.onClick(); await h.flush();
    assert.equal(h.button(spec.save).props.disabled, false);
    h.button(spec.save).props.onClick(); await h.flush();
    assert.equal(h.writes.length, 1);
    if (spec.read === 'nativeIntelFilterProfile') assert.deepEqual(Array.from(h.writes[0].keyword_rules.global_excludes), ['KEEP']);
    else assert.equal(h.writes[0].standalone_max_items, 31);
    assert.equal(h.notices.filter(([type]) => type === 'success').length, 1); h.unmount();
  });
  test(`${spec.section}: rejected save retains the draft and can be retried`, async () => {
    const h = harness(spec, async () => spec.fixture); await h.flush();
    nodes(h.tree).find(n => n.props?.['data-testid'] === spec.field).props.onChange({ target: { value: spec.draft } }); await h.flush();
    h.failSave(true); h.button(spec.save).props.onClick(); await h.flush();
    assert.equal(h.writes.length, 1); assert.equal(h.button(spec.save).props.disabled, false);
    assert.equal(String(nodes(h.tree).find(n => n.props?.['data-testid'] === spec.field).props.value), spec.draft);
    assert.equal(h.notices.filter(([type]) => type === 'success').length, 0);
    h.failSave(false); h.button(spec.save).props.onClick(); await h.flush();
    assert.equal(h.writes.length, 2); assert.deepEqual(h.writes[1], h.writes[0]);
    assert.equal(h.notices.filter(([type]) => type === 'success').length, 1); h.unmount();
  });
  test(`${spec.section}: failed post-save readback is retryable without saving defaults`, async () => {
    let reads = 0;
    const h = harness(spec, async () => { if (++reads === 2) throw new Error('SYNTHETIC_READBACK_FAILURE'); return spec.fixture; });
    await h.flush(); h.button(spec.save).props.onClick(); await h.flush();
    const save = h.button(spec.save); assert.ok(!save || save.props.disabled);
    save?.props.onClick(); await h.flush(); assert.equal(h.writes.length, 1);
    h.button(spec.retry).props.onClick(); await h.flush(); assert.equal(h.button(spec.save).props.disabled, false);
    assert.equal(h.writes.length, 1); h.unmount();
  });
  test(`${spec.section}: reopening after a failed save reads persisted values`, async () => {
    const h = harness(spec, async () => spec.fixture); await h.flush(); h.failSave(true);
    h.button(spec.save).props.onClick(); await h.flush(); h.unmount();
    const reopened = harness(spec, async () => spec.fixture); await reopened.flush();
    assert.equal(reopened.button(spec.save).props.disabled, false); assert.equal(reopened.writes.length, 0);
    assert.equal(reopened.notices.length, 0); reopened.unmount();
  });
}
