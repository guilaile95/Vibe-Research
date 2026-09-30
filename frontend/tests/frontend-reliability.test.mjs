import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import * as notes from '../src/lib/notes.ts';
import * as llm from '../src/lib/llm.ts';
import * as apiClient from '../src/lib/api.ts';
import * as models from '../src/lib/ai-models.ts';

// Component behavior in a deterministic hook runner: real TSX handlers/effects and
// storage modules, mocked network/UI dependencies. No browser or real credentials.
function harness(path, name, overrides = {}) {
  const states = [], effects = [], refs = [], timers = new Map();
  let cursor = 0, pending = [], timerId = 0;
  const React = {
    useState(init) { const i = cursor++; if (!(i in states)) states[i] = typeof init === 'function' ? init() : init; return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
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
  const mods = {
    react: React,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' },
    '@/lib/api': apiClient, '@/lib/notes': notes, ...overrides,
  };
  const exports = {};
  const js = ts.transpileModule(readFileSync(new URL('../src/' + path, import.meta.url), 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(js, {
    exports, require: name => mods[name] ?? generic, AbortController, DOMException, Error, console, URLSearchParams, Map, Set, Date,
    window: { setTimeout: fn => { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id) }, confirm: () => true,
  }, { filename: path });
  return {
    render(props = {}) { cursor = 0; const tree = exports[name](props); const current = pending; pending = []; current.forEach(fn => fn()); return tree; },
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
test('notes save returns the same bounded list that survives reload', () => {
  storage.set('vr-notes', JSON.stringify(Array.from({ length: notes.NOTES_LIMIT }, (_, i) => ({ id: String(i), kind:'test', title:'test', content:'test', ts:i }))));
  const result = notes.addNote('test', 'new', 'new');
  assert.equal(result.length, notes.NOTES_LIMIT);
  assert.deepEqual(result, notes.loadNotes());
});

function startDebate(h, code = '600519') {
  let tree = h.render(); find(tree, 'input').props.onChange({ target: { value: code } });
  tree = h.render(); return find(tree, 'button', '开始辩论').props.onClick();
}
test('completed Debate notes retain the analyzed ticker after input edits', async () => {
  let requested;
  const h = harness('pages/Debate.tsx', 'Debate', { '@/lib/agents': { debateStream: async (code, rounds, handlers) => {
    requested = code; handlers.onStageStart('bull','bull'); handlers.onStageDone('bull','bull','Research for ' + code);
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
test('failed or stopped Debate never advertises complete savable results', async () => {
  const h = harness('pages/Debate.tsx', 'Debate', { '@/lib/agents': { debateStream: async (code, rounds, handlers) => {
    handlers.onStageStart('bull','bull'); handlers.onStageDone('bull','bull','partial'); handlers.onError('provider failed');
  } } });
  await startDebate(h);
  assert.equal(find(h.render(), 'button', '存入沉淀'), undefined);
  assert.match(label(h.render()), /辩论失败/);
});

function reportHarness(search) {
  const params = new URLSearchParams();
  return harness('pages/MyReports.tsx', 'MyReports', {
    'react-router-dom': { useSearchParams: () => [params, () => {}], Link: 'link' },
    '@/data/sectors.json': { default: { sectors: [] } }, '@/lib/utils': { cn: () => '' },
    '@/lib/myReportsView': { filterReports: rows => rows, groupReportsByIndustry: () => [], groupReportsByInstitution: () => [], groupReportsByYearMonth: () => [] },
    '@/lib/api': { ...apiClient, api: { myReports: async () => [], searchMyReportText: search } },
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
function settingsHarness(overrides = {}) {
  const messages = [];
  const h = harness('pages/Settings.tsx', 'Settings', {
    '@/lib/llm': llm, '@/lib/ai-models': models,
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
