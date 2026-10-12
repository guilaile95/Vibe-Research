import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const compile = file => ts.transpileModule(fs.readFileSync(new URL(file, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const parser = {};
vm.runInNewContext(compile('../src/lib/platformSettings.ts'), { exports: parser, require: () => ({ request: () => { throw Error('No network allowed'); } }), AbortSignal, Date });
const contact = { source: 'none', configured: false, revision: 'absent', editable: true };
const update = { repository: 'guilaile95/Vibe-Research', current: '0.1.3', mode: 'manual_only', status: 'not_checked', checked_at: null, latest: null };
const fixture = { schema: 'platform_settings.v1', sec_contact: contact, update, sec_provider: 'not_connected', can_check_update: true, platforms: { windows: 'existing_launcher', linux: 'existing_user_space_launcher', macos: 'unsupported_launcher' } };
test('strict response parser strips extras, rejects source/status/date/version aliases', () => {
  assert.doesNotMatch(JSON.stringify(parser.parsePlatformSettings({ ...fixture, secret: 'SYNTHETIC' })), /SYNTHETIC/);
  for (const patch of [{ source: 'remote' }, { configured: 'yes' }, { revision: 1 }, { source: 'environment' }, { source: 'saved' }]) assert.throws(() => parser.parseContact({ ...contact, ...patch }));
  const valid = { ...update, checked_at: '2026-10-12T12:00:00Z', status: 'update_available', latest: { version: '0.1.4', url: 'https://github.com/guilaile95/Vibe-Research/releases/tag/v0.1.4', published_at: '2026-10-11T12:00:00Z' } };
  assert.equal(parser.parseUpdate(valid).status, 'update_available');
  for (const patch of [{ repository: 'attacker/repo' }, { current: null }, { current: '01.2.3' }, { current: '0.1.3\n' }, { status: 'current' }, { checked_at: '2026-02-30T12:00:00Z' }, { checked_at: '2026-1-2T12:00:00Z' }, { mode: 'automatic' }]) assert.throws(() => parser.parseUpdate({ ...valid, ...patch }));
  for (const patch of [{ url: 'https://evil.invalid' }, { url: valid.latest.url + '\n' }, { version: '0.1.4-rc1' }, { published_at: '2026-10-13T00:00:00Z' }, { published_at: '2026-02-30T00:00:00Z' }]) assert.throws(() => parser.parseUpdate({ ...valid, latest: { ...valid.latest, ...patch } }));
});
const source = compile('../src/components/settings/PlatformSettingsCard.tsx');
const tick = () => new Promise(done => setImmediate(done));
const nodes = v => !v || typeof v !== 'object' ? [] : Array.isArray(v) ? v.flatMap(nodes) : [v, ...nodes(v.props?.children)];
const text = v => v == null || typeof v === 'boolean' ? '' : typeof v === 'string' || typeof v === 'number' ? String(v) : Array.isArray(v) ? v.map(text).join('') : text(v.props?.children);
function harness(initialRead) {
  let reads = 0;
  let cursor = 0, dirty = true, tree, readFailure = false, saveFailure = false, checkFailure = false, saved = structuredClone(fixture), writes = [], checks = 0;
  const cells = [], effects = [];
  const react = {
    useRef(initial) { const i = cursor++; if (!(i in cells)) cells[i] = { current: initial }; return cells[i]; },
    useState(initial) { const i = cursor++; if (!(i in cells)) cells[i] = initial; return [cells[i], next => { const v = typeof next === 'function' ? next(cells[i]) : next; if (!Object.is(v, cells[i])) { cells[i] = v; dirty = true; } }]; },
    useEffect(fn, deps) { const i = cursor++; if (!cells[i]) { cells[i] = { deps }; effects.push(() => { cells[i].cleanup = fn(); }); } },
  };
  const api = {
    read: async () => { if (++reads === 1 && initialRead) return initialRead; if (readFailure) throw Error('PRIVATE'); return structuredClone(saved); },
    save: async (draft, revision) => { writes.push({ draft, revision }); saved.sec_contact = { source: draft ? 'saved' : 'none', configured: Boolean(draft), revision: 'a'.repeat(32), editable: true }; if (saveFailure) throw Error('lost response PRIVATE'); return saved.sec_contact; },
    check: async () => { checks++; if (checkFailure) throw Error('PRIVATE'); return { ...update, status: 'release_not_found', checked_at: '2026-10-12T12:00:00Z' }; },
  };
  const exports = {}, modules = { react, 'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }, '@/components/ui/GlassCard': { GlassCard: 'card' }, '@/lib/platformSettings': { platformSettingsApi: api } };
  vm.runInNewContext(source, { exports, Error, require: name => { if (!modules[name]) throw Error(`Unexpected module ${name}`); return modules[name]; } });
  return { writes, get checks() { return checks; }, get tree() { return tree; }, get saved() { return saved; }, setReadFailure: v => { readFailure = v; }, setSaveFailure: v => { saveFailure = v; }, setCheckFailure: v => { checkFailure = v; }, button: label => nodes(tree).find(n => n.type === 'button' && text(n) === label), input: () => nodes(tree).find(n => n.type === 'input'),
    async flush() { await tick(); for (let i = 0; i < 20 && dirty; i++) { dirty = false; cursor = 0; tree = exports.PlatformSettingsCard(); for (const effect of effects.splice(0)) effect(); await tick(); } assert.equal(dirty, false); },
    unmount() { cells.forEach(cell => cell?.cleanup?.()); },
  };
}
test('actual JSX: failed initial read disables mutation and never checks automatically', async () => {
  const h = harness(); h.setReadFailure(true); await h.flush();
  assert.equal(h.button('保存联系方式').props.disabled, true); assert.equal(h.button('手动检查正式版本').props.disabled, true);
  h.button('保存联系方式').props.onClick(); await h.flush(); assert.equal(h.writes.length, 0); assert.equal(h.checks, 0); assert.match(text(h.tree), /读取设置失败/); h.unmount();
});
test('actual JSX: dirty draft survives refresh and uncertain save, readback recovery requires explicit retry', async () => {
  const h = harness(); await h.flush();
  h.input().props.onChange({ target: { value: 'Synthetic User synthetic@example.invalid' } }); await h.flush();
  h.button('重新读取状态').props.onClick(); await h.flush(); assert.equal(h.input().props.value, 'Synthetic User synthetic@example.invalid');
  h.setSaveFailure(true); h.button('保存联系方式').props.onClick(); await h.flush();
  assert.equal(h.button('保存联系方式').props.disabled, true); assert.equal(h.input().props.value, 'Synthetic User synthetic@example.invalid'); assert.match(text(h.tree), /保存未确认/); assert.doesNotMatch(text(h.tree), /PRIVATE/);
  h.button('重新读取状态').props.onClick(); await h.flush(); assert.equal(h.input().props.value, 'Synthetic User synthetic@example.invalid'); assert.match(text(h.tree), /不能确认先前草稿已保存/);
  h.setSaveFailure(false); // a later write must get a fresh revision, just like the real store
  h.saved.sec_contact.revision = 'b'.repeat(32); h.button('重新读取状态').props.onClick(); await h.flush();
  h.button('保存联系方式').props.onClick(); await h.flush(); assert.match(text(h.tree), /已保存并回读确认/); assert.equal(h.input().props.value, ''); assert.equal(h.checks, 0); h.unmount();
});
test('actual JSX: manual update failure clears previous result without claiming current', async () => {
  const h = harness(); await h.flush(); h.button('手动检查正式版本').props.onClick(); await h.flush(); assert.equal(h.checks, 1); assert.match(text(h.tree), /未取得正式版本/);
  h.setCheckFailure(true); h.button('手动检查正式版本').props.onClick(); await h.flush(); assert.match(text(h.tree), /更新检查未确认/); assert.doesNotMatch(text(h.tree), /PRIVATE|未取得正式版本/); h.unmount();
});

test('actual JSX: repeated same-render actions issue one save/check only', async () => {
  const h = harness(); await h.flush();
  h.input().props.onChange({ target: { value: 'Synthetic User synthetic@example.invalid' } }); await h.flush();
  const save = h.button('保存联系方式').props.onClick; save(); save(); await h.flush(); assert.equal(h.writes.length, 1); assert.match(text(h.tree), /已保存并回读确认/);
  const check = h.button('手动检查正式版本').props.onClick; check(); check(); await h.flush(); assert.equal(h.checks, 1); h.unmount();
});

test('actual JSX: late initial read cannot overwrite explicit newer refresh', async () => {
  let resolve; const pending = new Promise(done => { resolve = done; });
  const h = harness(pending); await h.flush();
  h.button('重新读取状态').props.onClick(); await h.flush();
  assert.equal(h.input().props.disabled, false);
  resolve({ ...fixture, sec_contact: { source: 'environment', configured: true, revision: 'environment', editable: false } }); await h.flush();
  assert.equal(h.input().props.disabled, false); assert.doesNotMatch(text(h.tree), /由环境变量管理/); h.unmount();
});
