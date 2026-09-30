import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { firstResearchStatus, readFirstResearchLocalState, subscribeFirstResearchState } from "../src/lib/firstResearchStatus.ts";
import { LLM_CHANGED_EVENT } from "../src/lib/llm.ts";
import { NOTES_CHANGED_EVENT } from "../src/lib/notes.ts";

function fixture(t: test.TestContext, values: Record<string, string>, denied = false) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: (key: string) => { if (denied) throw new Error("denied"); return values[key] ?? null; },
  } });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else Reflect.deleteProperty(globalThis, "localStorage");
  });
}
const apiConfig = JSON.stringify({ provider: "openai", model: "fixture", baseURL: "https://fixture.invalid", apiKey: "fixture-secret" });

test("empty storage and unknown backend do not claim a working model", (t) => {
  fixture(t, {});
  const status = firstResearchStatus(readFirstResearchLocalState(), null);
  assert.match(status.browser, /未读取到完整配置/);
  assert.match(status.mirror, /状态未知/);
  assert.match(status.model, /不代表模型已成功回答/);
  assert.match(status.research, /尚无本地研究记录/);
});

test("saved credentials distinguish configured from model success and research", (t) => {
  fixture(t, { "vr-llm": apiConfig });
  const local = readFirstResearchLocalState();
  assert.doesNotMatch(JSON.stringify(local), /fixture-secret|fixture.invalid/);
  const status = firstResearchStatus(local, { configured: true, provider: "openai" });
  assert.match(status.browser, /已读取到保存/);
  assert.match(status.model, /不代表模型已成功回答/);
  assert.match(status.capability, /受控查询工具/);
  assert.match(status.mirror, /不代表.*完全一致/);
  assert.match(status.research, /尚无/);
});

test("failed or unsynced backend mirror never appears saved", (t) => {
  fixture(t, { "vr-llm": apiConfig });
  const local = readFirstResearchLocalState();
  assert.match(firstResearchStatus(local, null).mirror, /状态未知/);
  assert.match(firstResearchStatus(local, { configured: false, provider: null }).mirror, /尚未保存/);
  assert.match(firstResearchStatus(local, { configured: true, provider: "cli-codex" }).mirror, /接入方式不同/);
});

test("valid saved notes confirm persistence without retaining research content", (t) => {
  fixture(t, { "vr-notes": JSON.stringify([{ id: "fixture", kind: "问AI", title: "private title", content: "private text", ts: 1 }]) });
  const local = readFirstResearchLocalState();
  assert.deepEqual(local, { provider: null, noteCount: 1, notesReadable: true });
  assert.match(firstResearchStatus(local, null).research, /已有 1 条/);
});

test("corrupt notes are unknown rather than a false empty research history", (t) => {
  fixture(t, { "vr-notes": "not-json" });
  assert.match(firstResearchStatus(readFirstResearchLocalState(), null).research, /无法读取/);
});

test("denied storage does not invent successful setup or empty research history", (t) => {
  fixture(t, {}, true);
  const status = firstResearchStatus(readFirstResearchLocalState(), null);
  assert.match(status.browser, /未读取到完整配置/);
  assert.match(status.research, /无法读取/);
});

test("provider, research, cross-tab and focus changes refresh and clean up listeners", (t) => {
  const values = { "vr-llm": apiConfig };
  fixture(t, values);
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  const target = new EventTarget();
  Object.defineProperty(globalThis, "window", { configurable: true, value: target });
  t.after(() => { if (previous) Object.defineProperty(globalThis, "window", previous); else Reflect.deleteProperty(globalThis, "window"); });
  let calls = 0;
  let state = readFirstResearchLocalState();
  const unsubscribe = subscribeFirstResearchState(() => { calls += 1; state = readFirstResearchLocalState(); });
  values["vr-llm"] = JSON.stringify({ provider: "cli-codex", model: "codex" });
  for (const event of [LLM_CHANGED_EVENT, NOTES_CHANGED_EVENT, "storage", "focus"]) target.dispatchEvent(new Event(event));
  assert.equal(calls, 4);
  assert.match(firstResearchStatus(state, null).capability, /当前页面上下文/);
  assert.match(firstResearchStatus(state, null).model, /不代表模型已成功回答/);
  unsubscribe();
  target.dispatchEvent(new Event(LLM_CHANGED_EVENT));
  assert.equal(calls, 4);
});

test("compact Settings guidance uses real routes and never starts a model call", () => {
  const card = readFileSync(new URL("../src/components/settings/FirstResearchStatusCard.tsx", import.meta.url), "utf8");
  const settings = readFileSync(new URL("../src/pages/Settings.tsx", import.meta.url), "utf8");
  assert.match(card, /<details/);
  assert.match(card, /to="\/stock-data"/);
  assert.match(card, /to="\/notes"/);
  assert.match(card, /不验证研究质量/);
  assert.doesNotMatch(card, /chatStream|fetch\(|api\./);
  assert.match(settings, /配置已保存到本机浏览器和后台；尚未验证模型调用/);
  assert.match(settings, /<FirstResearchStatusCard mirror=\{scheduledStatus\}/);
});


test("legacy CLI configuration never implies API tool support", (t) => {
  fixture(t, { "vr-llm": JSON.stringify({ provider: "cli-legacy", model: "fixture", baseURL: "https://fixture.invalid", apiKey: "fixture-secret" }) });
  const status = firstResearchStatus(readFirstResearchLocalState(), null);
  assert.match(status.capability, /旧版 CLI 配置/);
  assert.doesNotMatch(status.capability, /API 对话/);
  assert.match(status.model, /不代表模型已成功回答/);
});
