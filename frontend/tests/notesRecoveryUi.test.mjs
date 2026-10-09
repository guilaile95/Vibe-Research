import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";
import * as notes from "../src/lib/notes.ts";

// Exercise actual Notes handlers with real storage functions and isolated React hooks.
// Browser download/dialog behavior is independently covered by notes-backup.browser.mjs.
function createHarness(confirm = () => true) {
  const state = [], refs = [], cleanup = [], downloads = [];
  const events = new EventTarget();
  let cursor = 0, initialized = false;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in state)) state[i] = typeof initial === "function" ? initial() : initial;
      return [state[i], (next) => { state[i] = typeof next === "function" ? next(state[i]) : next; }];
    },
    useRef(initial) { const i = cursor++; return refs[i] ??= { current: initial }; },
    useEffect(effect) { if (!initialized) cleanup.push(effect()); },
  };
  const generic = new Proxy({}, { get: (_, key) => key === "__esModule" ? true : () => null });
  const searchParams = new URLSearchParams();
  const modules = {
    react,
    "react-router-dom": { useSearchParams: () => [searchParams, () => {}], Link: "link" },
    "react/jsx-runtime": { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    "@/lib/notes": notes,
  };
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL("../src/pages/Notes.tsx", import.meta.url), "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(source, {
    exports, require: (name) => modules[name] ?? generic, Error, DOMException, AbortController,
    Blob, confirm, console,
    window: { addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events) },
    URL: { createObjectURL: (blob) => { downloads.push(blob); return "blob:synthetic"; }, revokeObjectURL() {} },
    document: { createElement: () => ({ click() {}, remove() {} }), body: { appendChild() {} } },
  });
  return {
    downloads,
    storageChanged(key) { const event = new Event("storage"); Object.defineProperty(event, "key", { value: key }); events.dispatchEvent(event); },
    notesChanged() { events.dispatchEvent(new Event(notes.NOTES_CHANGED_EVENT)); },
    render() { cursor = 0; const tree = exports.Notes(); initialized = true; return tree; },
    unmount() { cleanup.forEach((fn) => fn?.()); },
  };
}
function nodes(value) {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap(nodes);
  return [value, ...nodes(value.props?.children), ...nodes(value.props?.actions)];
}
function label(value) {
  if (value == null || value === false) return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(label).join("");
  return label(value.props?.children);
}
const button = (tree, name) => nodes(tree).find((node) => node.type === "button" && label(node).trim() === name);
const input = (tree) => nodes(tree).find((node) => node.props?.["data-testid"] === "notes-backup-input");
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function chooseFile(h, raw) {
  input(h.render()).props.onChange({ currentTarget: { files: [{ text: async () => raw }], value: "synthetic.json" } });
  await tick();
  return h.render();
}

const storage = new Map();
const workingStorage = { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) };
const corruptedRaw = ' \n{"broken":"中文原文\n';
const restoredNote = { id: "restored", kind: "复盘", title: "恢复后的研究记录", content: "原始结论", ts: 10 };
const backup = notes.createNotesBackupJson([restoredNote]);
let originalStorage;
test.beforeEach(() => {
  originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { value: workingStorage, configurable: true });
  storage.clear();
  storage.set("vr-notes", corruptedRaw);
  storage.set("vr-llm", "SYNTHETIC_CONFIG");
  storage.set("vr-askai-chat:test", "SYNTHETIC_CHAT");
});
test.afterEach(() => {
  if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
  else delete globalThis.localStorage;
});

test("corrupt Notes renders recovery, downloads only the original raw data, and never claims empty", async () => {
  const h = createHarness();
  const tree = h.render();
  assert.ok(button(tree, "从备份替换损坏记录"));
  assert.equal(button(tree, "导入备份").props.disabled, true);
  assert.equal(button(tree, "导出备份").props.disabled, true);
  assert.doesNotMatch(label(tree), /还没有记录/);
  button(tree, "下载损坏原始数据").props.onClick();
  assert.equal(h.downloads.length, 1);
  assert.equal(await h.downloads[0].text(), corruptedRaw);
  assert.equal(storage.get("vr-notes"), corruptedRaw);
  assert.match(label(h.render()), /原始数据仍保留/);
});

test("recovery UI validates before confirmation, preserves cancel and quota failures, then resumes merge import", async () => {
  let accept = false;
  const confirmations = [];
  const h = createHarness((message) => { confirmations.push(message); return accept; });
  let tree = await chooseFile(h, "invalid-json");
  assert.equal(confirmations.length, 0);
  assert.match(label(tree), /不是有效的 JSON/);
  assert.equal(storage.get("vr-notes"), corruptedRaw);

  tree = await chooseFile(h, backup);
  assert.equal(confirmations.length, 1);
  assert.match(confirmations[0], /备份已校验，共 1 条研究记录/);
  assert.match(confirmations[0], /仅替换研究记录/);
  assert.match(label(tree), /已取消替换/);
  assert.equal(storage.get("vr-notes"), corruptedRaw);

  accept = true;
  Object.defineProperty(globalThis, "localStorage", {
    value: { ...workingStorage, setItem() { throw new DOMException("full", "QuotaExceededError"); } }, configurable: true,
  });
  tree = await chooseFile(h, backup);
  assert.match(label(tree), /无法保存/);
  assert.doesNotMatch(label(tree), /已从备份恢复/);
  assert.equal(storage.get("vr-notes"), corruptedRaw);
  assert.equal(button(tree, "从备份替换损坏记录").props.disabled, false);

  Object.defineProperty(globalThis, "localStorage", { value: workingStorage, configurable: true });
  tree = await chooseFile(h, backup);
  assert.match(label(tree), /已从备份恢复 1 条研究记录/);
  assert.match(label(createHarness().render()), /恢复后的研究记录/);
  assert.equal(button(tree, "从备份替换损坏记录"), undefined);
  assert.equal(button(tree, "导入备份").props.disabled, false);

  const afterRecovery = notes.createNotesBackupJson([
    { ...restoredNote, content: "不能覆盖" }, { ...restoredNote, id: "new", title: "新记录", ts: 20 },
  ]);
  tree = await chooseFile(h, afterRecovery);
  assert.match(label(tree), /已导入 1 条研究记录，另有 1 条重复/);
  assert.equal(confirmations.length, 3, "healthy imports must not use replacement confirmation");
  assert.equal(notes.loadNotes().find((note) => note.id === "restored").content, "原始结论");
  assert.equal(storage.get("vr-llm"), "SYNTHETIC_CONFIG");
  assert.equal(storage.get("vr-askai-chat:test"), "SYNTHETIC_CHAT");
});

test("leaving Notes during file reading prevents a late confirmation or replacement", async () => {
  let resolveText, confirmed = false;
  const pendingText = new Promise((resolve) => { resolveText = resolve; });
  const h = createHarness(() => { confirmed = true; return true; });
  input(h.render()).props.onChange({ currentTarget: { files: [{ text: () => pendingText }], value: "synthetic.json" } });
  assert.equal(button(h.render(), "从备份替换损坏记录").props.disabled, true);
  h.unmount();
  resolveText(backup);
  await tick();
  assert.equal(confirmed, false);
  assert.equal(storage.get("vr-notes"), corruptedRaw);
});

test("unreadable storage does not offer destructive recovery or claim an empty collection", () => {
  Object.defineProperty(globalThis, "localStorage", {
    value: { ...workingStorage, getItem() { throw new Error("denied"); } }, configurable: true,
  });
  const tree = createHarness().render();
  assert.match(label(tree), /无法读取/);
  assert.equal(button(tree, "从备份替换损坏记录"), undefined);
  assert.equal(button(tree, "下载损坏原始数据"), undefined);
  assert.doesNotMatch(label(tree), /还没有记录/);
});

test("Notes refreshes relevant storage events and removes listeners on unmount", () => {
  const h = createHarness();
  assert.ok(button(h.render(), "从备份替换损坏记录"));
  storage.set("vr-notes", JSON.stringify([restoredNote]));
  h.storageChanged("unrelated-key");
  assert.ok(button(h.render(), "从备份替换损坏记录"), "unrelated storage changes do not alter the list");
  h.storageChanged("vr-notes");
  assert.equal(button(h.render(), "从备份替换损坏记录"), undefined);
  assert.match(label(h.render()), /恢复后的研究记录/);
  storage.set("vr-notes", "[]");
  h.notesChanged();
  assert.doesNotMatch(label(h.render()), /恢复后的研究记录/);
  h.unmount();
  storage.set("vr-notes", corruptedRaw);
  h.storageChanged(null);
  assert.equal(button(h.render(), "从备份替换损坏记录"), undefined, "unmounted subscriptions cannot update state");
});
