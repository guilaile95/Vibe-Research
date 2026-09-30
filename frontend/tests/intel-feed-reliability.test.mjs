import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { ApiError } from '../src/lib/api.ts';

// Run the real component's hooks and event handlers with deterministic network
// results. Rendered browser coverage lives in native-intel.browser.mjs.
function harness({ watch = async () => validWatch(), quote = async () => ({}), announcements = async () => [], news = async () => [] } = {}) {
  const slots = [], effects = [];
  let cursor = 0, pending = [], writes = 0;
  const same = (left, right) => left && right && left.length === right.length && left.every((value, i) => Object.is(value, right[i]));
  const React = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], (next) => { writes++; slots[i] = typeof next === 'function' ? next(slots[i]) : next; }];
    },
    useRef(initial) { const i = cursor++; return slots[i] ??= { current: initial }; },
    useCallback(callback, deps) {
      const i = cursor++;
      if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { deps, callback };
      return slots[i].callback;
    },
    useEffect(callback, deps) {
      const i = cursor++;
      if (!effects[i] || !same(effects[i].deps, deps)) pending.push(() => {
        effects[i]?.cleanup?.(); effects[i] = { deps, cleanup: callback() };
      });
    },
  };
  const stub = new Proxy({}, { get: (_, key) => key === '__esModule' ? true : key === 'default' ? 'stub' : () => null });
  const modules = {
    react: React,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    '@/lib/api': { ApiError, api: { quote, announcements, news } },
    '@/lib/watchlist': { loadWatchAuthoritative: watch },
  };
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL('../src/pages/Intel.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(source, { exports, require: (name) => modules[name] ?? stub }, { filename: 'Intel.tsx' });
  return {
    render(kind = 'news') { cursor = 0; const tree = exports.WatchlistFeed({ kind }); const queue = pending; pending = []; queue.forEach((run) => run()); return tree; },
    unmount() { effects.forEach((effect) => effect?.cleanup?.()); },
    writes: () => writes,
  };
}
const validWatch = (codes = ['000001']) => ({ codes, etag: 'test', status: 'valid', migrated: false });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise((resolve) => setImmediate(resolve));
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return Array.isArray(tree) ? tree.map(text).join('') : text(tree.props?.children);
}
function nodes(tree) {
  if (tree == null || typeof tree !== 'object') return [];
  return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
}
const button = (tree, label) => nodes(tree).find((node) => node.type === 'button' && text(node) === label);
const alerts = (tree) => nodes(tree).filter((node) => node.props?.role === 'alert');
const unsafe = 'ProxyError https://provider.invalid/?token=secret SQL SELECT traceback';

for (const kind of ['filings', 'news']) {
  const label = kind === 'filings' ? '公告' : '新闻';
  test(`${kind}: loading is not an empty watchlist, and successful empty remains distinct`, async () => {
    const pending = deferred();
    const h = harness({ watch: () => pending.promise });
    let tree = h.render(kind);
    assert.match(text(tree), /正在汇总/);
    assert.doesNotMatch(text(tree), /还没有关注股票|近期暂无/);
    pending.resolve(validWatch());
    await tick();
    tree = h.render(kind);
    assert.match(text(tree), new RegExp(`关注列表里的个股近期暂无${label}`));
    assert.equal(alerts(tree).length, 0);
  });

  test(`${kind}: all failures show safe errors and recover through retry`, async () => {
    let fail = true, calls = 0;
    const fetch = async () => { calls++; if (fail) throw new ApiError(unsafe, 502); return []; };
    const h = harness({ announcements: fetch, news: fetch });
    h.render(kind); await tick();
    let tree = h.render(kind);
    assert.match(text(tree), new RegExp(`${label}加载失败（1/1 只）`));
    assert.equal(alerts(tree).length, 1);
    assert.doesNotMatch(text(tree), /近期暂无|https:|ProxyError|SQL|traceback/);
    assert.equal(button(tree, '重试').props.disabled, false);
    fail = false; button(tree, '重试').props.onClick(); await tick();
    tree = h.render(kind);
    assert.equal(calls, 2);
    assert.equal(alerts(tree).length, 0);
    assert.match(text(tree), new RegExp(`近期暂无${label}`));
  });

  test(`${kind}: partial failure preserves successful rows and does not claim a full count`, async () => {
    const fetch = async (code) => {
      if (code === '000002') throw new ApiError(unsafe, 502);
      return kind === 'filings' ? [{ title: 'Synthetic announcement', date: '2026-09-30', type: '公告', url: '' }]
        : [{ 新闻标题: 'Synthetic news', 发布时间: '2026-09-30 10:00' }];
    };
    const h = harness({ watch: async () => validWatch(['000001', '000002']), announcements: fetch, news: fetch });
    h.render(kind); await tick();
    const tree = h.render(kind);
    assert.match(text(tree), new RegExp(`部分${label}加载失败（1/2 只）`));
    assert.match(text(tree), /Synthetic/);
    assert.match(text(tree), /已获取 1 条/);
    assert.doesNotMatch(text(tree), /近期暂无|https:|SQL/);
  });

  test(`${kind}: successful empty plus a failed stock is partial, not globally empty`, async () => {
    const fetch = async (code) => { if (code === '000002') throw Error(unsafe); return []; };
    const h = harness({ watch: async () => validWatch(['000001', '000002']), announcements: fetch, news: fetch });
    h.render(kind); await tick();
    const tree = h.render(kind);
    assert.equal(alerts(tree).length, 1);
    assert.match(text(tree), /其余个股尚未获取成功/);
    assert.doesNotMatch(text(tree), /关注列表里的个股近期暂无/);
  });

  test(`${kind}: malformed successful response is an error, not empty or a render crash`, async () => {
    for (const malformed of [null, {}, [null], [{}], [{ title: 23, 新闻标题: 23 }], [{ title: 'valid', date: {}, type: '', url: '' }], [{ 新闻标题: 'valid', 发布时间: {} }]]) {
      const h = harness({ announcements: async () => malformed, news: async () => malformed });
      h.render(kind); await tick();
      const tree = h.render(kind);
      assert.match(text(tree), /加载失败/);
      assert.doesNotMatch(text(tree), /近期暂无/);
    }
  });
}

test('not configured and valid empty watchlists are legitimate empty states', async () => {
  for (const status of ['not_configured', 'valid']) {
    const h = harness({ watch: async () => ({ ...validWatch([]), status }) });
    h.render(); await tick();
    const tree = h.render();
    assert.match(text(tree), /还没有关注股票/);
    assert.equal(alerts(tree).length, 0);
    assert.ok(button(tree, '刷新'));
  }
});

test('watchlist fetch failure, corrupted state and malformed codes stay retryable', async () => {
  for (const failure of [null, { ...validWatch([]), status: 'corrupted' }, { ...validWatch(), codes: null }, { ...validWatch(), codes: ['bad'] }]) {
    let recovered = false, feedCalls = 0;
    const h = harness({ watch: async () => { if (recovered) return validWatch(); if (failure) return failure; throw Error(unsafe); }, news: async () => { feedCalls++; return []; } });
    h.render(); await tick();
    const tree = h.render();
    assert.equal(alerts(tree).length, 1);
    assert.doesNotMatch(text(tree), /还没有关注股票|暂无新闻|SQL|https:/);
    assert.equal(feedCalls, 0);
    recovered = true; button(tree, '重试').props.onClick(); await tick();
    assert.match(text(h.render()), /近期暂无新闻/);
    assert.equal(feedCalls, 1);
  }
});

test('a failed watchlist refresh cannot silently fall back to old codes', async () => {
  let failWatch = false, feedCalls = 0;
  const h = harness({ watch: async () => { if (failWatch) throw Error(unsafe); return validWatch(); }, news: async () => { feedCalls++; return [{ 新闻标题: 'Old row' }]; } });
  h.render(); await tick();
  failWatch = true; button(h.render(), '刷新').props.onClick(); await tick();
  const tree = h.render();
  assert.match(text(tree), /关注列表加载失败/);
  assert.doesNotMatch(text(tree), /Old row|还没有关注股票/);
  assert.equal(feedCalls, 1);
});

test('missing news dependency gets a safe hint rather than upstream error detail', async () => {
  const h = harness({ news: async () => { throw new ApiError(unsafe, 501); } });
  h.render(); await tick();
  const tree = h.render();
  assert.match(text(tree), /缺少 akshare 依赖/);
  assert.doesNotMatch(text(tree), /暂无新闻|SQL|https:/);
});

test('optional quote failure never blocks a successful feed', async () => {
  const h = harness({ quote: async () => { throw Error(unsafe); }, news: async () => [{ 新闻标题: 'Available row' }] });
  h.render(); await tick();
  const tree = h.render();
  assert.equal(alerts(tree).length, 0);
  assert.match(text(tree), /Available row/);
});

test('new tab wins over delayed old feed success and error', async () => {
  for (const fail of [false, true]) {
    const old = deferred();
    const h = harness({ announcements: () => old.promise, news: async () => [{ 新闻标题: 'New tab row' }] });
    h.render('filings'); await tick();
    h.render('news'); await tick();
    fail ? old.reject(Error(unsafe)) : old.resolve([{ title: 'Old tab row', date: '', type: '', url: '' }]);
    await tick();
    const tree = h.render('news');
    assert.match(text(tree), /New tab row/);
    assert.doesNotMatch(text(tree), /Old tab row|加载失败/);
  }
});

test('stale watchlist read cannot start an old feed after switching tabs', async () => {
  const old = deferred(); let calls = 0, oldFeedCalls = 0;
  const h = harness({ watch: () => ++calls === 1 ? old.promise : Promise.resolve(validWatch()), announcements: async () => { oldFeedCalls++; return []; }, news: async () => [{ 新闻标题: 'New tab row' }] });
  h.render('filings'); h.render('news'); await tick();
  old.resolve(validWatch()); await tick();
  assert.equal(oldFeedCalls, 0);
  assert.match(text(h.render('news')), /New tab row/);
});

test('unmount cancels state writes from an in-flight feed', async () => {
  const pending = deferred();
  const h = harness({ news: () => pending.promise });
  h.render(); await tick(); h.unmount();
  const before = h.writes();
  pending.resolve([{ 新闻标题: 'Too late' }]); await tick();
  assert.equal(h.writes(), before);
});


test('a newer same-tab refresh wins over an older pending response', async () => {
  const old = deferred(); let calls = 0;
  const h = harness({ news: () => ++calls === 1 ? old.promise : Promise.resolve([{ 新闻标题: 'Latest row' }]) });
  h.render(); await tick();
  // Exercise the existing handler twice before a browser rerender disables it.
  const refresh = nodes(h.render()).find((node) => node.type === 'button').props.onClick;
  refresh(); await tick();
  old.resolve([{ 新闻标题: 'Stale row' }]); await tick();
  const tree = h.render();
  assert.match(text(tree), /Latest row/);
  assert.doesNotMatch(text(tree), /Stale row/);
});
