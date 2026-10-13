import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import * as view from '../src/lib/myReportsView.ts';

// Execute the production component and its rendered handlers with deferred writes.
// This is deterministic component coverage, not browser acceptance.
const source = ts.transpileModule(readFileSync(new URL('../src/pages/MyReports.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const tick = () => new Promise(done => setImmediate(done));
function nodes(v) { return !v || typeof v !== 'object' ? [] : Array.isArray(v) ? v.flatMap(nodes) : [v, ...nodes(v.props?.children)]; }
function text(v) { return v == null || typeof v === 'boolean' ? '' : typeof v === 'string' || typeof v === 'number' ? String(v) : Array.isArray(v) ? v.map(text).join('') : text(v.props?.children); }
function harness({ deferRefresh = false } = {}) {
  let cursor = 0, dirty = true, tree, writes = 0;
  const cells = [], effects = [], calls = [], reads = [];
  const reports = ['A', 'B'].map(id => ({ id, name: `${id}.pdf`, title: id, size: 100 }));
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(initial) { const i = cursor++; if (!(i in cells)) cells[i] = initial; return [cells[i], next => { writes++; const v = typeof next === 'function' ? next(cells[i]) : next; if (!Object.is(v, cells[i])) { cells[i] = v; dirty = true; } }]; },
    useRef(initial) { return cells[cursor++] ??= { current: initial }; },
    useMemo(fn, deps) { const i = cursor++; if (!cells[i] || !same(cells[i].deps, deps)) cells[i] = { deps, value: fn() }; return cells[i].value; },
    useEffect(fn, deps) { const i = cursor++; if (!cells[i] || !same(cells[i].deps, deps)) { const old = cells[i]; cells[i] = { deps }; effects.push(() => { old?.cleanup?.(); cells[i].cleanup = fn(); }); } },
  };
  const params = new URLSearchParams();
  const modules = {
    react, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    'react-router-dom': { Link: 'link', useSearchParams: () => [params, () => {}] },
    '@/lib/myReportsView': view, '@/data/sectors.json': { default: { sectors: [] } }, '@/lib/utils': { cn: () => '' },
    '@/lib/api': { ApiError: Error, api: { myReports: () => { if (!reads.length || !deferRefresh) { reads.push(true); return Promise.resolve(reports); } return new Promise((resolve, reject) => reads.push({ resolve, reject })); }, patchReport: (id, payload) => new Promise((resolve, reject) => calls.push({ id, payload, resolve, reject })) } },
  };
  const exports = {}, generic = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : String(key) });
  vm.runInNewContext(source, { exports, URLSearchParams, Error, require: name => modules[name] ?? generic });
  const row = id => nodes(tree).find(n => n.props?.id === `report-${id}`);
  const button = (id, label) => nodes(row(id)).find(n => n.type === 'button' && (n.props.title === label || text(n).trim() === label));
  return { calls, reads, get tree() { return tree; }, get writes() { return writes; }, row, button,
    edit(id) { button(id, '编辑').props.onClick(); },
    unmount() { cells.forEach(cell => cell?.cleanup?.()); },
    async flush() { await tick(); for (let i = 0; i < 20 && dirty; i++) { dirty = false; cursor = 0; tree = exports.MyReports(); for (const effect of effects.splice(0)) effect(); await tick(); } assert.equal(dirty, false); },
  };
}
for (const next of ['A', 'B']) test(`pending save cannot close ${next === 'A' ? 'cancelled/reopened' : 'another report'} editor`, async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); h.button('A', '保存').props.onClick(); await h.flush();
  h.button('A', '取消').props.onClick(); await h.flush(); h.edit(next); await h.flush();
  const title = nodes(h.row(next)).find(n => n.type === 'input' && n.props.placeholder === `${next}.pdf`);
  title.props.onChange({ target: { value: 'UNSAVED NEW DRAFT' } }); await h.flush();
  h.calls[0].resolve({}); await h.flush();
  assert.ok(h.button(next, '取消'), 'new edit session remains open');
  assert.ok(nodes(h.row(next)).some(n => n.type === 'input' && n.props.value === 'UNSAVED NEW DRAFT'));
  assert.equal(h.reads.length, 2, 'successful persisted write still refreshes the report list'); h.unmount();
});
test('repeated same-turn save sends only one metadata write', async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); const save = h.button('A', '保存').props.onClick;
  save(); save(); assert.equal(h.calls.length, 1); h.calls[0].resolve({}); await h.flush(); h.unmount();
});
test('old failure is not shown as the new editor error', async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); h.button('A', '保存').props.onClick(); await h.flush();
  h.edit('B'); await h.flush(); h.calls[0].reject(new Error('OLD SAVE FAILURE')); await h.flush();
  assert.doesNotMatch(text(h.row('B')), /OLD SAVE FAILURE/); assert.ok(h.button('B', '取消')); h.unmount();
});
test('unmounted save cannot refresh or mutate component state', async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); h.button('A', '保存').props.onClick(); await h.flush();
  h.unmount(); const writes = h.writes; h.calls[0].resolve({}); await tick(); await tick();
  assert.equal(h.writes, writes); assert.equal(h.reads.length, 1);
});
test('typing during save preserves unsaved fields and allows a subsequent save', async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); h.button('A', '保存').props.onClick(); await h.flush();
  const title = nodes(h.row('A')).find(n => n.type === 'input' && n.props.placeholder === 'A.pdf');
  title.props.onChange({ target: { value: 'NEW DRAFT' } }); await h.flush();
  h.calls[0].resolve({}); await h.flush(); assert.ok(h.button('A', '保存'));
  h.button('A', '保存').props.onClick(); await h.flush(); assert.equal(h.calls[1].payload.title, 'NEW DRAFT');
  h.calls[1].resolve({}); await h.flush(); assert.equal(h.button('A', '取消'), undefined); h.unmount();
});
test('pending save locks a newly selected editor until completion, then allows saving', async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); h.button('A', '保存').props.onClick(); await h.flush();
  h.edit('B'); await h.flush(); const pending = h.button('B', '保存中…'); assert.equal(pending.props.disabled, true);
  pending.props.onClick(); assert.equal(h.calls.length, 1);
  h.calls[0].reject(new Error('OLD SAVE FAILURE')); await h.flush();
  assert.match(text(h.tree), /研报「A」保存失败：OLD SAVE FAILURE/);
  h.button('B', '保存').props.onClick(); assert.equal(h.calls[1].id, 'B'); h.calls[1].resolve({}); await h.flush(); h.unmount();
});
test('active editor save failure remains visible and retry can close the editor', async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); h.button('A', '保存').props.onClick(); await h.flush();
  h.calls[0].reject(new Error('CURRENT FAILURE')); await h.flush(); assert.match(text(h.row('A')), /CURRENT FAILURE/);
  h.button('A', '保存').props.onClick(); await h.flush(); assert.doesNotMatch(text(h.row('A')), /CURRENT FAILURE/);
  h.calls[1].resolve({}); await h.flush(); assert.equal(h.button('A', '取消'), undefined); h.unmount();
});
test('late save rejection after unmount cannot update state', async () => {
  const h = harness(); await h.flush(); h.edit('A'); await h.flush(); h.button('A', '保存').props.onClick(); await h.flush();
  h.unmount(); const writes = h.writes; h.calls[0].reject(new Error('LATE FAILURE')); await tick(); await tick();
  assert.equal(h.writes, writes); assert.equal(h.reads.length, 1);
});

test('successful PATCH releases the mutation lock even when its list readback never settles', async () => {
  const h = harness({ deferRefresh: true }); await h.flush(); h.edit('A'); await h.flush();
  h.button('A', '保存').props.onClick(); await h.flush();
  h.button('A', '取消').props.onClick(); await h.flush(); h.edit('B'); await h.flush();
  assert.equal(h.button('B', '保存中…').props.disabled, true, 'issued PATCH remains locked after Cancel');
  h.calls[0].resolve({}); await h.flush();
  assert.equal(h.reads.length, 2, 'persisted metadata still uses list readback');
  assert.equal(h.button('B', '保存')?.props.disabled, false, 'unsettled readback must not lock new editors');
  const save = h.button('B', '保存').props.onClick; save(); save();
  assert.equal(h.calls.length, 2, 'new PATCH retains same-turn duplicate guard');
  h.calls[1].resolve({}); await h.flush(); h.unmount();
});

test('previous persisted readback remains usable if a subsequent PATCH fails', async () => {
  const h = harness({ deferRefresh: true }); await h.flush(); h.edit('A'); await h.flush();
  h.button('A', '保存').props.onClick(); h.calls[0].resolve({}); await h.flush();
  h.edit('B'); await h.flush();
  nodes(h.row('B')).find(n => n.type === 'input' && n.props.placeholder === 'B.pdf').props.onChange({ target: { value: 'NEW UNSAVED DRAFT' } }); await h.flush();
  h.button('B', '保存').props.onClick(); await h.flush(); h.calls[1].reject(new Error('SECOND PATCH FAILURE')); await h.flush();
  h.reads[1].resolve([{ id: 'A', title: 'FIRST PERSISTED TITLE', name: 'A.pdf', size: 100 }, { id: 'B', title: 'B', name: 'B.pdf', size: 100 }]); await h.flush();
  assert.match(text(h.row('A')), /FIRST PERSISTED TITLE/);
  assert.match(text(h.row('B')), /SECOND PATCH FAILURE/);
  assert.ok(nodes(h.row('B')).some(n => n.type === 'input' && n.props.value === 'NEW UNSAVED DRAFT'));
  h.button('B', '保存').props.onClick(); assert.equal(h.calls[2].payload.title, 'NEW UNSAVED DRAFT');
  h.calls[2].resolve({}); await h.flush(); h.unmount();
});

test('older readback during the next PATCH cannot unlock or close its editor', async () => {
  const h = harness({ deferRefresh: true }); await h.flush(); h.edit('A'); await h.flush();
  h.button('A', '保存').props.onClick(); h.calls[0].resolve({}); await h.flush();
  h.edit('B'); await h.flush(); h.button('B', '保存').props.onClick(); await h.flush();
  h.reads[1].resolve([{ id: 'A', title: 'FIRST PERSISTED TITLE', name: 'A.pdf', size: 100 }, { id: 'B', title: 'B', name: 'B.pdf', size: 100 }]); await h.flush();
  assert.equal(h.button('B', '保存中…').props.disabled, true); assert.ok(h.button('B', '取消'));
  h.button('B', '保存中…').props.onClick(); assert.equal(h.calls.length, 2);
  h.calls[1].resolve({}); await h.flush(); h.unmount();
});

for (const staleResult of ['success', 'failure']) test(`older list ${staleResult} after newer persisted readback cannot overwrite it`, async () => {
  const h = harness({ deferRefresh: true }); await h.flush(); h.edit('A'); await h.flush();
  h.button('A', '保存').props.onClick(); h.calls[0].resolve({}); await h.flush();
  h.edit('B'); await h.flush(); h.button('B', '保存').props.onClick(); h.calls[1].resolve({}); await h.flush();
  h.reads[2].resolve([{ id: 'B', title: 'AUTHORITATIVE NEW TITLE', name: 'B.pdf', size: 100 }]); await h.flush();
  const before = h.writes;
  if (staleResult === 'success') h.reads[1].resolve([{ id: 'B', title: 'OLD TITLE', name: 'B.pdf', size: 100 }]);
  else h.reads[1].reject(new Error('STALE READ FAILURE'));
  await h.flush(); assert.equal(h.writes, before); assert.match(text(h.row('B')), /AUTHORITATIVE NEW TITLE/); h.unmount();
});

test('readback failure is a list error, leaves persisted rows unchanged and permits another save', async () => {
  const h = harness({ deferRefresh: true }); await h.flush(); h.edit('A'); await h.flush();
  nodes(h.row('A')).find(n => n.type === 'input' && n.props.placeholder === 'A.pdf').props.onChange({ target: { value: 'UNCONFIRMED TITLE' } }); await h.flush();
  h.button('A', '保存').props.onClick(); h.calls[0].resolve({}); await h.flush();
  assert.doesNotMatch(text(h.row('A')), /UNCONFIRMED TITLE/, 'PATCH request must not optimistically replace list metadata');
  h.reads[1].reject(new Error('LIST READBACK FAILURE')); await h.flush();
  assert.match(text(h.tree), /LIST READBACK FAILURE/); assert.doesNotMatch(text(h.tree), /保存失败/);
  h.edit('B'); await h.flush(); h.button('B', '保存').props.onClick(); h.calls[1].resolve({}); await h.flush();
  h.reads[2].resolve([{ id: 'A', title: 'PERSISTED TITLE', name: 'A.pdf', size: 100 }]); await h.flush();
  assert.match(text(h.row('A')), /PERSISTED TITLE/); assert.doesNotMatch(text(h.tree), /LIST READBACK FAILURE/); h.unmount();
});

test('unmounted pending readback cannot update state', async () => {
  const h = harness({ deferRefresh: true }); await h.flush(); h.edit('A'); await h.flush();
  h.button('A', '保存').props.onClick(); h.calls[0].resolve({}); await h.flush(); h.unmount(); const before = h.writes;
  h.reads[1].resolve([]); await tick(); await tick(); assert.equal(h.writes, before);
});

test('earlier list readback cannot erase a newer detached PATCH failure', async () => {
  const h = harness({ deferRefresh: true }); await h.flush(); h.edit('A'); await h.flush();
  h.button('A', '保存').props.onClick(); h.calls[0].resolve({}); await h.flush();
  h.edit('B'); await h.flush(); h.button('B', '保存').props.onClick(); await h.flush();
  h.button('B', '取消').props.onClick(); await h.flush(); h.edit('A'); await h.flush();
  h.calls[1].reject(new Error('DETACHED SECOND FAILURE')); await h.flush();
  assert.match(text(h.tree), /研报「B」保存失败：DETACHED SECOND FAILURE/);
  h.reads[1].resolve([{ id: 'A', title: 'FIRST PERSISTED TITLE', name: 'A.pdf', size: 100 }, { id: 'B', title: 'B', name: 'B.pdf', size: 100 }]); await h.flush();
  assert.match(text(h.tree), /研报「B」保存失败：DETACHED SECOND FAILURE/);
  assert.doesNotMatch(text(h.row('A')), /DETACHED SECOND FAILURE/);
  h.button('A', '保存').props.onClick(); h.calls[2].resolve({}); await h.flush();
  assert.match(text(h.tree), /DETACHED SECOND FAILURE/, 'unrelated save must not erase failure');
  h.edit('B'); await h.flush(); h.button('B', '保存').props.onClick(); await h.flush();
  assert.doesNotMatch(text(h.tree), /DETACHED SECOND FAILURE/, 'retrying the failed report clears its old error');
  h.calls[3].resolve({}); await h.flush(); h.unmount();
});
