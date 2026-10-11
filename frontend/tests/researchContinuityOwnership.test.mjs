import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

// Execute the entire production component with deterministic hook scheduling and
// deferred API responses. This tests ownership and rendered controls, not browser QA.
const source = ts.transpileModule(readFileSync(new URL("../src/components/campaign/ResearchContinuityCard.tsx", import.meta.url), "utf8"), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const tick = () => new Promise(done => setImmediate(done));
function harness(initial) {
  let props = initial, cursor = 0, dirty = true, tree, writes = 0;
  const cells = [], effects = [], calls = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in cells)) cells[i] = typeof initial === "function" ? initial() : initial;
      return [cells[i], next => { writes++; const value = typeof next === "function" ? next(cells[i]) : next; if (!Object.is(cells[i], value)) { cells[i] = value; dirty = true; } }];
    },
    useRef(initial) { const i = cursor++; return cells[i] ??= { current: initial }; },
    useId() { const i = cursor++; return cells[i] ??= `continuity-${i}`; },
    useCallback(fn, deps) { const i = cursor++; if (!cells[i] || !same(cells[i].deps, deps)) cells[i] = { deps, fn }; return cells[i].fn; },
    useLayoutEffect(fn, deps) {
      const i = cursor++;
      if (!cells[i] || !same(cells[i].deps, deps)) { const old = cells[i]; cells[i] = { deps, effect: fn }; effects.push(() => { old?.cleanup?.(); cells[i].cleanup = fn(); }); }
    },
  };
  const modules = {
    react,
    "react/jsx-runtime": { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: "fragment" },
    "@/lib/api": { ApiError: Error, api: { getResearchContinuity: campaignId => new Promise((resolve, reject) => calls.push({ campaignId, resolve, reject })) } },
    "@/components/ui/GlassCard": { GlassCard: "section" },
    "lucide-react": { AlertCircle: "icon", CalendarClock: "icon", Loader2: "icon", RefreshCw: "icon" },
  };
  const exports = {};
  vm.runInNewContext(source, { exports, Error, require: name => { assert.ok(name in modules, `Unexpected import ${name}`); return modules[name]; } });
  const render = () => { dirty = false; cursor = 0; tree = exports.ResearchContinuityCard(props); };
  return {
    calls, get tree() { return tree; }, get writes() { return writes; },
    update(next) { props = next; dirty = true; }, render,
    commit() { for (const effect of effects.splice(0)) effect(); },
    abandonRender(next) {
      const saved = { props, cells: cells.slice(), effects: effects.slice(), dirty, tree };
      props = next; render();
      // React discards speculative state/effects, but ref objects are shared
      // with the committed tree. Intentionally do not clone or restore refs.
      props = saved.props; cells.splice(0, cells.length, ...saved.cells);
      effects.splice(0, effects.length, ...saved.effects); dirty = saved.dirty; tree = saved.tree;
    },
    refresh() { nodes(tree).find(node => node.props?.["aria-label"] === "刷新研究连续性").props.onClick(); },
    unmount() { cells.forEach(cell => cell?.cleanup?.()); },
    replayEffects() { cells.forEach(cell => { if (cell?.effect) { cell.cleanup?.(); cell.cleanup = cell.effect(); } }); },
    async flush() {
      await tick();
      for (let n = 0; n < 20 && (dirty || effects.length); n++) { if (dirty) render(); for (const effect of effects.splice(0)) effect(); await tick(); }
      assert.equal(dirty, false, "render loop settles");
    },
  };
}
function nodes(value) { return !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)]; }
function text(value) { return value == null || typeof value === "boolean" ? "" : typeof value === "string" || typeof value === "number" ? String(value) : Array.isArray(value) ? value.map(text).join("") : text(value.props?.children); }
function fixture(campaignId, count = 1) {
  return {
    campaign_id: campaignId, baseline: { status: "READY" },
    changes: { status: "NORMAL", observation_count: 1234, items: Array.from({ length: count }, (_, i) => ({ change_type: "ADDED", record_key: `${campaignId}-${i}`, after: { claim_identity: `${campaignId} fact ${i}`, source: "Synthetic source" } })) },
    decision_calendar: { state: "NO_RECORD", source: "Synthetic calendar", fetched_at: "2026-10-11" },
  };
}
const loading = h => nodes(h.tree).find(node => node.props?.["aria-label"] === "刷新研究连续性").props.disabled;
const rows = h => nodes(h.tree).filter(node => node.props?.["data-testid"] === "research-change-added");
for (const fails of [false, true]) test(`manual refresh late ${fails ? "failure" : "success"} cannot overwrite a new campaign's prefetch`, async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush(); h.refresh(); await h.flush();
  h.update({ campaignId: "B", prefetched: fixture("B") }); await h.flush();
  fails ? h.calls[0].reject(new Error("STALE ERROR")) : h.calls[0].resolve(fixture("STALE")); await h.flush();
  assert.match(text(h.tree), /B fact/); assert.doesNotMatch(text(h.tree), /STALE/); assert.equal(loading(h), false); h.unmount();
});
for (const fails of [false, true]) test(`old manual ${fails ? "failure" : "success"} finalizer cannot finish a newer request`, async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush(); h.refresh(); await h.flush();
  h.update({ campaignId: "B" }); await h.flush(); assert.equal(h.calls[1].campaignId, "B");
  fails ? h.calls[0].reject(new Error("STALE ERROR")) : h.calls[0].resolve(fixture("STALE")); await h.flush();
  assert.equal(loading(h), true); assert.doesNotMatch(text(h.tree), /STALE/);
  h.calls[1].resolve(fixture("B")); await h.flush(); assert.match(text(h.tree), /B fact/); h.unmount();
});
test("same-campaign replacement prefetch owns the result over a pending refresh", async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("INITIAL") }); await h.flush(); h.refresh(); await h.flush();
  h.update({ campaignId: "A", prefetched: fixture("PREFETCH") }); await h.flush();
  h.calls[0].resolve(fixture("STALE")); await h.flush(); assert.match(text(h.tree), /PREFETCH fact/); assert.doesNotMatch(text(h.tree), /STALE/); h.unmount();
});
test("more than eight changes disclose the returned count and all rows are reachable", async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A", 11) }); await h.flush();
  assert.equal(rows(h).length, 8); assert.match(text(h.tree), /共 11 条/); assert.doesNotMatch(text(h.tree), /1234/);
  const expand = nodes(h.tree).find(node => node.type === "button" && text(node).includes("展开"));
  assert.ok(expand); assert.equal(expand.props["aria-expanded"], false); assert.match(text(expand), /3/);
  assert.ok(nodes(h.tree).some(node => node.props?.id === expand.props["aria-controls"]));
  expand.props.onClick(); await h.flush(); assert.equal(rows(h).length, 11);
  const collapse = nodes(h.tree).find(node => node.type === "button" && node.props["aria-expanded"] === true);
  assert.ok(collapse); collapse.props.onClick(); await h.flush(); assert.equal(rows(h).length, 8); h.unmount();
});

for (const fails of [false, true]) test(`prefetch wait invalidates old ${fails ? "failure" : "success"} and prevents fallback reads`, async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush(); h.refresh(); await h.flush();
  h.update({ campaignId: "A", awaitingPrefetch: true }); await h.flush();
  h.refresh(); assert.equal(h.calls.length, 1, "even a retained refresh handler must not bypass a pending batch");
  fails ? h.calls[0].reject(new Error("STALE")) : h.calls[0].resolve(fixture("STALE")); await h.flush();
  assert.equal(loading(h), true); assert.doesNotMatch(text(h.tree), /STALE/);
  h.update({ campaignId: "A", prefetched: fixture("BATCH") }); await h.flush();
  assert.match(text(h.tree), /BATCH fact/); assert.equal(h.calls.length, 1); h.unmount();
});
for (const fails of [false, true]) test(`unmount prevents late manual ${fails ? "failure" : "success"} state writes`, async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush(); h.refresh(); await h.flush(); h.unmount();
  const writes = h.writes;
  fails ? h.calls[0].reject(new Error("STALE")) : h.calls[0].resolve(fixture("STALE")); await tick();
  assert.equal(h.writes, writes); h.refresh(); assert.equal(h.calls.length, 1);
});
for (const fails of [false, true]) test(`committed context change blocks stale ${fails ? "failure" : "success"} before passive effects`, async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush(); h.refresh(); await h.flush();
  h.update({ campaignId: "B", prefetched: fixture("B") }); h.render();
  assert.match(text(h.tree), /B fact/); assert.doesNotMatch(text(h.tree), /A fact/);
  h.commit(); const writes = h.writes;
  fails ? h.calls[0].reject(new Error("STALE")) : h.calls[0].resolve(fixture("STALE")); await tick();
  assert.equal(h.writes, writes, "no stale writes after layout commit");
  await h.flush(); assert.match(text(h.tree), /B fact/); h.unmount();
});
for (const fails of [false, true]) test(`same-context duplicate refresh is latest-request-wins after old ${fails ? "failure" : "success"}`, async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush();
  // Same event-loop turn: exercise repeated handlers before the disabled render.
  h.refresh(); h.refresh(); await h.flush();
  fails ? h.calls[0].reject(new Error("STALE")) : h.calls[0].resolve(fixture("STALE")); await h.flush();
  assert.equal(loading(h), true);
  h.calls[1].resolve(fixture("CURRENT")); await h.flush(); assert.match(text(h.tree), /CURRENT fact/); assert.doesNotMatch(text(h.tree), /STALE/); h.unmount();
});
test("failed prefetch stays authoritative until explicit refresh, which can fail and retry", async () => {
  const h = harness({ campaignId: "A", prefetched: null }); await h.flush();
  assert.equal(h.calls.length, 0); assert.match(text(h.tree), /批量读取失败/); assert.equal(loading(h), false);
  h.refresh(); await h.flush(); h.calls[0].reject(new Error("CURRENT failure")); await h.flush();
  assert.match(text(h.tree), /CURRENT failure/); assert.equal(loading(h), false);
  h.refresh(); await h.flush(); h.calls[1].resolve(fixture("RECOVERED")); await h.flush();
  assert.match(text(h.tree), /RECOVERED fact/); assert.doesNotMatch(text(h.tree), /failure/); h.unmount();
});
test("a replacement null prefetch cannot be overwritten by late manual success", async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush(); h.refresh(); await h.flush();
  h.update({ campaignId: "A", prefetched: null }); await h.flush(); h.calls[0].resolve(fixture("STALE")); await h.flush();
  assert.match(text(h.tree), /批量读取失败/); assert.doesNotMatch(text(h.tree), /STALE/); h.unmount();
});
test("initial fetch works and a current ordinary failure clears obsolete facts", async () => {
  const h = harness({ campaignId: "A" }); await h.flush(); assert.equal(h.calls.length, 1); assert.equal(loading(h), true);
  h.calls[0].resolve(fixture("INITIAL")); await h.flush(); assert.match(text(h.tree), /INITIAL fact/);
  h.refresh(); await h.flush(); assert.doesNotMatch(text(h.tree), /INITIAL fact/);
  h.calls[1].reject({ unsafe: "internal details" }); await h.flush(); assert.match(text(h.tree), /研究变化读取失败/); assert.doesNotMatch(text(h.tree), /internal details/); h.unmount();
});
test("expansion resets on refreshed data and campaign changes without manufacturing global totals", async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A", 10) }); await h.flush();
  const expand = () => nodes(h.tree).find(node => node.type === "button" && node.props["aria-expanded"] === false).props.onClick();
  expand(); await h.flush(); assert.equal(rows(h).length, 10);
  h.refresh(); await h.flush(); h.calls[0].resolve(fixture("REFRESH", 12)); await h.flush();
  assert.equal(rows(h).length, 8); assert.match(text(h.tree), /共 12 条/); expand(); await h.flush();
  h.update({ campaignId: "B", prefetched: fixture("B", 9) }); await h.flush();
  assert.equal(rows(h).length, 8); assert.match(text(h.tree), /共 9 条/); assert.doesNotMatch(text(h.tree), /REFRESH fact/); h.unmount();
});
for (const count of [0, 1, 8]) test(`${count} returned changes need no expansion control`, async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A", count) }); await h.flush();
  assert.equal(rows(h).length, count); assert.equal(nodes(h.tree).filter(node => node.props?.["aria-expanded"] !== undefined).length, 0);
  if (count === 0) assert.match(text(h.tree), /未发现事实字段变化/);
  h.unmount();
});

test("StrictMode effect cleanup and replay preserve the remounted request's ownership", async () => {
  const h = harness({ campaignId: "A" }); await h.flush(); h.replayEffects(); await h.flush();
  assert.equal(h.calls.length, 2); h.calls[0].resolve(fixture("STALE")); await h.flush(); assert.equal(loading(h), true);
  h.calls[1].resolve(fixture("CURRENT")); await h.flush(); assert.match(text(h.tree), /CURRENT fact/); assert.doesNotMatch(text(h.tree), /STALE/); h.unmount();
});
for (const [status, message] of [["NO_BASELINE", /暂时无法比较变化/], ["NOT_EVALUATED", /不能声称“没有变化”/], ["UNAVAILABLE", /证据链无法完整验证/]]) test(`${status} does not expose unverifiable item counts`, async () => {
  const data = fixture("A", 10); data.changes.status = status;
  const h = harness({ campaignId: "A", prefetched: data }); await h.flush(); assert.match(text(h.tree), message);
  assert.equal(rows(h).length, 0); assert.doesNotMatch(text(h.tree), /共 10 条|展开/); h.unmount();
});

for (const fails of [false, true]) test(`abandoned campaign render preserves committed request ${fails ? "failure" : "success"} ownership`, async () => {
  const h = harness({ campaignId: "A" }); await h.flush();
  const writes = h.writes; h.abandonRender({ campaignId: "B" });
  assert.equal(h.writes, writes, "speculative render must not schedule state changes");
  fails ? h.calls[0].reject(new Error("A failure")) : h.calls[0].resolve(fixture("A")); await h.flush();
  assert.equal(loading(h), false);
  assert.match(text(h.tree), fails ? /A failure/ : /A fact/); assert.equal(h.calls.length, 1); h.unmount();
});
test("retained committed refresh cannot target a campaign from an abandoned render", async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush();
  h.abandonRender({ campaignId: "B", prefetched: fixture("B") });
  h.refresh(); await h.flush(); assert.equal(h.calls[0].campaignId, "A");
  h.calls[0].resolve(fixture("REFRESH A")); await h.flush(); assert.match(text(h.tree), /REFRESH A fact/); h.unmount();
});
test("a new context renders its loading boundary before layout commit, never old facts", async () => {
  const h = harness({ campaignId: "A", prefetched: fixture("A") }); await h.flush();
  h.update({ campaignId: "B" }); h.render();
  assert.equal(loading(h), true); assert.doesNotMatch(text(h.tree), /A fact/);
  await h.flush(); assert.equal(h.calls[0].campaignId, "B");
  h.calls[0].resolve(fixture("B")); await h.flush(); assert.match(text(h.tree), /B fact/); h.unmount();
});
