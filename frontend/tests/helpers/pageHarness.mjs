import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const root = new URL('../../', import.meta.url);

// Run the actual page's hooks, handlers and JSX with deferred synthetic API calls.
// Child presentation components stay inert; no browser, storage or network exists.
export function pageHarness(file, exportName, initialParams = {}) {
  const slots = [], effects = [], pending = [], requests = [];
  let index = 0, dirty = false, tree, params = initialParams, search = new URLSearchParams();
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const hooks = {
    useState(value) {
      const i = index++;
      if (!(i in slots)) slots[i] = typeof value === 'function' ? value() : value;
      return [slots[i], value => {
        const next = typeof value === 'function' ? value(slots[i]) : value;
        if (!Object.is(next, slots[i])) { slots[i] = next; dirty = true; }
      }];
    },
    useRef(value) { const i = index++; return slots[i] ??= {current: value}; },
    useCallback(fn, deps) {
      const i = index++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = {fn, deps};
      return slots[i].fn;
    },
    useEffect(fn, deps) {
      const i = index++;
      if (!equal(effects[i]?.deps, deps)) pending.push(() => {
        effects[i]?.cleanup?.(); effects[i] = {deps, cleanup: fn()};
      });
    },
  };
  const api = new Proxy({}, {get: (_, name) => (...args) => new Promise((resolve, reject) => requests.push({name, args, resolve, reject}))});
  const modules = {
    react: hooks,
    'react/jsx-runtime': {jsx: (type, props) => ({type, props}), jsxs: (type, props) => ({type, props}), Fragment: 'fragment'},
    'react-router-dom': {useParams: () => params, useSearchParams: () => [search, value => { search = value; dirty = true; }], Link: 'link'},
    '@/lib/api': {api, ApiError: class extends Error {}},
    '@/lib/internalReturnTo': {safeInternalReturnTo: (_, fallback) => fallback},
    '@/lib/utils': {cn: () => ''},
  };
  const ctx = {exports: {}, URLSearchParams, Error, require: name => new Proxy({}, {
    get: (_, key) => modules[name]?.[key] ?? ((...args) => typeof args[0] === 'string' ? args[0] : null),
  })};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(file, root), 'utf8'), {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText, ctx);
  const all = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(all) : [node, ...all(node.props?.children)];
  function render() {
    let count = 0;
    do {
      if (++count > 30) throw new Error('Render did not settle');
      dirty = false; index = 0; tree = ctx.exports[exportName]();
      while (pending.length) pending.shift()();
    } while (dirty);
    return tree;
  }
  render();
  return {
    requests, slots, render, all: () => all(tree),
    unmount() { for (const effect of effects) effect?.cleanup?.(); },
    params(value) { params = value; render(); },
    search(value) { search = new URLSearchParams(value); render(); },
  };
}
