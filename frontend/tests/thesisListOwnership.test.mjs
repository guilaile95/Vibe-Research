import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";
import * as subjectView from "../src/lib/evidenceListView.ts";
import * as thesisView from "../src/lib/thesisListView.ts";

// Actual production controller, isolated deterministic hooks/router/API.
// This is component ownership evidence, not a replacement for browser CI.
function harness(initial, read = async () => ({ items: [], total: 0 })) {
  let params = new URLSearchParams(initial), cursor = 0, dirty = true, tree;
  const cells = [], effects = [], reads = [], writes = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
  const react = {
    useState(value) { const index = cursor++; if (!(index in cells)) cells[index] = typeof value === "function" ? value() : value; return [cells[index], next => { const value = typeof next === "function" ? next(cells[index]) : next; if (!Object.is(cells[index], value)) { cells[index] = value; dirty = true; } }]; },
    useEffect(fn, deps) { const index = cursor++; if (!cells[index] || !same(cells[index].deps, deps)) { const old = cells[index]; cells[index] = { deps }; effects.push(() => { old?.cleanup?.(); cells[index].cleanup = fn(); }); } },
  };
  const modules = {
    react, "react/jsx-runtime": { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    "react-router-dom": { Link: "link", useSearchParams: () => [params, next => { params = next; writes.push(params.toString()); dirty = true; }] },
    "@/lib/api": { ApiError: Error, api: { thesisList: async params => { reads.push(params); return read(params); } } },
    "@/lib/evidenceListView": subjectView, "@/lib/thesisListView": thesisView,
  };
  const exports = {}, generic = new Proxy({}, { get: (_, key) => key === "__esModule" ? true : () => null });
  const source = ts.transpileModule(readFileSync(new URL("../src/pages/ThesisList.tsx", import.meta.url), "utf8"), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(source, { exports, URLSearchParams, Error, require: name => modules[name] ?? generic });
  return { reads, writes, get query() { return params.toString(); }, get tree() { return tree; },
    apply(type, id, status) { nodes(tree).find(node => node.props?.onApply).props.onApply(type, id, status); },
    navigate(search) { params = new URLSearchParams(search); dirty = true; },
    unmount() { cells.forEach(cell => cell?.cleanup?.()); },
    async flush() { await new Promise(done => setImmediate(done)); for (let n = 0; n < 20 && dirty; n++) { dirty = false; cursor = 0; tree = exports.ThesisList(); for (const effect of effects.splice(0)) effect(); await new Promise(done => setImmediate(done)); } assert.equal(dirty, false, "render loop settles"); },
  };
}
function nodes(value) { return !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children), ...nodes(value.props?.actions)]; }
function text(value) { return value == null || typeof value === "boolean" ? "" : typeof value === "string" || typeof value === "number" ? String(value) : Array.isArray(value) ? value.map(text).join("") : text(value.props?.children); }
const record = title => ({ id: title, title, summary: "Synthetic", subject_type: "stock", subject_id: "000001", status: "active", formal_state: "draft", current_revision: 1, frozen_revision: null, updated_at: null });

test("actual list restores Back filters and requests the restored status without rewriting URL", async () => {
  const initial = "subject_type=stock&subject_id=000001&status=active";
  const h = harness(initial); await h.flush(); h.apply("stock", "000001", "archived"); await h.flush();
  const writesBeforeBack = h.writes.length;
  h.navigate(initial); await h.flush();
  assert.equal(h.query, initial);
  assert.equal(h.writes.length, writesBeforeBack);
  assert.deepEqual(h.reads.map(read => read.status), ["active", "archived", "active"]);
  assert.equal(nodes(h.tree).find(node => node.props?.onApply).props.query.status, "active");
  h.unmount();
});
test("invalid deep links make zero all-subject requests and clear can recover", async () => {
  for (const query of ["subject_type=stock", "subject_id=000001", "status=frozen"]) {
    const h = harness(query); await h.flush(); assert.equal(h.reads.length, 0);
    assert.match(text(h.tree), /筛选无效/);
    h.apply("", "", ""); await h.flush(); assert.equal(h.reads.length, 1);
    h.unmount();
  }
});
test("a page change requests its offset and preserves filter-specific detail return context", async () => {
  const h = harness("subject_type=stock&subject_id=000001&status=active&page=2", async () => ({ items: [record("page-two")], total: 51 }));
  await h.flush(); assert.equal(h.reads[0].offset, 50);
  const href = nodes(h.tree).find(node => node.type === "link" && node.props.to.startsWith("/thesis/page-two?")).props.to;
  assert.equal(new URL(href, "http://synthetic.invalid").searchParams.get("return_to"), "/thesis?subject_type=stock&subject_id=000001&status=active&page=2");
  h.unmount();
});
test("late superseded success cannot replace current rows, and error cannot retain the old subject", async () => {
  let release;
  const h = harness("subject_type=stock&subject_id=slow", params => params.subject_id === "slow" ? new Promise(done => { release = done; }) : params.subject_id === "failed" ? Promise.reject(new Error("synthetic failure")) : Promise.resolve({ items: [record("NEWER")], total: 1 }));
  await h.flush(); h.apply("stock", "newer", ""); await h.flush(); assert.match(text(h.tree), /NEWER/);
  release({ items: [record("STALE")], total: 1 }); await h.flush(); assert.doesNotMatch(text(h.tree), /STALE/); assert.match(text(h.tree), /NEWER/);
  h.apply("stock", "failed", ""); await h.flush(); assert.match(text(h.tree), /投资逻辑加载失败/); assert.doesNotMatch(text(h.tree), /NEWER/);
  h.unmount();
});
