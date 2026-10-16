import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const parserExports = {};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/lib/runtimeDiagnostics.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: parserExports });
const source = ts.transpileModule(readFileSync(new URL('../src/components/settings/RuntimeDiagnosticsExport.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const nodes = v => !v || typeof v !== 'object' ? [] : Array.isArray(v) ? v.flatMap(nodes) : [v, ...nodes(v.props?.children)];
const text = v => typeof v === 'string' ? v : Array.isArray(v) ? v.map(text).join('') : text(v?.props?.children ?? '');
function harness(get) {
  let cursor = 0, tree, cleanup;
  const cells = [], requests = [], downloads = [], revoked = [], blobs = [], timers = new Set();
  const react = {
    useState(initial) { const i = cursor++; if (!(i in cells)) cells[i] = initial; return [cells[i], v => { cells[i] = v; }]; },
    useRef(initial) { const i = cursor++; if (!(i in cells)) cells[i] = { current: initial }; return cells[i]; },
    useEffect(fn) { const i = cursor++; if (!(i in cells)) { cells[i] = true; cleanup = fn(); } },
  };
  const exports = {};
  vm.runInNewContext(source, { exports, AbortController, Error, JSON, Blob,
    setTimeout(fn) { timers.add(fn); return fn; }, clearTimeout(fn) { timers.delete(fn); },
    URL: { createObjectURL(blob) { blobs.push(blob); return 'blob:synthetic'; }, revokeObjectURL(url) { revoked.push(url); } },
    document: { body: { appendChild() {} }, createElement() { return { click() { downloads.push(this.download); }, remove() {} }; } },
    require(name) {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
      if (name === '@/lib/runtimeDiagnostics') return parserExports;
      if (name === '@/lib/api') return { get: (...args) => { requests.push(args); return get(...args); } };
      throw new Error(`Unexpected import: ${name}`);
    },
  });
  const render = () => { cursor = 0; tree = exports.RuntimeDiagnosticsExport(); return tree; };
  render();
  return { requests, downloads, revoked, blobs, timers, render, get tree() { return tree; },
    click() { nodes(tree).find(n => n.type === 'button').props.onClick(); },
    button() { return nodes(tree).find(n => n.type === 'button'); },
    async settle() { await new Promise(resolve => setImmediate(resolve)); render(); },
    unmount() { cleanup(); },
  };
}
const report = JSON.parse(readFileSync(new URL('./fixtures/runtime-diagnostics.json', import.meta.url), 'utf8'));
test('actual Settings card mounts click-only diagnostics action', () => {
  assert.match(readFileSync(new URL('../src/pages/Settings.tsx', import.meta.url), 'utf8'), /<BackendRuntimeCard\s*\/>/);
  assert.match(readFileSync(new URL('../src/components/settings/BackendRuntimeCard.tsx', import.meta.url), 'utf8'), /<RuntimeDiagnosticsExport\s*\/>/);
  const h = harness(async () => report);
  assert.equal(h.requests.length, 0);
  assert.match(text(h.tree), /不读取凭据或账户资料/);
});
test('authenticated API get, duplicate click suppression, and blob cleanup', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  h.click(); h.click(); h.render();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0][0], '/runtime-diagnostics/export');
  assert.ok(h.requests[0][1].signal instanceof AbortSignal);
  assert.equal(h.button().props.disabled, true);
  resolve(report); await h.settle();
  assert.deepEqual(h.downloads, ['vibe-runtime-diagnostics.json']);
  assert.deepEqual(h.revoked, ['blob:synthetic']);
  assert.deepEqual(JSON.parse(await h.blobs[0].text()), { data: report });
  assert.equal(h.button().props.disabled, false);
  assert.equal(h.timers.size, 0);
});
test('safe error and malformed response permit retry without Settings mutation', async () => {
  let attempt = 0;
  const h = harness(async () => { attempt++; if (attempt === 1) throw new Error('private-token-path'); if (attempt === 2) return {}; return report; });
  for (let i = 0; i < 2; i++) {
    h.click(); await h.settle();
    assert.match(text(h.tree), /导出失败.*当前设置未修改/);
    assert.doesNotMatch(text(h.tree), /private-token-path/);
    assert.equal(h.downloads.length, 0);
    assert.equal(h.button().props.disabled, false);
  }
  h.click(); await h.settle(); assert.equal(h.downloads.length, 1);
});
test('unmount cancels and suppresses late download', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  h.click(); h.unmount();
  assert.equal(h.requests[0][1].signal.aborted, true);
  resolve(report); await h.settle();
  assert.equal(h.downloads.length, 0);
  assert.equal(h.timers.size, 0);
});
test('timeout cannot export a late response', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  h.click(); [...h.timers][0](); resolve(report); await h.settle();
  assert.equal(h.downloads.length, 0);
  assert.match(text(h.tree), /导出失败/);
});

for (const [label, change] of [
  ['extra top-level key', r => { r.credential = 'private'; }],
  ['extra nested key', r => { r.startup.source_directory = '/private'; }],
  ['nested credential', r => { r.configuration_presence[0].value = 'secret'; }],
  ['malformed scalar array', r => { r.agent_runtime.backend_target_port = ['secret']; }],
  ['unknown enum string', r => { r.directories.data = '/private'; }],
  ['malformed collection', r => { r.source_capabilities = 'private'; }],
  ['unverified state escalation', r => { r.agent_runtime.availability = 'VERIFIED'; }],
  ['invalid backend port zero', r => { r.agent_runtime.backend_target_port = 0; }],
  ['false port match', r => { r.agent_runtime.declared_runtime_port = 8912; }],
  ['false port mismatch', r => { r.agent_runtime.configuration_status = 'PORT_MISMATCH'; }],
  ['false dynamic port', r => { r.agent_runtime.configuration_status = 'DYNAMIC_PORT_UNVERIFIED'; }],
  ['false invalid configuration', r => { r.agent_runtime.configuration_status = 'INVALID_CONFIGURATION'; }],
]) test(`schema-valid unsafe export rejected: ${label}`, async () => {
  const malicious = structuredClone(report); change(malicious);
  const h = harness(async () => malicious); h.click(); await h.settle();
  assert.equal(h.downloads.length, 0); assert.equal(h.blobs.length, 0);
  assert.match(text(h.tree), /导出失败/);
});

test('backend-produced golden report is reconstructed without aliases', () => {
  const parsed = parserExports.parseRuntimeDiagnostics(report);
  assert.deepEqual(JSON.parse(JSON.stringify(parsed)), report);
  assert.notEqual(parsed, report);
  assert.notEqual(parsed.startup, report.startup);
});

for (const [state, target, declared] of [['PORT_MISMATCH', 8911, 8912], ['DYNAMIC_PORT_UNVERIFIED', 8911, 0], ['INVALID_CONFIGURATION', null, 8911], ['INVALID_CONFIGURATION', 8911, null]]) {
  test(`valid runtime diagnostic state: ${state}/${target}/${declared}`, () => {
    const value = structuredClone(report);
    Object.assign(value.agent_runtime, { configuration_status: state, backend_target_port: target, declared_runtime_port: declared });
    assert.doesNotThrow(() => parserExports.parseRuntimeDiagnostics(value));
  });
}
