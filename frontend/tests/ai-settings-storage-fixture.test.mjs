import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";
import { config, chatKey, readPaths, readReply, validSyntheticStream, observeSyntheticStreams } from "./e2e/ai-settings-storage.fixture.mjs";

test("read whitelist covers actual MyReports and Settings startup contracts only", () => {
  for (const path of readPaths) {
    const search = path.endsWith("/profile") ? "?profile_id=default" : "";
    assert.ok(readReply("GET", path, search), path);
    for (const method of ["POST", "PUT", "DELETE", "PATCH"]) assert.equal(readReply(method, path, search), null);
    assert.equal(readReply("GET", path, "?unrequested=true"), null);
  }
  assert.equal(readReply("GET", "/api/agent-runtime/status"), null);
  assert.equal(readReply("GET", "/api/valuation"), null);
  assert.deepEqual(readReply("GET", "/api/myreports")[0].sector_keys, []);
  assert.deepEqual(readReply("GET", "/api/native-intel/sources"), { sources: [] });
  const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  for (const path of ["/myreports", "/ai/credential-status", "/native-intel/sources", "/native-intel/config", "/native-intel/filter/profile?profile_id="]) assert.ok(api.includes(path), path);
  const runtime = readFileSync(new URL("../src/lib/backendRuntime.ts", import.meta.url), "utf8");
  for (const path of ["/health", "/runtime-info"]) assert.ok(runtime.includes(path));
});
test("stream whitelist rejects non-synthetic credentials, endpoints, methods and report scope", () => {
  const chat = { llm: config, messages: [{ role: "user", content: "SYNTHETIC_QUESTION" }], report_ids: ["synthetic-report"] };
  assert.equal(validSyntheticStream("POST", "/api/chat", chat), true);
  assert.equal(validSyntheticStream("POST", "/api/ai/connection-test", { llm: config }), true);
  for (const [method, path, body] of [
    ["GET", "/api/chat", chat], ["POST", "/api/chat", { ...chat, llm: { ...config, apiKey: 123 } }], ["POST", "/api/chat", { ...chat, report_ids: ["other"] }],
    ["POST", "/api/chat", { ...chat, llm: { ...config, baseURL: "https://example.com" } }],
    ["POST", "/api/chat", { ...chat, llm: { ...config, apiKey: "not-synthetic" } }],
    ["POST", "/api/ai/credential", { llm: config }],
    ["POST", "/api/ai/connection-test", { llm: config, messages: [] }],
  ]) assert.equal(validSyntheticStream(method, path, body), false);
  assert.match(chatKey, /^vr-askai-chat:\/my-reports#reports:synthetic-report@openai-compatible:/);
});
test("stream observation records real abort but lets late chunks reach parsing; unrelated fetch signal stays native", async () => {
  const calls = [], storage = {}, listeners = {};
  const window = { addEventListener: (name, fn) => { listeners[name] = fn; }, fetch: async (input, init) => {
    calls.push({ input, init }); let read = 0;
    return { body: { getReader: () => ({ read: async () => ++read === 1 ? { done: false, value: new Uint8Array([1]) } : { done: true } }) } };
  } };
  vm.runInNewContext(`(${observeSyntheticStreams.toString()})()`, { window, localStorage: storage, URL, location: { href: "http://127.0.0.1/my-reports" } });
  const controller = new AbortController();
  await window.fetch("/api/health", { signal: controller.signal });
  assert.equal(calls[0].init.signal, controller.signal);
  const response = await window.fetch("/api/chat", { signal: controller.signal });
  assert.equal(calls[1].init.signal, undefined);
  controller.abort(); assert.equal(window.__streams[0].aborted, true);
  const reader = response.body.getReader(); await reader.read(); await reader.read();
  assert.equal(window.__streams[0].chunks, 1); assert.equal(window.__streams[0].eof, true);
  listeners.storage({ key: "vr-sidebar", storageArea: storage, isTrusted: true });
  assert.equal(window.__storageEvents[0].local, true); assert.equal(window.__storageEvents[0].trusted, true);
});
