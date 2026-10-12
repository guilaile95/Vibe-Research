import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { sealReply, dayA } from "./e2e/seal-quality.fixture.mjs";

const provenance = JSON.parse(readFileSync(new URL("./fixtures/next-day-verification-provenance.json", import.meta.url), "utf8"));
const golden = JSON.parse(readFileSync(new URL("./fixtures/next-day-verification.json", import.meta.url), "utf8"));
function load(relative, modules = {}) {
  const source = ts.transpileModule(readFileSync(new URL(relative, import.meta.url), "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(source, { exports, AbortController, Date, Intl, Error, require: name => { assert.ok(name in modules, `Unexpected import ${name}`); return modules[name]; } });
  return exports;
}
const journal = load("../src/lib/nextDayVerification.ts");
const shortline = load("../src/lib/shortlineResearch.ts");
const shortlineGolden = JSON.parse(readFileSync(new URL("./fixtures/shortline-research.golden.json", import.meta.url), "utf8"));
const seal = load("../src/lib/sealQuality.ts");
const copy = x => structuredClone(x);

test("all existing real-service journal goldens still satisfy readback contract", () => {
  for (const [name, view] of Object.entries(golden)) assert.equal(journal.isVerificationViewForDate(view, view.trade_date), true, name);
});
for (const [name, mutate] of [
  ["wrong date", x => x.trade_date = "2026-07-30"], ["unsupported schema", x => x.schema_version = "future"],
  ["authority escalation", x => x.research_only = false], ["null items", x => x.items = null],
  ["null metrics", x => x.metrics = null], ["null history", x => x.history = null],
  ["boolean revision", x => x.revision = true], ["unsafe revision", x => x.revision = 2 ** 53],
  ["duplicate metrics", x => x.metrics[1] = x.metrics[0]], ["invalid boundary timestamp", x => x.seals_at = "bad"],
  ["contradictory boundary", x => x.state = "SEALED"], ["NaN summary", x => x.summary.total = NaN],
  ["impossible summary", x => x.summary.hit = 4], ["infinite ratio", x => x.history.summary.coverage = Infinity],
]) test(`journal rejects ${name}`, () => {
  const value = copy(golden.open_empty); mutate(value);
  assert.equal(journal.isVerificationViewForDate(value, golden.open_empty.trade_date), false);
});
for (const [name, mutate] of [
  ["null baseline", x => x.items[0].baseline = null], ["null item", x => x.items[0] = null],
  ["duplicate item", x => x.items.push(copy(x.items[0]))], ["foreign target", x => x.items[0].target_date = "2026-08-04"],
  ["malformed provenance", x => x.items[0].prior_evidence = { source_ids: null }],
  ["boolean reading", x => x.items[0].prior_value = true], ["out of range frequency", x => x.items[0].baseline.rate = 2],
  ["invented verdict", x => x.items[0].verified = true], ["invalid direction", x => x.items[0].direction = "buy"],
]) test(`journal rejects item ${name}`, () => {
  const value = copy(golden.open_saved); mutate(value);
  assert.equal(journal.isVerificationViewForDate(value, value.trade_date), false);
});
test("seal preserves normal, partial, unavailable and rejects corrupt render operands", () => {
  for (const mode of ["normal", "partial", "unconnected"]) assert.equal(seal.isSealQualityArchiveForDate(sealReply(dayA, mode), dayA), true, mode);
  const mutations = [
    x => x.projection.coverage.extra = null, x => x.projection.coverage.first_seal = null,
    x => x.projection.rows[0] = null, x => x.projection.rows[0].field_issues = [],
    x => x.projection.rows[0].field_issues.first_seal = null, x => x.projection.rows[0].broken_times = true,
    x => x.projection.rows[0].first_seal = "990000", x => x.projection.rows[0].last_seal = "090000",
    x => x.projection.rows.push(copy(x.projection.rows[0])), x => x.projection.status = "partial",
    x => x.projection.metrics.never_broken_ratio = 2, x => x.projection.metrics.average_broken_times = NaN,
    x => x.projection.coverage.first_seal.known_count = -1, x => x.projection.coverage.first_seal.unknown_count = 0.5,
    x => x.projection.sample_count = 1.5, x => x.archive_identity.raw_payload_hash = "fake",
  ];
  for (const mutate of mutations) { const value = sealReply(dayA); mutate(value); assert.equal(seal.isSealQualityArchiveForDate(value, dayA), false, String(mutate)); }
});

// Run the entire production JSX component with deterministic hooks and promises.
// No browser, network, source reimplementation, or backend process is involved.
function harness(component, initial) {
  let props = initial, cursor = 0, dirty = true, tree;
  const cells = [], effects = [], calls = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((x, i) => Object.is(x, b[i]));
  const react = {
    useState(initial) { const i = cursor++; if (!(i in cells)) cells[i] = typeof initial === "function" ? initial() : initial; return [cells[i], next => { const value = typeof next === "function" ? next(cells[i]) : next; if (!Object.is(cells[i], value)) { cells[i] = value; dirty = true; } }]; },
    useRef(initial) { const i = cursor++; return cells[i] ??= { current: initial }; },
    useEffect(fn, deps) { const i = cursor++; if (!cells[i] || !same(cells[i].deps, deps)) { const old = cells[i]; cells[i] = { deps }; effects.push(() => { old?.cleanup?.(); cells[i].cleanup = fn(); }); } },
  };
  const request = (...args) => new Promise((resolve, reject) => calls.push({ args, resolve, reject }));
  const modules = { react, "react/jsx-runtime": { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: "fragment" },
    "@/lib/api": { request, api: { sealQuality: request } }, "@/components/dailyReview/RegimeAnnotationForm": { RegimeAnnotationForm: "form" }, "@/lib/shortlineResearch": shortline, "@/lib/nextDayVerification": journal, "@/lib/sealQuality": seal,
    "@/components/ui/GlassCard": { GlassCard: "section" } };
  const exports = load(`../src/components/dailyReview/${component}.tsx`, modules);
  return { calls, get tree() { return tree; }, update(next) { props = next; dirty = true; },
    async flush() { await new Promise(done => setImmediate(done)); for (let n = 0; n < 20 && (dirty || effects.length); n++) { if (dirty) { dirty = false; cursor = 0; tree = exports[component](props); } for (const effect of effects.splice(0)) effect(); await new Promise(done => setImmediate(done)); } assert.equal(dirty, false, "render settles"); },
    unmount() { for (const cell of cells) cell?.cleanup?.(); },
  };
}
function nodes(value) { return !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)]; }
function text(value) { return value == null || typeof value === "boolean" ? "" : typeof value === "string" || typeof value === "number" ? String(value) : Array.isArray(value) ? value.map(text).join("") : text(value.props?.children); }
const button = (h, label) => nodes(h.tree).find(n => n.type === "button" && text(n).includes(label));
const control = (h, label) => nodes(h.tree).find(n => n.props?.["aria-label"] === label);

test("production journal rejects malformed GET without committing it and recovers by reread", async () => {
  const h = harness("NextDayVerificationCard", { initialDate: golden.open_empty.trade_date }); await h.flush();
  h.calls[0].resolve({ trade_date: golden.open_empty.trade_date, items: null }); await h.flush();
  assert.match(text(h.tree), /响应未通过校验/); assert.equal(control(h, "涨停家数方向"), undefined);
  button(h, "重新读取").props.onClick(); await h.flush(); h.calls[1].resolve(copy(golden.open_empty)); await h.flush();
  assert.ok(control(h, "涨停家数方向")); assert.doesNotMatch(text(h.tree), /响应未通过校验/); h.unmount();
});
test("production journal malformed PUT retains draft, withholds success and blocks resave until reread", async () => {
  const h = harness("NextDayVerificationCard", { initialDate: golden.open_empty.trade_date }); await h.flush();
  h.calls[0].resolve(copy(golden.open_empty)); await h.flush();
  control(h, "涨停家数方向").props.onChange({ target: { value: "up" } }); await h.flush();
  control(h, "涨停家数理由").props.onChange({ target: { value: "Keep my input" } }); await h.flush();
  button(h, "保存整晚条件").props.onClick(); await h.flush();
  h.calls[1].resolve({ ...copy(golden.open_saved), history: null }); await h.flush();
  assert.equal(control(h, "涨停家数理由").props.value, "Keep my input"); assert.match(text(h.tree), /保存结果尚未确认/);
  assert.doesNotMatch(text(h.tree), /已保存；/); assert.equal(button(h, "保存整晚条件").props.disabled, true);
  button(h, "保存整晚条件").props.onClick(); await h.flush(); assert.equal(h.calls.length, 2);
  button(h, "重新读取").props.onClick(); await h.flush(); h.calls[2].resolve(copy(golden.open_saved)); await h.flush();
  assert.equal(button(h, "保存整晚条件").props.disabled, false); assert.doesNotMatch(text(h.tree), /尚未确认/); h.unmount();
});
test("production seal turns malicious coverage into recoverable error rather than JSX crash", async () => {
  const h = harness("SealQualityCard", { tradeDate: dayA }); await h.flush();
  const bad = sealReply(dayA); bad.projection.coverage.extra = null; h.calls[0].resolve(bad); await h.flush();
  assert.match(text(h.tree), /归档读取未通过/); assert.doesNotMatch(text(h.tree), /50.0%/);
  button(h, "重新读取").props.onClick(); await h.flush(); h.calls[1].resolve(sealReply(dayA)); await h.flush();
  assert.match(text(h.tree), /50.0%/); h.unmount();
});
test("production journal provenance preserves unknown and labels frozen versus current evidence", async () => {
  const h = harness("NextDayVerificationCard", { initialDate: golden.open_saved.trade_date }); await h.flush();
  h.calls[0].resolve(copy(golden.open_saved)); await h.flush();
  assert.match(text(h.tree), /已冻结事前证据/); assert.match(text(h.tree), /当前存档收盘观察/);
  assert.match(text(h.tree), /未提供合格证据/); assert.match(text(h.tree), /后续来源更正可能改变对账结果/);
  assert.ok(nodes(h.tree).find(n => n.props?.["data-testid"] === "verification-evidence-limit_up_count")); h.unmount();
});


test("qualified provenance goldens preserve source correction and frozen baseline", async () => {
  for (const [name, view] of Object.entries(provenance)) assert.equal(journal.isVerificationViewForDate(view, view.trade_date), true, name);
  const h = harness("NextDayVerificationCard", { initialDate: provenance.verified.trade_date }); await h.flush();
  h.calls[0].resolve(copy(provenance.verified)); await h.flush();
  assert.match(text(h.tree), /来源：synthetic/); assert.match(text(h.tree), /抓取时间（UTC）：2026-07-31/);
  assert.match(text(h.tree), /抓取时间（UTC）：2026-08-03/); assert.match(text(h.tree), /基准窗口：/);
  assert.match(text(h.tree), /成立/); assert.doesNotMatch(text(h.tree), /不成立/);
  button(h, "重新读取").props.onClick(); await h.flush(); h.calls[1].resolve(copy(provenance.corrected)); await h.flush();
  assert.match(text(h.tree), /不成立/);
  assert.deepEqual(provenance.verified.items.map(x => x.prior_evidence), provenance.corrected.items.map(x => x.prior_evidence));
  assert.deepEqual(provenance.verified.items.map(x => x.baseline), provenance.corrected.items.map(x => x.baseline)); h.unmount();
});
for (const [name, mutate] of [
  ["24 hour timestamp", x => x.generated_at = "2026-08-03T24:00:00Z"],
  ["normalized impossible date", x => x.generated_at = "2026-02-30T08:00:00Z"],
  ["source time inversion", x => x.items[0].prior_evidence.snapshot_at = "2026-07-31T07:09:00Z"],
  ["microsecond source inversion", x => x.items[0].prior_evidence.fetched_at = "2026-07-31T07:10:00.000001Z"],
  ["frozen timestamp drift", x => x.items[0].baseline.as_of = "2026-07-31T08:00:00.000001Z"],
  ["late verified condition", x => { x.items[0].written_at = x.seals_at; x.items[0].baseline.as_of = x.seals_at; }],
  ["wrong actual direction", x => { x.items[0].actual = "down"; x.items[0].verified = false; }],
  ["wrong baseline subset", x => x.summary.baseline_covered = 0],
]) test(`provenance rejects ${name}`, () => {
  const value = copy(provenance.verified); mutate(value);
  assert.equal(journal.isVerificationViewForDate(value, value.trade_date), false);
});
test("seal rejects invalid or normalized captured timestamps without throwing", () => {
  for (const stamp of ["2026-07-30T24:00:00Z", "2026-02-30T12:00:00Z", "2026-99-99T12:00:00Z", "2026-07-30T12:00:00"]) {
    const value = sealReply(dayA); value.archive_identity.captured_at = stamp;
    assert.equal(seal.isSealQualityArchiveForDate(value, dayA), false);
  }
});

for (const mutate of [
 x => x.projection.structure.market_structure.recent_10.median_limit_up_count = {},
 x => x.projection.structure.regime_events = null,
 x => x.projection.cohort.previous_limit_up_denominator = {},
]) test(`production shortline rejects malformed response and recovers: ${mutate}`, async () => {
 const h = harness("ShortlineResearchCard", { tradeDate: shortlineGolden.trade_date }); await h.flush();
 const bad = copy(shortlineGolden); mutate(bad); h.calls[0].resolve(bad); await h.flush();
 assert.match(text(h.tree), /读取或合同核验失败/);
 button(h, "重新读取研究归档").props.onClick(); await h.flush(); h.calls[1].resolve(copy(shortlineGolden)); await h.flush();
 for (const label of ["完整昨日反馈", "结构与字段", "涨停样本", "历史分位", "今日事实"]) {
  button(h, label).props.onClick(); await h.flush(); assert.doesNotMatch(text(h.tree), /读取或合同核验失败/);
 }
 h.unmount();
});
