import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { createMemoryRouter } from 'react-router-dom';

const require = createRequire(import.meta.url);
const source = readFileSync(new URL('../src/router.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
} }).outputText;
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(initial = '/daily-review', fail) {
  const imports = [];
  let routes;
  const scope = { exports: {}, require(name) {
    if (name === 'react-router-dom') return { ...require(name), createBrowserRouter(value) { routes = value; return null; } };
    if (name.startsWith('@/pages/')) {
      imports.push(name);
      if (name === fail) throw new Error('synthetic import rejection https://private.invalid/token');
      const page = name.split('/').at(-1);
      return { [page]: () => React.createElement('p', null, page) };
    }
    if (name.startsWith('@/')) return new Proxy({}, { get: (_, key) => key === 'hasSectorResearchWorkspace' ? () => false : () => null });
    return require(name);
  } };
  vm.runInNewContext(compiled, scope);
  const router = createMemoryRouter(routes, { initialEntries: [initial] });
  return { router, imports, routes };
}
async function ready(router) {
  for (let i = 0; i < 50 && !router.state.initialized; i++) await tick();
  assert.equal(router.state.initialized, true);
}
test('actual route definitions load only the matched core page and retain fallback/error boundaries', async () => {
  for (const [path, name] of [['daily-review', 'DailyReview'], ['stock-data', 'StockData'], ['sectors', 'Sectors']]) {
    const { router, imports, routes } = fixture('/' + path);
    try {
      assert.equal(router.state.initialized, false);
      const route = routes[0].children.find(r => r.path === '/' + path);
      assert.ok(route.hydrateFallbackElement);
      assert.ok(route.errorElement);
      assert.equal(route.element, undefined);
      await ready(router);
      assert.deepEqual(imports, ['@/pages/' + name]);
      const resolved = router.state.matches.at(-1).route.element;
      assert.ok(resolved.props.children.type === React.Suspense);
      assert.equal(router.state.errors, null);
    } finally { router.dispose(); }
  }
});
test('route import rejection remains an error, never a successful empty page', async () => {
  const { router } = fixture('/stock-data', '@/pages/StockData');
  try {
    await ready(router);
    assert.ok(router.state.errors);
    assert.match(Object.values(router.state.errors)[0].message, /synthetic import rejection/);
    assert.ok(router.state.matches.at(-1).route.errorElement);
    assert.doesNotMatch(source.slice(source.indexOf('function RouteLoadError'), source.indexOf('function SectorResearchTagRoute')), /useRouteError|\.message|\.stack/);
  } finally { router.dispose(); }
});
test('newer navigation wins over an unresolved route; late resolution cannot replace current page', async () => {
  const { router } = fixture();
  try {
    await ready(router);
    let release;
    router.routes[0].children.find(r => r.path === '/stock-data').lazy = () => new Promise(resolve => { release = resolve; });
    const old = router.navigate('/stock-data?code=600001');
    await tick();
    assert.equal(router.state.navigation.state, 'loading');
    assert.equal(router.state.location.pathname, '/daily-review');
    await router.navigate('/sectors');
    release({ element: React.createElement('p', null, 'obsolete') });
    await old;
    assert.equal(router.state.location.pathname, '/sectors');
    await router.navigate(-1);
    assert.equal(router.state.location.pathname, '/daily-review');
  } finally { router.dispose(); }
});
test('existing data-router blocker prevents lazy import until user proceeds; cancel and back remain guarded', async () => {
  const { router, imports } = fixture();
  try {
    await ready(router);
    router.getBlocker('synthetic-draft', () => true);
    await router.navigate('/stock-data?code=600001');
    assert.equal(router.state.blockers.get('synthetic-draft').state, 'blocked');
    assert.deepEqual(imports, ['@/pages/DailyReview']);
    router.state.blockers.get('synthetic-draft').reset();
    assert.equal(router.state.location.pathname, '/daily-review');
    await router.navigate('/stock-data?code=600001');
    router.state.blockers.get('synthetic-draft').proceed();
    for (let i = 0; i < 50 && router.state.location.pathname !== '/stock-data'; i++) await tick();
    assert.equal(router.state.location.search, '?code=600001');
    await router.navigate(-1);
    await tick();
    assert.equal(router.state.blockers.get('synthetic-draft').state, 'blocked');
    assert.equal(router.state.location.pathname, '/stock-data');
  } finally { router.dispose(); }
});
