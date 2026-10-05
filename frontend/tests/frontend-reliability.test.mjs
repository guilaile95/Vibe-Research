import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import * as notes from '../src/lib/notes.ts';
import * as llm from '../src/lib/llm.ts';
import * as apiClient from '../src/lib/api.ts';
import * as models from '../src/lib/ai-models.ts';
import * as researchNote from '../src/lib/researchNote.ts';
import * as modelProbe from '../src/lib/modelConnectionProbe.ts';
import * as preferenceStorage from '../src/lib/storage.ts';
import * as navigation from '../src/lib/navigation.ts';
import * as sectorResearch from '../src/data/sectorResearch/index.ts';

// Component behavior in a deterministic hook runner: real TSX handlers/effects and
// storage modules, mocked network/UI dependencies. No browser or real credentials.
function harness(path, name, overrides = {}, globals = {}) {
  const states = [], effects = [], refs = [], timers = new Map(), listeners = new Map();
  let cursor = 0, pending = [], timerId = 0, scheduled = true, lastTree, lastProps = {};
  const React = {
    useState(init) { const i = cursor++; if (!(i in states)) states[i] = typeof init === 'function' ? init() : init; return [states[i], value => {
      const next = typeof value === 'function' ? value(states[i]) : value;
      if (!Object.is(states[i], next)) { states[i] = next; scheduled = true; }
    }]; },
    useRef(init) { const i = cursor++; return refs[i] ??= { current: init }; },
    useMemo: fn => fn(), useCallback: fn => fn,
    useEffect(fn, deps) {
      const i = cursor++;
      if (!effects[i] || !deps || deps.some((value, j) => value !== effects[i].deps?.[j])) {
        pending.push(() => { effects[i]?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; });
      }
    },
  };
  const generic = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : key === 'default' ? 'stub' : () => null });
  const searchParams = new URLSearchParams();
  const mods = {
    react: React,
    'react-router-dom': { useSearchParams: () => [searchParams, () => {}], Link: 'link', useBlocker: () => ({ state: 'unblocked' }) },
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' },
    '@/lib/api': apiClient, '@/lib/notes': notes, '@/lib/researchNote': researchNote, '@/lib/modelConnectionProbe': modelProbe, ...overrides,
  };
  const exports = {};
  const js = ts.transpileModule(readFileSync(new URL('../src/' + path, import.meta.url), 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(js, {
    exports, document: { addEventListener() {}, removeEventListener() {} }, require: name => mods[name] ?? generic, FileReader: globalThis.FileReader, AbortController, DOMException, Error, console, URLSearchParams, Map, Set, Date,
    window: { setTimeout: fn => { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id), addEventListener(type, fn) { listeners.set(type, fn); }, removeEventListener(type, fn) { if (listeners.get(type) === fn) listeners.delete(type); } }, confirm: () => true, ...globals,
  }, { filename: path });
  const render = (props = {}) => { scheduled = false; lastProps = props; cursor = 0; lastTree = exports[name](props); const current = pending; pending = []; current.forEach(fn => fn()); return lastTree; };
  return {
    render,
    // Respect React's same-state bailout when testing external storage changes.
    flushScheduled() { let remaining = 30; while (scheduled && remaining-- > 0) render(lastProps); assert.equal(scheduled, false, 'render did not settle'); return lastTree; },
    emit(type, event) { listeners.get(type)?.(event); },
    hasListener(type) { return listeners.has(type); },
    flushTimers() { const current = [...timers.values()]; timers.clear(); current.forEach(fn => fn()); },
    unmount() { effects.forEach(effect => effect?.cleanup?.()); },
  };
}
function nodes(value) {
  if (!value || typeof value !== 'object') return [];
  if (Array.isArray(value)) return value.flatMap(nodes);
  return [value, ...nodes(value.props?.children), ...nodes(value.props?.actions)];
}
function label(value) {
  if (value == null || value === false) return '';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(label).join('');
  return label(value.props?.children);
}
const find = (tree, type, text) => nodes(tree).find(node => node.type === type && (!text || label(node).includes(text)));
const testId = (tree, id) => nodes(tree).find(node => node.props?.['data-testid'] === id);
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const storage = new Map();
const workingStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
test.beforeEach(() => { storage.clear(); globalThis.localStorage = workingStorage; });
test.afterEach(() => { globalThis.localStorage = workingStorage; storage.clear(); });

const layoutHarness = () => harness('components/layout/Layout.tsx', 'Layout', {
  'react-router-dom': { useLocation: () => ({ pathname: '/notes' }), Link: 'link', Outlet: 'outlet' },
  '@/hooks/useDarkMode': { useDarkMode: () => ({ dark: false, toggle() {} }) },
  '@/lib/storage': preferenceStorage, '@/lib/navigation': navigation,
}, { localStorage: globalThis.localStorage });
const sidebarControl = (tree, name) => nodes(tree).find(node => node.type === 'button' && node.props['aria-label'] === name);

test('sidebar valid preferences persist and missing or corrupt values default to expanded', () => {
  for (const value of [null, 'expanded', 'collapsed', '', 'true', '{broken']) {
    storage.clear();
    if (value !== null) storage.set('vr-sidebar', value);
    const h = layoutHarness();
    const tree = h.render();
    assert.ok(sidebarControl(tree, value === 'collapsed' ? '展开侧栏' : '收起侧栏'));
    sidebarControl(tree, value === 'collapsed' ? '展开侧栏' : '收起侧栏').props.onClick();
    h.render();
    assert.equal(storage.get('vr-sidebar'), value === 'collapsed' ? 'expanded' : 'collapsed');
    h.unmount();
    assert.ok(sidebarControl(layoutHarness().render(), value === 'collapsed' ? '收起侧栏' : '展开侧栏'));
  }
});

test('sidebar storage read denial falls back without preventing in-memory navigation state', () => {
  globalThis.localStorage = { ...workingStorage, getItem(key) { if (key === 'vr-sidebar') throw new DOMException('denied', 'SecurityError'); return workingStorage.getItem(key); } };
  const h = layoutHarness();
  sidebarControl(h.render(), '收起侧栏').props.onClick();
  assert.ok(sidebarControl(h.render(), '展开侧栏'));
  h.unmount();
});

test('sidebar denied writes keep session toggles usable and retain the last saved preference', () => {
  for (const name of ['SecurityError', 'QuotaExceededError']) {
    storage.set('vr-sidebar', 'collapsed');
    let denied = true;
    globalThis.localStorage = { ...workingStorage, setItem(key, value) { if (key === 'vr-sidebar' && denied) throw new DOMException('denied', name); workingStorage.setItem(key, value); } };
    const h = layoutHarness();
    sidebarControl(h.render(), '展开侧栏').props.onClick();
    assert.ok(sidebarControl(h.render(), '收起侧栏'));
    assert.equal(storage.get('vr-sidebar'), 'collapsed');
    h.unmount();
    const reloaded = layoutHarness();
    assert.ok(sidebarControl(reloaded.render(), '展开侧栏'));
    denied = false;
    sidebarControl(reloaded.render(), '展开侧栏').props.onClick();
    reloaded.render();
    assert.equal(storage.get('vr-sidebar'), 'expanded');
    reloaded.unmount();
  }
});

const noteProps = { kind: 'test', title: 'Synthetic research', content: 'Synthetic content' };
test('failed note save keeps the button retryable and shows an error', () => {
  globalThis.localStorage = { ...workingStorage, setItem() { throw Error('quota'); } };
  const h = harness('components/ui/SaveNoteButton.tsx', 'SaveNoteButton');
  find(h.render(noteProps), 'button').props.onClick();
  const tree = h.render(noteProps);
  assert.equal(find(tree, 'button').props.disabled, false);
  assert.match(label(tree), /无法保存/);
  assert.equal(notes.loadNotes().length, 0);
  globalThis.localStorage = workingStorage;
  find(tree, 'button').props.onClick();
  assert.match(label(h.render(noteProps)), /已存入沉淀/);
});
test('save state follows the exact content identity', () => {
  const h = harness('components/ui/SaveNoteButton.tsx', 'SaveNoteButton');
  find(h.render(noteProps), 'button').props.onClick();
  assert.equal(find(h.render(noteProps), 'button').props.disabled, true);
  for (const changed of [{ ...noteProps, title: 'Other' }, { ...noteProps, content: 'Other' }, { ...noteProps, kind: 'Other' }]) {
    assert.equal(find(h.render(changed), 'button').props.disabled, false);
  }
  const next = { ...noteProps, content: 'New research' };
  find(h.render(next), 'button').props.onClick();
  assert.equal(notes.loadNotes().length, 2);
  assert.equal(notes.loadNotes()[0].content, next.content);
});
test('note mutations and import reject failed writes and preserve stored records', () => {
  notes.addNote('test', 'Synthetic', 'Research');
  const original = storage.get('vr-notes');
  const id = notes.loadNotes()[0].id;
  globalThis.localStorage = { ...workingStorage, setItem() { throw Error('quota'); }, removeItem() { throw Error('denied'); } };
  assert.throws(() => notes.addNote('test', 'new', 'new'), /无法保存/);
  assert.throws(() => notes.deleteNote(id), /无法保存/);
  assert.throws(() => notes.clearNotes(), /无法清除/);
  assert.throws(() => notes.importNotesBackupJson(notes.createNotesBackupJson([])), /无法保存/);
  assert.equal(storage.get('vr-notes'), original);
});
test('read denial and malformed stored notes render errors and never overwrite unreadable data', () => {
  for (const raw of ['[null]', '{}', 'broken', '[{"id":"bad"}]', JSON.stringify([{ id:'duplicate', kind:'test', title:'test', content:'test', ts:1 }, { id:'duplicate', kind:'test', title:'test', content:'test', ts:2 }])]) {
    storage.set('vr-notes', raw);
    const h = harness('pages/Notes.tsx', 'Notes');
    const tree = h.render();
    assert.ok(nodes(tree).find(node => node.props?.role === 'alert'));
    assert.throws(() => notes.addNote('test', 'new', 'new'));
    assert.throws(() => notes.importNotesBackupJson(notes.createNotesBackupJson([])));
    assert.equal(storage.get('vr-notes'), raw);
  }
  globalThis.localStorage = { ...workingStorage, getItem() { throw Error('denied'); } };
  assert.match(notes.loadNotesState().error, /无法读取/);
  assert.throws(() => notes.addNote('test', 'new', 'new'), /无法读取/);
});
test('notes UI retains rows after failed delete and clear', () => {
  notes.addNote('test', 'Synthetic retained record', 'Research');
  const h = harness('pages/Notes.tsx', 'Notes');
  globalThis.localStorage = { ...workingStorage, setItem() { throw Error('quota'); }, removeItem() { throw Error('denied'); } };
  let tree = h.render();
  nodes(tree).find(node => node.props?.title === '删除').props.onClick();
  tree = h.render();
  assert.match(label(tree), /Synthetic retained record/);
  assert.match(label(tree), /无法保存/);
  find(tree, 'button', '清空').props.onClick();
  tree = h.render();
  assert.match(label(tree), /Synthetic retained record/);
  assert.match(label(tree), /无法清除/);
});
test('notes save at capacity reports failure rather than silently evicting user research', () => {
  storage.set('vr-notes', JSON.stringify(Array.from({ length: notes.NOTES_LIMIT }, (_, i) => ({ id: String(i), kind:'test', title:'test', content:'test', ts:i }))));
  const raw = storage.get('vr-notes');
  const h = harness('components/ui/SaveNoteButton.tsx', 'SaveNoteButton');
  find(h.render(noteProps), 'button').props.onClick();
  assert.match(label(h.render(noteProps)), /200 条上限/);
  assert.doesNotMatch(label(h.render(noteProps)), /已存入沉淀/);
  assert.equal(storage.get('vr-notes'), raw);
});

function startDebate(h, code = '600519') {
  let tree = h.render(); find(tree, 'input').props.onChange({ target: { value: code } });
  tree = h.render(); return find(tree, 'button', '开始辩论').props.onClick();
}
test('completed Debate notes retain the analyzed ticker after input edits', async () => {
  let requested;
  const h = harness('pages/Debate.tsx', 'Debate', { '@/lib/agents': { debateStream: async (code, rounds, handlers) => {
    requested = code;
    for (const stage of ['bull', 'bear', 'referee']) {
      handlers.onStageStart(stage, stage); handlers.onStageDone(stage, stage, 'Research for ' + code);
    }
  } } });
  await startDebate(h);
  let tree = h.render(); find(tree, 'input').props.onChange({ target: { value: '000001' } });
  tree = h.render(); find(tree, 'button', '存入沉淀').props.onClick();
  assert.equal(requested, '600519');
  assert.match(notes.loadNotes()[0].title, /600519/);
  assert.doesNotMatch(notes.loadNotes()[0].title, /000001/);
});
test('stopped Debate callbacks and finally cannot mutate the new run; unmount aborts it', async () => {
  const calls = [];
  const h = harness('pages/Debate.tsx', 'Debate', { '@/lib/agents': { debateStream: (code, rounds, handlers, signal) => {
    const d = deferred(); calls.push({ ...d, handlers, signal }); return d.promise;
  } } });
  const old = startDebate(h);
  find(h.render(), 'button', '中止').props.onClick();
  assert.equal(calls[0].signal.aborted, true);
  const fresh = startDebate(h, '000001');
  calls[0].handlers.onStatus('STALE STATUS');
  calls[0].handlers.onStageStart('bull', 'STALE STAGE');
  calls[0].handlers.onError('STALE ERROR');
  calls[0].reject(new DOMException('aborted', 'AbortError'));
  await old;
  const tree = h.render();
  assert.ok(find(tree, 'button', '中止'));
  assert.doesNotMatch(label(tree), /STALE/);
  assert.equal(calls[1].signal.aborted, false);
  h.unmount();
  assert.equal(calls[1].signal.aborted, true);
  calls[1].resolve(); await fresh;
});
test('late successful Debate response cannot overwrite a completed retry or its saved ticker', async () => {
  const calls = [];
  const h = harness('pages/Debate.tsx', 'Debate', { '@/lib/agents': { debateStream: (code, rounds, handlers) => {
    const d = deferred(); calls.push({ ...d, handlers }); return d.promise;
  } } });
  const old = startDebate(h);
  find(h.render(), 'button', '中止').props.onClick();
  const fresh = startDebate(h, '000001');
  for (const stage of ['bull', 'bear', 'referee']) {
    calls[1].handlers.onStageStart(stage, stage); calls[1].handlers.onStageDone(stage, stage, 'FRESH ' + stage);
  }
  calls[1].resolve(); await fresh;
  calls[0].handlers.onStageStart('bull', 'STALE');
  calls[0].handlers.onStageDone('bull', 'STALE', 'STALE');
  calls[0].handlers.onError('STALE ERROR');
  calls[0].resolve(); await old;
  const tree = h.render(); assert.doesNotMatch(label(tree), /STALE/);
  find(tree, 'button', '存入沉淀').props.onClick();
  assert.match(notes.loadNotes()[0].title, /000001/);
  assert.doesNotMatch(notes.loadNotes()[0].content, /STALE/);
});

test('failed or stopped Debate never advertises complete savable results', async () => {
  const h = harness('pages/Debate.tsx', 'Debate', { '@/lib/agents': { debateStream: async (code, rounds, handlers) => {
    handlers.onStageStart('bull','bull'); handlers.onStageDone('bull','bull','partial'); handlers.onError('provider failed');
  } } });
  await startDebate(h);
  assert.equal(find(h.render(), 'button', '存入沉淀'), undefined);
  assert.match(label(h.render()), /辩论失败/);
});

function reportHarness(search, api = {}) {
  const params = new URLSearchParams();
  return harness('pages/MyReports.tsx', 'MyReports', {
    'react-router-dom': { useSearchParams: () => [params, () => {}], Link: 'link' },
    '@/data/sectors.json': { default: { sectors: [] } }, '@/lib/utils': { cn: () => '' },
    '@/lib/myReportsView': { filterReports: rows => rows, groupReportsByIndustry: rows => [{ key:"all", label:"All", count:rows.length, reports:rows }], groupReportsByInstitution: () => [], groupReportsByYearMonth: () => [] },
    '@/lib/api': { ...apiClient, api: { myReports: async () => [], searchMyReportText: search, ...api } },
  });
}
function query(h, value) {
  const tree = h.render(); nodes(tree).find(node => node.type === 'input' && node.props.placeholder === '搜索研报正文…').props.onChange({ target: { value } });
  return h.render();
}
test('report search debounces, distinguishes pending/error/empty, and supports retry', async () => {
  const calls = [];
  const h = reportHarness((q, ids, limit, signal) => { const d = deferred(); calls.push({ ...d, q, signal }); return d.promise; });
  query(h, 'a'); query(h, 'alpha');
  assert.equal(calls.length, 0);
  h.flushTimers(); assert.equal(calls.length, 1); assert.equal(calls[0].q, 'alpha');
  assert.match(label(h.render()), /正在搜索/); assert.doesNotMatch(label(h.render()), /没有匹配/);
  calls[0].reject(Error('offline')); await tick();
  assert.match(label(h.render()), /搜索失败/); assert.doesNotMatch(label(h.render()), /没有匹配/);
  find(h.render(), 'button', '重试搜索').props.onClick(); h.render(); h.flushTimers();
  calls[1].resolve([]); await tick();
  assert.match(label(h.render()), /没有匹配/); assert.doesNotMatch(label(h.render()), /搜索失败/);
});
test('new report query hides old results immediately, aborts obsolete requests, and ignores late replies', async () => {
  const calls = [];
  const h = reportHarness((q, ids, limit, signal) => { const d = deferred(); calls.push({ ...d, q, signal }); return d.promise; });
  query(h, 'alpha'); h.flushTimers();
  calls[0].resolve([{ report_id:'synthetic', title:'Alpha only', snippet:'alpha', page:1 }]); await tick();
  assert.match(label(h.render()), /Alpha only/);
  assert.doesNotMatch(label(query(h, 'beta')), /Alpha only/);
  h.flushTimers();
  query(h, 'gamma'); h.flushTimers();
  assert.equal(calls[1].signal.aborted, true);
  calls[1].resolve([{ report_id:'stale', title:'Stale beta', snippet:'beta', page:1 }]); await tick();
  assert.doesNotMatch(label(h.render()), /Stale beta/);
  h.unmount(); assert.equal(calls[2].signal.aborted, true);
  calls[2].resolve([]); await tick();
});
test('report search API forwards cancellation to fetch', async () => {
  const original = globalThis.fetch;
  const controller = new AbortController(); let received;
  globalThis.fetch = async (url, options) => { received = options.signal; return new Response('[]', {status:200}); };
  try { await apiClient.api.searchMyReportText('synthetic', undefined, 20, controller.signal); assert.equal(received, controller.signal); }
  finally { globalThis.fetch = original; }
});

const dummyConfig = { provider:'openai-compatible', baseURL:'https://example.invalid/v1', apiKey:'SYNTHETIC-NOT-A-SECRET', model:'synthetic-model' };
test('credential helpers reject failed writes/removals rather than notifying success', () => {
  globalThis.localStorage = { ...workingStorage, setItem() { throw Error('quota'); } };
  assert.throws(() => llm.saveLlm(dummyConfig), /无法保存/);
  assert.throws(() => apiClient.saveAccessKey('SYNTHETIC-NOT-A-SECRET'), /无法保存/);
  globalThis.localStorage = workingStorage; llm.saveLlm(dummyConfig); apiClient.saveAccessKey('SYNTHETIC-NOT-A-SECRET');
  globalThis.localStorage = { ...workingStorage, removeItem() { throw Error('denied'); } };
  assert.throws(() => llm.clearLlm(), /无法清除/);
  assert.throws(() => apiClient.saveAccessKey(''), /无法清除/);
  assert.deepEqual(llm.loadLlm(), dummyConfig);
});
function settingsHarness(overrides = {}, llmOverrides = {}) {
  const messages = [];
  const h = harness('pages/Settings.tsx', 'Settings', {
    '@/lib/llm': { ...llm, ...llmOverrides }, '@/lib/ai-models': models,
    sonner: { toast: { success: message => messages.push(['success', message]), error: message => messages.push(['error', message]) } },
    '@/lib/api': { ...apiClient, api: { getAiCredentialStatus: async () => ({ configured:true }), putAiCredential: async () => {}, deleteAiCredential: async () => {}, ...overrides } },
  });
  return { h, messages };
}
test('settings report backend-save/local-failure and backend-clear/local-failure explicitly', async () => {
  llm.saveLlm(dummyConfig);
  const { h, messages } = settingsHarness();
  globalThis.localStorage = { ...workingStorage, setItem() { throw Error('quota'); }, removeItem() { throw Error('denied'); } };
  testId(h.render(), 'wave5-save-api-btn').props.onClick(); await tick();
  assert.equal(messages.at(-1)[0], 'error'); assert.match(messages.at(-1)[1], /后台凭据已保存.*浏览器保存失败/);
  testId(h.render(), 'wave5-forget-btn').props.onClick(); await tick();
  assert.equal(messages.at(-1)[0], 'error'); assert.match(messages.at(-1)[1], /后台凭据已清除.*浏览器凭据仍未清除/);
  assert.deepEqual(llm.loadLlm(), dummyConfig);
  assert.equal(messages.some(([kind]) => kind === 'success'), false);
});
test('settings backend failure leaves existing browser credentials unchanged', async () => {
  llm.saveLlm(dummyConfig);
  const { h, messages } = settingsHarness({ putAiCredential: async () => { throw Error('offline'); }, deleteAiCredential: async () => { throw Error('offline'); } });
  testId(h.render(), 'wave5-save-api-btn').props.onClick(); await tick();
  testId(h.render(), 'wave5-forget-btn').props.onClick(); await tick();
  assert.deepEqual(llm.loadLlm(), dummyConfig);
  assert.equal(messages.filter(([kind]) => kind === 'error').length, 2);
  assert.equal(messages.some(([kind]) => kind === 'success'), false);
});

test('silent storage no-ops and readback failures cannot claim save/clear success', () => {
  globalThis.localStorage = { ...workingStorage, setItem() {} };
  assert.throws(() => llm.saveLlm(dummyConfig), /无法保存/);
  assert.throws(() => notes.addNote('test', 'test', 'test'), /无法保存/);
  globalThis.localStorage = workingStorage;
  llm.saveLlm(dummyConfig);
  globalThis.localStorage = { ...workingStorage, removeItem() {} };
  assert.throws(() => llm.clearLlm(), /无法清除/);
  globalThis.localStorage = { ...workingStorage, getItem() { throw Error('denied'); } };
  assert.throws(() => apiClient.saveAccessKey('SYNTHETIC-NOT-A-SECRET'), /无法保存/);
  assert.throws(() => llm.clearLlm(), /无法清除/);
});
test('normal settings save and clear finish in both stores and report success', async () => {
  llm.saveLlm(dummyConfig);
  let backend = dummyConfig;
  const { h, messages } = settingsHarness({ putAiCredential: async config => { backend = config; }, deleteAiCredential: async () => { backend = null; } });
  testId(h.render(), 'wave5-save-api-btn').props.onClick(); await tick();
  assert.deepEqual(llm.loadLlm(), JSON.parse(JSON.stringify(backend)));
  assert.equal(messages.at(-1)[0], 'success');
  testId(h.render(), 'wave5-forget-btn').props.onClick(); await tick();
  assert.equal(llm.loadLlm(), null); assert.equal(backend, null);
  assert.equal(messages.at(-1)[0], 'success');
});
test('full-market partial/stale results label retained observations and excluded breadth', async () => {
  const screener = await import('../src/lib/recoveredScreener.ts');
  const discovery = await import('../src/lib/discoveryView.ts');
  const result = {
    status:'partial', as_of:'2026-09-30', total_rows:1, returned_rows:1, next_offset:null,
    coverage: { start:'2026-01-01', end:'2026-09-30', row_count:2, code_count:2, universe_count:2, current_count:1, stale_count:1 },
    breadth: { ma20:{ breadth:1, evaluable_count:1, insufficient_count:0, stale_count:1 }, ma60:{ breadth:null, evaluable_count:0, insufficient_count:1, stale_count:1 } },
    provenance: {}, limitations:[], rows:[{code:'600519', status:'stale', latest_date:'2026-09-29', latest_close:10, return_20d:0.1, metric_status:{latest_close:'STALE', return_20d:'STALE'}}],
  };
  const h = harness('pages/Screener.tsx', 'Screener', {
    'react-router-dom': { useSearchParams:() => [new URLSearchParams('mode=full-market')], useLocation:() => ({pathname:'/screener', hash:''}), useNavigate:() => () => {}, Link:'link' },
    '@/lib/recoveredScreener': screener, '@/lib/discoveryView':discovery,
    '@/lib/recoveredMarketApi': {recoveredMarketApi:{getFullMarket:async () => result}},
  });
  let tree = h.render();
  await testId(tree, 'run-full-market').props.onClick();
  tree = h.render();
  assert.match(label(tree), /部分可用（含过期快照）/);
  assert.match(label(tree), /当期 1 · 过期 1/);
  assert.match(label(tree), /过期排除 1/);
  const table = nodes(tree).find(node => node.type?.name === 'FullMarketResultTable');
  const rendered = table.type(table.props);
  assert.match(label(rendered), /过期快照/);
  assert.match(label(rendered), /10\.00（过期）/);
  assert.match(label(rendered), /10\.00%（过期）/);
});

test('reflection persistence failure preserves the generated text and allows retry', async () => {
  notes.addNote('test', 'Synthetic source', 'Source research');
  const h = harness('pages/Notes.tsx', 'Notes', { '@/lib/agents': { reflectStream:async (content, title, handlers) => { handlers.onDelta('Synthetic reflection'); } } });
  find(h.render(), 'button', 'Synthetic source').props.onClick();
  await find(h.render(), 'button', '反思审计').props.onClick();
  globalThis.localStorage = { ...workingStorage, setItem() { throw Error('quota'); } };
  find(h.render(), 'button', '把审计结果存为新记录').props.onClick();
  let tree = h.render();
  assert.match(label(tree), /无法保存/); assert.match(label(tree), /Synthetic reflection/);
  assert.equal(find(tree, 'button', '把审计结果存为新记录').props.disabled, false);
  globalThis.localStorage = workingStorage;
  find(tree, 'button', '把审计结果存为新记录').props.onClick();
  tree = h.render();
  assert.match(label(tree), /已存为新记录/);
  assert.equal(notes.loadNotes().length, 2);
});
test('leaving Notes aborts reflection and ignores late callbacks', async () => {
  notes.addNote('test', 'Synthetic source', 'Source research');
  const d = deferred(); let signal, callbacks;
  const h = harness('pages/Notes.tsx', 'Notes', { '@/lib/agents': { reflectStream:(content, title, handlers, s) => { signal = s; callbacks = handlers; return d.promise; } } });
  find(h.render(), 'button', 'Synthetic source').props.onClick();
  const pending = find(h.render(), 'button', '反思审计').props.onClick();
  h.unmount(); assert.equal(signal.aborted, true);
  callbacks.onDelta('STALE REFLECTION'); callbacks.onError('STALE ERROR');
  d.resolve(); await pending;
  assert.doesNotMatch(label(h.render()), /STALE/);
});

test('candidate research explicitly selects sources, saves tentative notes, and resumes from the same stock context', () => {
  const record = { id:'synthetic-evidence', subject_type:'stock', subject_id:'600519', deleted:0, claim:'Synthetic uncertainty', source_title:'Synthetic source', source_date:null, source_url:'https://example.com/research', classification:'unknown', confidence:'low' };
  const returnTo = '/candidates/600519?return_to=%2Fscreener%3Fstrategy%3DSWING';
  const props = { code:'600519', records:[record], evidenceStatus:'ready', returnTo, suggestedQuestion:'What should be checked?' };
  const h = harness('components/campaign/CandidateResearchNote.tsx', 'CandidateResearchNote');
  let tree = h.render(props);
  let ai = nodes(tree).find(node => node.props?.scopeKey === '600519');
  assert.match(ai.props.context, /没有选择证据/);
  assert.doesNotMatch(ai.props.context, /Synthetic uncertainty/);
  nodes(tree).find(node => node.type === 'input' && node.props.type === 'checkbox').props.onChange({target:{checked:true}});
  find(tree, 'button', '使用建议问题').props.onClick();
  tree = h.render(props);
  ai = nodes(tree).find(node => node.props?.scopeKey === '600519');
  assert.match(ai.props.context, /Synthetic uncertainty/);
  assert.equal(ai.props.initialQuestion, 'What should be checked?');
  assert.equal(ai.props.noteMetadata.sourceLinks[0].url, record.source_url);
  nodes(tree).find(node => node.type === 'textarea' && node.props.placeholder.includes('下次打开')).props.onChange({target:{value:'Check the actual filing'}});
  tree = h.render(props);
  find(tree, 'button', '保存暂定研究').props.onClick();
  tree = h.render(props);
  assert.match(label(tree), /已保存暂定研究/);
  assert.match(label(tree), /Check the actual filing/);
  const saved = notes.loadNotes()[0];
  assert.equal(saved.research.securityCode, '600519');
  assert.equal(saved.research.question, 'What should be checked?');
  assert.equal(saved.research.nextQuestion, 'Check the actual filing');
  assert.equal(saved.research.returnTo, returnTo + '#candidate-research-note');
  const reloaded = harness('components/campaign/CandidateResearchNote.tsx', 'CandidateResearchNote');
  assert.match(label(reloaded.render(props)), /Check the actual filing/);
  assert.doesNotMatch(label(harness('components/campaign/CandidateResearchNote.tsx', 'CandidateResearchNote').render({...props, code:'000001'})), /Check the actual filing/);
  const params = new URLSearchParams({security_code:'600519', note:saved.id});
  const notebook = harness('pages/Notes.tsx', 'Notes', {'react-router-dom':{useSearchParams:()=>[params,()=>{}], Link:'link'}});
  const noteTree = notebook.render();
  assert.match(label(noteTree), /用户暂定记录，尚未核验/);
  assert.equal(find(noteTree, 'link', '回到当时的研究位置').props.to, saved.research.returnTo);
});

test('candidate note save failure stays retryable and never claims a record was saved', () => {
  const h = harness('components/campaign/CandidateResearchNote.tsx', 'CandidateResearchNote');
  const props = {code:'600519', records:[], evidenceStatus:'error', returnTo:'/candidates/600519'};
  let tree = h.render(props);
  assert.match(label(tree), /证据读取失败/);
  nodes(tree).find(node => node.type === 'textarea' && node.props.placeholder.includes('目前')).props.onChange({target:{value:'Tentative user view'}});
  tree = h.render(props);
  globalThis.localStorage = {...workingStorage, setItem(){throw Error('quota');}};
  find(tree, 'button', '保存暂定研究').props.onClick();
  tree = h.render(props);
  assert.match(label(tree), /无法保存/);
  assert.doesNotMatch(label(tree), /已保存暂定研究/);
  assert.equal(notes.loadNotes().length, 0);
  globalThis.localStorage = workingStorage;
  find(tree, 'button', '保存暂定研究').props.onClick();
  assert.equal(notes.loadNotes().length, 1);
});

test('reflection of a stock-tagged note stays in the filtered research context without becoming a user conclusion', async () => {
  const metadata = {securityCode:'600519', question:'Original question', sourceLinks:[{title:'Synthetic source', url:'https://example.com/source'}], returnTo:'/candidates/600519#candidate-research-note', tentativeView:'User view', nextQuestion:'User next step'};
  const saved = notes.addNote('暂定研究', 'Stock-tagged note', 'Synthetic user view', metadata)[0];
  const params = new URLSearchParams({security_code:'600519', note:saved.id});
  const h = harness('pages/Notes.tsx', 'Notes', {
    'react-router-dom':{useSearchParams:()=>[params,()=>{}], Link:'link'},
    '@/lib/agents':{reflectStream:async (_content, _title, handlers)=>handlers.onDelta('Synthetic AI audit')},
  });
  await find(h.render(), 'button', '反思审计').props.onClick();
  find(h.render(), 'button', '把审计结果存为新记录').props.onClick();
  assert.match(label(h.render()), /反思 · Stock-tagged note/);
  const audit = notes.loadNotes()[0];
  assert.equal(audit.kind, '反思审计');
  assert.equal(audit.research.securityCode, '600519');
  assert.equal(audit.research.question, metadata.question);
  assert.deepEqual(audit.research.sourceLinks, metadata.sourceLinks);
  assert.equal(audit.research.returnTo, metadata.returnTo);
  assert.equal(audit.research.tentativeView, undefined);
  assert.equal(audit.research.nextQuestion, undefined);
  const candidate = harness('components/campaign/CandidateResearchNote.tsx', 'CandidateResearchNote');
  const tree = candidate.render({code:'600519', records:[], evidenceStatus:'ready', returnTo:'/candidates/600519'});
  assert.match(label(tree), /反思 · Stock-tagged noteAI 原文，未经用户确认/);
});


test('Settings manual probe uses unsaved form values and changing an API key cancels stale success', async () => {
  llm.saveLlm(dummyConfig);
  const before = storage.get('vr-llm');
  const pending = deferred(); const calls = []; let signal;
  const { h } = settingsHarness({}, { testModelConnection: (cfg, s) => { calls.push(cfg); signal=s; return pending.promise; } });
  h.render(); await tick();
  let tree=h.render(); assert.equal(calls.length,0);
  testId(tree,'wave5-model-input').props.onChange({target:{value:'unsaved-probe-model'}});
  tree=h.render(); testId(tree,'model-connection-test-start').props.onClick();
  testId(tree,'model-connection-test-start').props.onClick();
  assert.equal(calls.length,1); assert.equal(calls[0].model,'unsaved-probe-model');
  assert.equal(storage.get('vr-llm'),before);
  tree=h.render(); testId(tree,'wave5-api-key-input').props.onChange({target:{value:'changed-fixture'}});
  assert.equal(signal.aborted,true); pending.resolve({}); await tick();
  assert.equal(testId(h.render(),'model-connection-test-result'),undefined);
  assert.equal(storage.get('vr-llm'),before); h.unmount();
});

test('Settings cancellation is visible, and changing backend access key disables probing until saved', async () => {
  llm.saveLlm(dummyConfig);
  const pending=deferred(); let signal; let calls=0;
  const {h}=settingsHarness({}, {testModelConnection:(_cfg,s)=>{calls++;signal=s;return pending.promise;}});
  h.render(); await tick(); let tree=h.render();
  testId(tree,'model-connection-test-start').props.onClick();
  tree=h.render(); testId(tree,'model-connection-test-cancel').props.onClick();
  assert.equal(signal.aborted,true); pending.resolve({}); await tick();
  assert.match(label(h.render()),/已停止等待/);
  tree=h.render(); nodes(tree).find(n=>n.type==='input' && n.props.placeholder?.includes('VR_API_KEY')).props.onChange({target:{value:'UNSAVED-BACKEND-KEY'}});
  assert.equal(testId(h.render(),'model-connection-test-start').props.disabled,true);
  assert.equal(calls,1); h.unmount();
});

const accessInput = tree => nodes(tree).find(n => n.type === 'input' && n.props.placeholder?.includes('VR_API_KEY'));
const saveAccessButton = tree => nodes(tree).find(n => n.type === 'button' && label(n) === '保存');

test('Settings saved access key schedules a render even when the draft is already trimmed', async () => {
  llm.saveLlm(dummyConfig);
  const { h } = settingsHarness(); h.render(); await tick();
  let tree = h.flushScheduled();
  for (const value of ['SYNTHETIC_FIRST', 'SYNTHETIC_SECOND', '']) {
    accessInput(tree).props.onChange({ target: { value } }); tree = h.flushScheduled();
    assert.equal(testId(tree, 'model-connection-test-start').props.disabled, true);
    saveAccessButton(tree).props.onClick(); tree = h.flushScheduled();
    assert.equal(apiClient.loadAccessKey(), value);
    assert.equal(testId(tree, 'model-connection-test-start').props.disabled, false);
    assert.doesNotMatch(label(tree), /后端访问密钥修改后需先保存/);
  }
  h.unmount();
});

test('Settings failed access save retains the old confirmed value and stays blocked until retry', async () => {
  llm.saveLlm(dummyConfig); apiClient.saveAccessKey('SYNTHETIC_OLD');
  const { h, messages } = settingsHarness(); h.render(); await tick();
  let tree = h.flushScheduled();
  accessInput(tree).props.onChange({ target: { value: 'SYNTHETIC_NEW' } }); tree = h.flushScheduled();
  globalThis.localStorage = { ...workingStorage, setItem() { throw Error('denied'); } };
  saveAccessButton(tree).props.onClick(); tree = h.flushScheduled();
  assert.equal(apiClient.loadAccessKey(), 'SYNTHETIC_OLD');
  assert.equal(testId(tree, 'model-connection-test-start').props.disabled, true);
  assert.equal(messages.at(-1)[0], 'error');
  assert.equal(messages.some(([kind]) => kind === 'success'), false);
  globalThis.localStorage = workingStorage; saveAccessButton(tree).props.onClick(); tree = h.flushScheduled();
  assert.equal(testId(tree, 'model-connection-test-start').props.disabled, false); h.unmount();
});

test('Settings checks live access storage before probing and refreshes cross-tab readiness without replacing the draft', async () => {
  llm.saveLlm(dummyConfig); apiClient.saveAccessKey('SYNTHETIC_OLD'); let calls = 0;
  const { h } = settingsHarness({}, { testModelConnection: async () => { calls++; } });
  h.render(); await tick(); let tree = h.flushScheduled();
  // Stabilize shared idle state before changing storage without an event.
  testId(tree, 'wave5-model-input').props.onChange({ target: { value: 'synthetic-new-model' } }); tree = h.flushScheduled();
  apiClient.saveAccessKey('SYNTHETIC_PEER');
  testId(tree, 'model-connection-test-start').props.onClick(); await tick();
  assert.equal(calls, 0);
  h.emit('storage', { key: 'vr-access-key' }); tree = h.flushScheduled();
  assert.equal(accessInput(tree).props.value, 'SYNTHETIC_OLD');
  assert.equal(testId(tree, 'model-connection-test-start').props.disabled, true);
  apiClient.saveAccessKey('SYNTHETIC_OLD'); h.emit('storage', { key: 'vr-access-key' }); tree = h.flushScheduled();
  assert.equal(testId(tree, 'model-connection-test-start').props.disabled, false);
  apiClient.saveAccessKey(''); h.emit('storage', { key: null }); tree = h.flushScheduled();
  assert.equal(testId(tree, 'model-connection-test-start').props.disabled, true); h.unmount();
});


test('candidate unsaved guard follows only meaningful text, save success, and actual route changes', () => {
  let shouldBlock;
  const blocker = { state: 'unblocked', reset() { this.state = 'unblocked'; }, proceed() { this.state = 'proceeding'; } };
  const h = harness('components/campaign/CandidateResearchNote.tsx', 'CandidateResearchNote', {
    'react-router-dom': { Link: 'link', useBlocker: fn => { shouldBlock = fn; return blocker; } },
  });
  const props = { code:'600519', records:[], evidenceStatus:'ready', returnTo:'/candidates/600519' };
  const route = (pathname, search = '', hash = '') => ({ pathname, search, hash });
  const currentLocation = route('/candidates/600519');
  const blocks = (nextLocation = route('/notes')) => shouldBlock({currentLocation, nextLocation});
  const edit = (fieldLabel, text) => {
    const field = find(h.render(props), 'label', fieldLabel);
    nodes(field).find(node => ['input', 'textarea'].includes(node.type)).props.onChange({target:{value:text}});
    return h.render(props);
  };
  h.render(props);
  assert.equal(blocks(), false);
  assert.equal(h.hasListener('beforeunload'), false);
  edit('本次要核对的问题', '   ');
  assert.equal(blocks(), false);
  for (const field of ['本次要核对的问题', '我的暂定看法', '反证 / 不确定处', '下次核对']) {
    edit(field, 'synthetic pending research');
    assert.equal(blocks(), true, field);
    assert.equal(h.hasListener('beforeunload'), true);
    for (const destination of ['/notes', '/settings', '/evidence/fixture', '/candidates/000001']) assert.equal(blocks(route(destination)), true);
    assert.equal(blocks(route('/candidates/600519', '', '#candidate-existing-research')), false);
    assert.equal(blocks(route('/candidates/600519', '?return_to=/notes')), true);
    for (let attempt = 0; attempt < 2; attempt++) {
      blocker.state = 'blocked';
      find(h.render(props), 'button', '留下继续编辑').props.onClick();
      assert.equal(blocker.state, 'unblocked');
      assert.equal(blocks(), true);
    }
    edit(field, '');
    assert.equal(blocks(), false);
  }
  edit('我的暂定看法', 'Save this');
  const unload = {prevented:false, returnValue:undefined, preventDefault(){this.prevented=true;}};
  h.emit('beforeunload', unload);
  assert.equal(unload.prevented, true);
  assert.equal(unload.returnValue, '');
  globalThis.localStorage = {...workingStorage, setItem(){throw Error('quota');}};
  find(h.render(props), 'button', '保存暂定研究').props.onClick();
  h.render(props);
  assert.equal(blocks(), true);
  assert.equal(h.hasListener('beforeunload'), true);
  globalThis.localStorage = workingStorage;
  find(h.render(props), 'button', '保存暂定研究').props.onClick();
  h.render(props);
  assert.equal(blocks(), false);
  assert.equal(h.hasListener('beforeunload'), false);
  edit('我的暂定看法', '  Save this  ');
  assert.equal(blocks(), false);
  // Metadata refresh and changing selected evidence do not create pending text.
  h.render({...props, evidenceStatus:'loading', returnTo:'/candidates/600519?return_to=/notes'});
  assert.equal(blocks(), false);
  const evidenceProps = {...props, records:[{id:'fixture', subject_type:'stock', subject_id:'600519', deleted:0, claim:'Synthetic evidence', source_title:'Fixture', source_url:'https://example.com/source', classification:'inference', confidence:'low'}]};
  let refreshed = h.render(evidenceProps);
  nodes(refreshed).find(node => node.props?.type === 'checkbox').props.onChange({target:{checked:true}});
  h.render(evidenceProps);
  assert.equal(blocks(), false);
  h.render({...evidenceProps, records:[{...evidenceProps.records[0], source_title:'Updated fixture source'}]});
  assert.equal(blocks(), false);
  edit('我的暂定看法', 'Changed after save');
  assert.equal(blocks(), true);
  edit('我的暂定看法', 'Save this');
  assert.equal(blocks(), false);
  edit('下次核对', 'New question');
  blocker.state = 'blocked';
  find(h.render(props), 'button', '放弃未保存内容并离开').props.onClick();
  assert.equal(blocker.state, 'proceeding');
  h.unmount();
  assert.equal(h.hasListener('beforeunload'), false);
});

test('failed reflection keeps partial text but cannot reuse previous completion to save', async () => {
  notes.addNote('test', 'Synthetic source', 'Source research');
  let fail = false;
  const h = harness('pages/Notes.tsx', 'Notes', { '@/lib/agents': { reflectStream:async (_content, _title, handlers) => {
    handlers.onDelta(fail ? 'INCOMPLETE AUDIT' : 'complete audit');
    if (fail) throw new apiClient.ApiError('反思未完整结束', 502);
    handlers.onDone('complete audit', true);
  } } });
  find(h.render(), 'button', 'Synthetic source').props.onClick();
  await find(h.render(), 'button', '反思审计').props.onClick();
  assert.match(label(h.render()), /未覆盖全文/);
  find(h.render(), 'button', '把审计结果存为新记录').props.onClick();
  assert.match(notes.loadNotes().find(n=>n.kind==='反思审计').content, /未覆盖全文/);
  fail = true;
  await nodes(h.render()).find(node => node.type === 'button' && label(node) === '反思审计').props.onClick();
  const tree = h.render();
  assert.match(label(tree), /INCOMPLETE AUDIT/);
  assert.match(label(tree), /反思未完整结束/);
  assert.equal(find(tree, 'button', '把审计结果存为新记录'), undefined);
  assert.equal(notes.loadNotes().length, 2);
});

test('partial report upload refreshes confirmed successes and identifies the failed file', async t => {
  const previousReader = globalThis.FileReader;
  globalThis.FileReader = class { readAsDataURL() { this.result='data:text/plain;base64,eA=='; this.onload(); } };
  t.after(()=>{globalThis.FileReader=previousReader;});
  const calls=[]; let loads=0;
  const success={id:'uploaded',name:'first.txt',title:'Uploaded first',size:1,ts:1};
  const h=reportHarness(async()=>[], {
    myReports:async()=>{loads++;return loads>1?[success]:[];},
    uploadReport:async name=>{calls.push(name);if(name==='second.txt')throw new apiClient.ApiError('synthetic rejection',400);return success;},
  });
  h.render(); await tick();
  nodes(h.render()).find(node=>node.type==='input' && node.props.type==='file').props.onChange({target:{files:[{name:'first.txt'},{name:'second.txt'},{name:'third.txt'}],value:'files'}});
  await tick();
  assert.deepEqual(calls,['first.txt','second.txt']);
  assert.equal(loads,2);
  const tree=h.render();
  assert.match(label(tree),/Uploaded first/);
  assert.match(label(tree),/已上传 1/);
  assert.match(label(tree),/second.txt/);
  assert.match(label(tree),/synthetic rejection/);
  assert.doesNotMatch(label(tree),/还没有归档/);
});

test('report upload blocks overlapping batches and reports failed refresh without claiming rollback', async t => {
  const previousReader=globalThis.FileReader;
  globalThis.FileReader=class {readAsDataURL(){this.result='data:text/plain;base64,eA==';this.onload();}};
  t.after(()=>{globalThis.FileReader=previousReader;});
  const first=deferred();const calls=[];let loads=0;
  const h=reportHarness(async()=>[], {
    myReports:async()=>{if(++loads>1)throw new apiClient.ApiError('offline',500);return[];},
    uploadReport:async name=>{calls.push(name);if(name==='first.txt')return first.promise;throw new apiClient.ApiError('rejected',400);},
  });
  h.render();await tick();
  const input=()=>nodes(h.render()).find(node=>node.type==='input'&&node.props.type==='file');
  input().props.onChange({target:{files:[{name:'first.txt'},{name:'bad.txt'}],value:''}});await tick();
  input().props.onChange({target:{files:[{name:'duplicate.txt'}],value:''}});await tick();
  assert.deepEqual(calls,['first.txt']);
  first.resolve({id:'first'});await tick();
  assert.deepEqual(calls,['first.txt','bad.txt']);
  assert.match(label(h.render()),/已上传 1/);
  assert.match(label(h.render()),/列表刷新失败/);
  assert.doesNotMatch(label(h.render()),/还没有归档/);
});

for(const staleError of [false,true])test(`report upload refresh survives obsolete initial ${staleError?'error':'empty response'}`,async t=>{
  const previousReader=globalThis.FileReader;
  globalThis.FileReader=class {readAsDataURL(){this.result='data:text/plain;base64,eA==';this.onload();}};
  t.after(()=>{globalThis.FileReader=previousReader;});
  const initial=deferred();let loads=0;
  const report={id:'fresh-upload',name:'fresh.txt',title:'FRESH UPLOAD',size:1,ts:1};
  const h=reportHarness(async()=>[],{
    myReports:()=>++loads===1?initial.promise:Promise.resolve([report]),
    uploadReport:async()=>report,
  });
  h.render();
  nodes(h.render()).find(node=>node.type==='input'&&node.props.type==='file').props.onChange({target:{files:[{name:'fresh.txt'}],value:''}});
  await tick();assert.match(label(h.render()),/FRESH UPLOAD/);
  if(staleError)initial.reject(new apiClient.ApiError('STALE LIST ERROR',500));else initial.resolve([]);
  await tick();
  assert.match(label(h.render()),/FRESH UPLOAD/);
  assert.doesNotMatch(label(h.render()),/STALE LIST ERROR|还没有归档/);
});

test('active report search refreshes after successful batch indexing',async()=>{
  let indexed=false, searches=0;
  const h=reportHarness(async()=>{searches++;return indexed?[{report_id:'indexed',title:'NEWLY INDEXED',snippet:'audit',page:1}]:[];},{
    previewMyReportTextIndex:async()=>({items:[{eligible:true,report_id:'indexed'}]}),
    batchIndexMyReportText:async()=>{indexed=true;return{};},
  });
  h.render();await tick();query(h,'audit');h.flushTimers();await tick();
  assert.match(label(h.render()),/没有匹配/);
  await find(h.render(),'button','索引旧研报').props.onClick();
  h.render();h.flushTimers();await tick();
  assert.equal(searches,2);
  assert.match(label(h.render()),/NEWLY INDEXED/);
});

test('failed report indexing preserves current search and does not invent a refresh',async()=>{
  let searches=0;
  const h=reportHarness(async()=>{searches++;return[{report_id:'existing',title:'EXISTING RESULT',snippet:'audit',page:1}];},{
    previewMyReportTextIndex:async()=>({items:[{eligible:true,report_id:'existing'}]}),
    batchIndexMyReportText:async()=>{throw new apiClient.ApiError('INDEX FAILURE',500);},
  });
  h.render();await tick();query(h,'audit');h.flushTimers();await tick();
  await find(h.render(),'button','索引旧研报').props.onClick();h.render();h.flushTimers();await tick();
  assert.equal(searches,1);assert.match(label(h.render()),/EXISTING RESULT/);assert.match(label(h.render()),/INDEX FAILURE/);
});

test('index completion refreshes the latest query and discards older query responses',async()=>{
  const indexed=deferred(), calls=[];
  const h=reportHarness(q=>{const d=deferred();calls.push({...d,q});return d.promise;},{
    previewMyReportTextIndex:async()=>({items:[{eligible:true,report_id:'existing'}]}),
    batchIndexMyReportText:()=>indexed.promise,
  });
  h.render();await tick();query(h,'alpha');h.flushTimers();
  calls[0].resolve([]);await tick();
  const pending=find(h.render(),'button','索引旧研报').props.onClick();await tick();
  query(h,'beta');h.flushTimers();
  indexed.resolve({});await pending;h.render();h.flushTimers();
  assert.deepEqual(calls.map(c=>c.q),['alpha','beta','beta']);
  calls[2].resolve([{report_id:'fresh',title:'FRESH BETA',snippet:'beta',page:1}]);await tick();
  calls[1].resolve([{report_id:'stale',title:'OLD BETA',snippet:'beta',page:1}]);await tick();
  assert.match(label(h.render()),/FRESH BETA/);assert.doesNotMatch(label(h.render()),/OLD BETA/);
});

test('page reader invalidates old results on range, selection and SHA changes', async () => {
  const pending = [], calls = [];
  const h = harness('components/reports/ReportPageReader.tsx', 'ReportPageReader', {
    '@/lib/api': { api: { readReportPages: (body, signal) => { calls.push({ body, signal }); const d = deferred(); pending.push(d); return d.promise; } } },
  });
  let props = { reports: [{ id: 'a', name: 'A.pdf', file_sha256: 'a'.repeat(64) }] };
  let tree = h.render(props);
  find(tree, 'button', '读取指定页').props.onClick();
  tree = h.render(props);
  assert.equal(find(tree, 'button').props.disabled, true);
  nodes(tree).find(n => n.props?.['aria-label'] === '结束页').props.onChange({ target: { value: '2' } });
  tree = h.render(props);
  assert.equal(calls[0].signal.aborted, true);
  find(tree, 'button').props.onClick();
  const result = { file_sha256: 'a'.repeat(64), returned_chars: 5,
    coverage: { readable: [2], omitted: [], invalid: [], unreadable: [], error: [] },
    items: [{ page: 2, status: 'readable', reason: 'INDEXED_TEXT', text: 'fresh', returned_chars: 5, indexed_chars: 5 }] };
  pending[1].resolve(result); await tick();
  assert.match(label(h.render(props)), /fresh/);
  pending[0].resolve({ ...result, items: [{ ...result.items[0], text: 'stale' }] }); await tick();
  assert.doesNotMatch(label(h.render(props)), /stale/);
  props = { reports: [{ ...props.reports[0], file_sha256: 'b'.repeat(64) }] };
  assert.doesNotMatch(label(h.render(props)), /fresh/);
  props = { reports: [] };
  assert.equal(h.render(props), null);
  h.unmount();
});

test('page reader validates ranges, missing version, and retry without automatic AI use', async () => {
  let count = 0;
  const h = harness('components/reports/ReportPageReader.tsx', 'ReportPageReader', {
    '@/lib/api': { api: { readReportPages: async () => { count++; throw new Error('offline'); } } },
  });
  let props = { reports: [{ id: 'a', name: 'A.pdf' }] };
  let tree = h.render(props);
  assert.equal(find(tree, 'button').props.disabled, true);
  props = { reports: [{ ...props.reports[0], file_sha256: 'a'.repeat(64) }] };
  tree = h.render(props);
  assert.equal(count, 0);
  for (const value of ['-1', '1.5', '1e3', '999999999999999999999999', '201']) {
    nodes(tree).find(n => n.props?.['aria-label'] === '结束页').props.onChange({ target: { value } });
    tree = h.render(props);
    assert.equal(find(tree, 'button').props.disabled, true);
  }
  nodes(tree).find(n => n.props?.['aria-label'] === '结束页').props.onChange({ target: { value: '2' } });
  tree = h.render(props); await find(tree, 'button').props.onClick();
  tree = h.render(props); assert.match(label(tree), /读取失败/);
  await find(tree, 'button').props.onClick();
  assert.equal(count, 2);
  assert.match(label(h.render(props)), /不自动加入 AI 上下文/);
  h.unmount();
});


test('explicit page chat aborts old scope and preserves only matching complete history', async () => {
  const calls = [];
  const h = harness('components/ui/AskAiButton.tsx', 'AskAiButton', {
    'react-router-dom': { useLocation: () => ({ pathname: '/my-reports' }), Link: 'link' },
    '@/lib/storage': { storageGet: key => storage.get(key) ?? null, storageSet: (key, value) => storage.set(key, value), storageRemove: key => storage.delete(key) },
    '@/lib/llm': { ...llm, loadLlm: () => ({ provider: 'api', model: 'synthetic' }), hasLlm: () => true,
      llmIdentity: () => 'synthetic', runtimeLabel: () => 'Synthetic', chatStream: (...args) => { const d = deferred(); calls.push({ args, d }); return d.promise; } },
  });
  let props = { context: 'ignored browser hints', label: 'Explicit page AI', reportIds: ['report-a'], reportPageContext: { report_id: 'report-a', expected_file_sha256: 'a'.repeat(64), page_from: 2, page_to: 3 } };
  let tree = h.render(props); find(tree, 'button', 'Explicit page AI').props.onClick(); h.render(props); tree = h.render(props);
  find(tree, 'textarea').props.onChange({ target: { value: 'old question' } }); tree = h.render(props);
  nodes(tree).find(n => n.props?.['aria-label'] === '发送').props.onClick(); h.render(props);
  assert.deepEqual(calls[0].args[6], props.reportPageContext);
  props = { ...props, reportIds: ['report-b'], reportPageContext: { ...props.reportPageContext, report_id: 'report-b', expected_file_sha256: 'b'.repeat(64) } };
  h.render(props); tree = h.render(props);
  assert.equal(calls[0].args[3].aborted, true);
  calls[0].args[2].onDelta('STALE PAGE ANSWER'); calls[0].d.resolve({}); await tick();
  assert.doesNotMatch(label(h.render(props)), /STALE PAGE ANSWER/);
  find(tree, 'textarea').props.onChange({ target: { value: 'new question' } }); tree = h.render(props);
  nodes(tree).find(n => n.props?.['aria-label'] === '发送').props.onClick(); h.render(props);
  calls[1].args[2].onDelta('CURRENT PAGE ANSWER'); calls[1].d.resolve({}); await tick(); h.render(props);
  const stored = [...storage.entries()].filter(([key]) => key.startsWith('vr-askai-chat:'));
  assert.equal(stored.length, 1);
  assert.match(stored[0][0], /pages:report-b:b{64}:2-3/);
  assert.match(stored[0][1], /CURRENT PAGE ANSWER/);
  assert.doesNotMatch(stored[0][1], /old question|STALE PAGE/);
  tree = h.render(props);
  find(tree, 'textarea').props.onChange({ target: { value: 'cancel question' } }); tree = h.render(props);
  nodes(tree).find(n => n.props?.['aria-label'] === '发送').props.onClick(); tree = h.render(props);
  nodes(tree).find(n => n.props?.['aria-label'] === '停止生成').props.onClick();
  assert.equal(calls[2].args[3].aborted, true);
  calls[2].args[2].onDelta('LATE CANCELLED ANSWER'); calls[2].d.resolve({}); await tick(); tree = h.render(props);
  assert.doesNotMatch([...storage.values()].join(''), /cancel question|LATE CANCELLED/);
  find(tree, 'textarea').props.onChange({ target: { value: 'retry question' } }); tree = h.render(props);
  nodes(tree).find(n => n.props?.['aria-label'] === '发送').props.onClick(); h.render(props);
  calls[3].args[2].onDelta('RETRY PAGE ANSWER'); calls[3].d.resolve({}); await tick(); h.render(props);
  assert.match([...storage.values()].join(''), /RETRY PAGE ANSWER/);
  assert.doesNotMatch([...storage.values()].join(''), /cancel question|LATE CANCELLED/);
  h.unmount();
});

function storageChatHarness() {
  const calls = [];
  const h = harness('components/ui/AskAiButton.tsx', 'AskAiButton', {
    'react-router-dom': { useLocation: () => ({ pathname: '/synthetic-chat' }), Link: 'link' },
    '@/lib/storage': preferenceStorage,
    '@/lib/llm': { ...llm, loadLlm: () => ({ provider: 'api', model: 'synthetic' }), hasLlm: () => true,
      llmIdentity: () => 'synthetic', runtimeLabel: () => 'Synthetic', chatStream: (...args) => {
        const d = deferred(); calls.push({ args, d }); return d.promise;
      } },
  });
  let props = { context: 'synthetic context', scopeKey: 'first' };
  const render = () => h.render(props);
  find(render(), 'button', '问 AI').props.onClick(); render(); render();
  return { ...h, calls, render,
    scope(value) { props = { ...props, scopeKey: value }; render(); render(); },
    send(question = 'synthetic question') {
      find(render(), 'textarea').props.onChange({ target: { value: question } });
      nodes(render()).find(n => n.props?.['aria-label'] === '发送').props.onClick(); render();
      return calls.at(-1);
    },
  };
}

test('unrelated storage changes preserve the active chat through completion and persistence', async () => {
  const h = storageChatHarness(), call = h.send();
  call.args[2].onDelta('SYNTHETIC ANSWER'); h.render();
  for (let round = 0; round < 3; round++) {
    for (const key of ['vr-sidebar', 'vr-notes', 'unrelated', 'vr-askai-chat:other', 'vr-askai-epoch:other']) {
      h.emit('storage', { key, storageArea: null }); h.render();
      assert.equal(call.args[3].aborted, false);
      assert.ok(nodes(h.render()).find(n => n.props?.['aria-label'] === '停止生成'));
    }
  }
  call.d.resolve({}); await tick(); h.render();
  assert.match(storage.get('vr-askai-chat:/synthetic-chat#first@synthetic'), /SYNTHETIC ANSWER/);
  const next = h.send('followup'); assert.equal(next.args[0].length, 3);
  h.unmount(); assert.equal(next.args[3].aborted, true);
  assert.equal(h.hasListener('storage'), false); assert.equal(h.hasListener(llm.LLM_CHANGED_EVENT), false);
});

test('relevant storage and runtime events still cancel and exclude late results from persistence', async () => {
  const chatKey = 'vr-askai-chat:/synthetic-chat#first@synthetic';
  for (const key of ['vr-llm', 'vr-access-key', null, chatKey, 'vr-askai-epoch:' + chatKey, 'runtime-event']) {
    storage.clear(); const h = storageChatHarness(), call = h.send();
    if (key === 'runtime-event') h.emit(llm.LLM_CHANGED_EVENT);
    else h.emit('storage', { key, storageArea: null });
    assert.equal(call.args[3].aborted, true);
    call.args[2].onDelta('LATE CANCELLED'); call.d.resolve({}); await tick(); h.render();
    assert.doesNotMatch([...storage.values()].join(''), /LATE CANCELLED|synthetic question/);
    const retry = h.send('retry'); retry.args[2].onDelta('RETRY COMPLETE'); retry.d.resolve({}); await tick(); h.render();
    assert.match(storage.get(chatKey), /RETRY COMPLETE/); h.unmount();
  }
});

test('storage cancellation follows the current scope instead of the initial chat key', () => {
  const h = storageChatHarness(), first = h.send(); h.scope('second');
  assert.equal(first.args[3].aborted, true);
  const second = h.send('new scope');
  for (const key of ['vr-askai-chat:/synthetic-chat#first@synthetic', 'vr-askai-epoch:vr-askai-chat:/synthetic-chat#first@synthetic']) {
    h.emit('storage', { key, storageArea: null }); assert.equal(second.args[3].aborted, false);
  }
  h.emit('storage', { key: 'vr-askai-epoch:vr-askai-chat:/synthetic-chat#second@synthetic', storageArea: null });
  assert.equal(second.args[3].aborted, true); h.unmount();
});

test('non-local storage areas cannot invalidate chat runtime', () => {
  const h = storageChatHarness(), call = h.send();
  h.emit('storage', { key: 'vr-llm', storageArea: {} });
  h.emit('storage', { key: null, storageArea: {} });
  assert.equal(call.args[3].aborted, false); h.unmount();
});

function sectorLayoutHarness(loader) {
  let params = { key: 'ai-computing', tag: 'industry' };
  const h = harness('components/sectors/SectorResearchLayout.tsx', 'SectorResearchLayout', {
    'react-router-dom': { useParams: () => params, Link: 'link', Navigate: 'navigate' },
    '@/data/sectorResearch': { ...sectorResearch, loadSectorResearchWorkspace: loader },
    '@/components/ui/PageHeader': { PageHeader: 'page-header' },
    '@/components/ui/AskAiButton': { AskAiButton: 'ask-ai' },
    './SectorResearchContent': { SectorResearchContent: 'sector-content' },
  });
  return { ...h, route(key, tag = 'industry') { params = { key, tag }; return h.render(); } };
}

test('sector layout renders navigation and AI context from the same content as all 120 columns', async () => {
  let count = 0;
  for (const key of sectorResearch.listSectorResearchKeys()) {
    const workspace = await sectorResearch.loadSectorResearchWorkspace(key);
    const h = sectorLayoutHarness(async () => workspace);
    h.route(key, workspace.defaultTag); await tick();
    for (const tag of workspace.tags) {
      const tree = h.route(key, tag.slug);
      assert.equal(find(tree, 'page-header').props.title, workspace.fullName);
      assert.equal(nodes(tree).find(n => n.type === 'link' && n.props['aria-current'] === 'page').props.children, tag.label);
      assert.equal(find(tree, 'sector-content').props.tag, tag);
      assert.equal(find(tree, 'sector-content').props.sources, workspace.sources);
      const context = find(tree, 'ask-ai').props.context;
      assert.ok(context.includes('当前栏目：' + tag.label));
      assert.ok(context.includes('内容状态：' + (tag.status === 'placeholder' ? '框架占位，尚无正式研究正文' : tag.status)));
      count++;
    }
    h.unmount();
  }
  assert.equal(count, 120);
});

test('sector layout rejects previous content before effects and ignores late success or failure after rapid switches', async () => {
  const calls = [], h = sectorLayoutHarness(key => { const d = deferred(); calls.push({ key, ...d }); return d.promise; });
  let tree = h.render(); assert.equal(find(tree, 'ask-ai'), undefined);
  calls[0].resolve(await sectorResearch.loadSectorResearchWorkspace('ai-computing')); await tick();
  assert.ok(find(h.render(), 'ask-ai').props.context.includes('芯片、服务器、网络、散热产业格局'));
  // h.route returns the render before its new effect runs.
  tree = h.route('hbm'); assert.equal(find(tree, 'sector-content'), undefined); assert.equal(find(tree, 'ask-ai'), undefined);
  tree = h.route('ai-computing'); assert.equal(find(tree, 'sector-content'), undefined);
  calls[1].resolve(await sectorResearch.loadSectorResearchWorkspace('hbm')); await tick();
  assert.equal(find(h.render(), 'sector-content'), undefined);
  calls[2].resolve(await sectorResearch.loadSectorResearchWorkspace('ai-computing')); await tick();
  tree = h.render(); assert.ok(find(tree, 'ask-ai').props.context.includes('芯片、服务器、网络、散热产业格局'));
  h.route('hbm'); h.route('ai-computing');
  calls[3].reject(Error('obsolete chunk failure')); await tick();
  assert.doesNotMatch(label(h.render()), /加载失败/);
  calls[4].resolve(await sectorResearch.loadSectorResearchWorkspace('ai-computing')); await tick();
  assert.ok(find(h.render(), 'sector-content')); h.unmount();
});

test('sector missing, failed or wrong-owner content ends loading without exposing a misleading AI context', async () => {
  const other = await sectorResearch.loadSectorResearchWorkspace('hbm');
  for (const outcome of [undefined, other, new Error('synthetic load failure')]) {
    const h = sectorLayoutHarness(async () => { if (outcome instanceof Error) throw outcome; return outcome; });
    h.render(); await tick(); const tree = h.render();
    assert.match(label(tree), /研究内容加载失败/); assert.doesNotMatch(label(tree), /加载研究内容/);
    assert.equal(find(tree, 'ask-ai'), undefined); assert.equal(find(tree, 'sector-content'), undefined); h.unmount();
  }
});
