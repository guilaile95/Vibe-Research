import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { RESEARCH_NOTE_SOURCE_BOUNDARY, researchChatSourceBoundary } from '../../src/lib/researchNote.ts';

// Actual component, synthetic hooks/JSX and module boundaries. No DOM, API or provider.
const source = readFileSync(new URL('../../src/components/ui/AskAiButton.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
export const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
export function componentModule() {
  let active;
  const context = { exports: {}, AbortController, Error,
    require: name => new Proxy({}, { get: (_, key) => active.modules[name]?.[key] ?? String(key) }),
    window: new Proxy({}, { get: (_, key) => active.events[key] }),
    document: new Proxy({}, { get: (_, key) => active.events[key] }),
  };
  vm.runInNewContext(compiled, context);
  return { component: context.exports.AskAiButton, activate(value) { active = value; } };
}
export function harness(initial = {}, module = componentModule()) {
  const slots = [], effects = [], pending = [], requests = [], writes = [], storage = new Map(), listeners = new Map();
  let index = 0, dirty = false, tree, pathname = '/myreports', runtime = 'runtime-a', props = { context: 'synthetic', scopeKey: 'A', ...initial };
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const hooks = {
    useState(initial) {
      const i = index++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { const next = typeof value === 'function' ? value(slots[i]) : value;
        if (!Object.is(next, slots[i])) { slots[i] = next; dirty = true; } }];
    },
    useRef(initial) { const i = index++; return slots[i] ??= { current: initial }; },
    useEffect(fn, deps) {
      const i = index++;
      if (!equal(effects[i]?.deps, deps)) pending.push(() => {
        effects[i]?.cleanup?.(); effects[i] = { deps, setup: fn, cleanup: fn() };
      });
    },
  };
  const events = {
    addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
  };
  const failures = { read: false, write: false, remove: false };
  const modules = {
    react: hooks,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' },
    'react-router-dom': { useLocation: () => ({ pathname }), Link: 'link' },
    '@/lib/llm': {
      LLM_CHANGED_EVENT: 'runtime-changed', loadLlm: () => ({ provider: 'synthetic' }), hasLlm: () => true,
      llmIdentity: () => runtime, runtimeLabel: () => 'synthetic', chatSessionId: key => key,
      chatStream: (...args) => new Promise((resolve, reject) => requests.push({ args, resolve, reject })),
    },
    '@/lib/storage': {
      storageGet: key => storage.get(key) ?? null,
      storageGetChecked: key => { if (failures.read) throw new Error("synthetic read failure"); return storage.get(key) ?? null; },
      storageSetChecked: (key, value) => { if (failures.write) throw new Error("synthetic quota failure"); writes.push([key, value]); storage.set(key, value); },
      storageRemoveChecked: key => { if (failures.remove) throw new Error("synthetic remove failure"); writes.push([key, null]); storage.delete(key); },
      storageSet: (key, value) => { writes.push([key, value]); storage.set(key, value); },
      storageRemove: key => { writes.push([key, null]); storage.delete(key); },
    },
    '@/lib/chatToolStatus': { parseStoredChatTools: value => value, chatToolStatusLabel: () => '', applyChatToolResult: value => value },
    '@/lib/reportChatCoverage': { parseReportChatCoverage: value => value },
    '@/lib/researchNote': { RESEARCH_NOTE_SOURCE_BOUNDARY, researchChatSourceBoundary, conversationNoteMetadata: metadata => {
      if (metadata.invalid) throw new Error('synthetic invalid metadata'); return metadata;
    }, parseNoteResearchMetadata: value => value },
    '@/lib/utils': { cn: () => '' },
    '@/lib/api': { ApiError: class ApiError extends Error {} },
  };
  const activate = () => module.activate({ modules, events });
  function render(next = {}) {
    activate();
    props = { ...props, ...next };
    let count = 0;
    do {
      if (++count > 30) throw new Error('render did not settle');
      dirty = false; index = 0; tree = module.component(props);
      while (pending.length) pending.shift()();
    } while (dirty);
    return tree;
  }
  function all(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(item => all(item));
    return [node, ...all(node.props?.children ?? null)];
  }
  const find = predicate => all(tree).find(predicate);
  const button = label => find(node => node.type === 'button' && node.props['aria-label'] === label);
  const input = () => find(node => node.type === 'textarea');
  render();
  return {
    render, requests, writes, storage, failures, all: () => all(tree),
    open() { activate(); find(node => node.type === 'button').props.onClick(); render(); },
    input: () => input()?.props.value,
    type(value) { activate(); input().props.onChange({ target: { value } }); render(); },
    click(label) { activate(); const result = button(label).props.onClick(); render(); return result; },
    route(value) { pathname = value; render(); },
    runtime(value) { activate(); runtime = value; for (const fn of listeners.get('runtime-changed') ?? []) fn(); render(); },
    replayEffects() { activate(); for (const effect of effects) effect?.cleanup?.(); for (const effect of effects) if (effect) effect.cleanup = effect.setup(); render(); },
    unmount() { activate(); for (const effect of effects) effect?.cleanup?.(); },
  };
}
