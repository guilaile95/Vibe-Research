import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { addCodes, parseCodes } from '../src/lib/watchlist.ts';

function harness({ failRetryReadback = false } = {}) {
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
      loadWatchAuthoritative: async () => { loads++; if (failRetryReadback && loads > 1) { draft.length = 0; throw new Error('READBACK_FAILED_AFTER_IMPORT'); } return { codes: ['600000'], etag: 'current', status: 'valid', migrated: false, migrationError: '关注股超过上限 50（去重后 51 只）' }; },
      loadLocalDraft: () => [...draft], addCodes, parseCodes,
      saveWatchAuthoritative: async (codes, etag) => { saves.push({ codes, etag }); return { codes, etag: 'saved' }; },
      filterAndSortWatchlistCodes: codes => codes,
    },
    '@/lib/decisionCockpit': { getWatchlistAnomalies: async () => ({ items: [], unavailable_codes: [] }) },
    '@/hooks/useLiveQuotes': { useLiveQuotes: () => ({ quotes: {}, refresh: () => {} }) },
    '@/lib/candidateCampaign': { candidateWorkspaceHref: code => `/candidate?code=${code}` },
  };
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL('../src/pages/Watchlist.tsx', import.meta.url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(source, { URLSearchParams, exports, require: name => modules[name] ?? stub, localStorage: { getItem: () => null } });
  return { render() { cursor = 0; const tree = exports.Watchlist(); const queue = pending; pending = []; queue.forEach(fn => fn()); return tree; }, loads: () => loads, saves, draft };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree) { if (tree == null || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
function text(tree) { if (tree == null || typeof tree === 'boolean') return ''; if (typeof tree !== 'object') return String(tree); return Array.isArray(tree) ? tree.map(text).join('') : text(tree.props?.children); }

test('rejected migration is visible, retries only on demand and exposes existing draft editor', async () => {
  const h = harness(); h.render(); await tick();
  let tree = h.render();
  const alert = nodes(tree).find(node => node.props?.role === 'alert' && /本地草稿/.test(text(node)));
  assert.ok(alert, 'migration failure needs a visible alert');
  assert.match(text(alert), /超过上限 50/);
  assert.match(text(alert), /保留/);
  assert.equal(h.loads(), 1);
  const retry = nodes(alert).find(node => node.type === 'button' && text(node) === '重试导入');
  assert.ok(retry); retry.props.onClick(); await tick(); tree = h.render();
  assert.equal(h.loads(), 2);
  const edit = nodes(tree).find(node => node.type === 'button' && text(node) === '编辑本地草稿');
  assert.ok(edit); edit.props.onClick(); tree = h.render();
  assert.equal(nodes(tree).find(node => node.type === 'textarea').props.value, h.draft.join(' '));
  await tick(); h.render(); assert.equal(h.loads(), 2, 'no automatic retry loop');
});


test('explicitly saving an edited draft containing only existing codes completes recovery', async () => {
  const h = harness(); h.render(); await tick();
  let tree = h.render();
  nodes(tree).find(node => node.type === 'button' && text(node) === '编辑本地草稿').props.onClick();
  tree = h.render();
  nodes(tree).find(node => node.type === 'textarea').props.onChange({ target: { value: '600000' } });
  tree = h.render();
  nodes(tree).find(node => node.type === 'button' && /添加/.test(text(node))).props.onClick();
  await tick(); tree = h.render();
  assert.deepEqual(h.saves, [{ codes: ['600000'], etag: 'current' }]);
  assert.equal(nodes(tree).some(node => node.props?.role === 'alert' && /本地草稿/.test(text(node))), false);
});


test('successful retry import followed by failed readback does not claim the draft remains', async () => {
  const h = harness({ failRetryReadback: true }); h.render(); await tick();
  let tree = h.render();
  assert.ok(nodes(tree).some(node => node.props?.role === 'alert' && /本地草稿/.test(text(node))));
  nodes(tree).find(node => node.type === 'button' && text(node) === '重试导入').props.onClick();
  await tick(); tree = h.render();
  assert.equal(h.draft.length, 0, 'successful import has already cleared the draft');
  assert.match(text(tree), /自选股读取失败/);
  assert.equal(nodes(tree).some(node => node.props?.role === 'alert' && /本地草稿/.test(text(node))), false);
});
