import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../src/lib/credentialMutations.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const config = { provider: "openai-compatible", model: "synthetic", baseURL: "https://synthetic.invalid", apiKey: "SYNTHETIC_ONLY", revision: "1" };
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {resolve,reject,promise}; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture({ beforePut, storageFailure = false, statusReply } = {}) {
  const state = { revision: 1, configured: true, local: {...config}, calls: [] };
  const status = () => { const value = { revision: String(state.revision), configured: state.configured }; return statusReply ? statusReply(value) : value; };
  const api = {
    async getAiCredentialStatus() { state.calls.push("GET"); return status(); },
    async putAiCredential(payload) {
      assert.deepEqual(Object.keys(payload).sort(), ["apiKey", "baseURL", "expectedRevision", "model", "provider"]);
      state.calls.push(["PUT", payload.expectedRevision]);
      await beforePut?.();
      if (payload.expectedRevision !== String(state.revision)) throw Error("CREDENTIAL_REVISION_CONFLICT");
      state.revision++; state.configured = true; return status();
    },
    async deleteAiCredential(observed) {
      state.calls.push(["DELETE", observed]);
      assert.ok(Number(observed) <= state.revision);
      state.revision++; state.configured = false; return status();
    },
  };
  const exports = {};
  vm.runInNewContext(source, { exports, AbortSignal, Error, require: name => name === "./api.ts" ? {api} : {
    loadLlm: () => state.local,
    clearLlm() { if (storageFailure) throw Error("denied"); state.local = null; },
    saveLlm(value) { if (storageFailure) throw Error("quota"); state.local = value; },
  }});
  return {state, ...exports};
}

test("same-tab clear intent invalidates a pending save and survives component lifetime", async () => {
  const gate = deferred();
  const f = fixture({ beforePut: () => gate.promise });
  const saving = f.saveCredential(config);
  await tick();
  const clearing = f.clearCredential();
  assert.equal(f.state.local, null);
  gate.resolve();
  assert.equal(await saving, false);
  assert.equal(await clearing, true);
  assert.equal(f.state.configured, false);
  assert.equal(f.state.local, null);
  assert.equal(f.state.revision, 3);
});

test("external clear before delayed PUT cannot make old intent acquire a fresh generation", async () => {
  const gate = deferred();
  const f = fixture({ beforePut: () => gate.promise });
  const saving = f.saveCredential(config);
  await tick();
  // Simulates another tab's server clear before the original request executes.
  f.state.revision = 2; f.state.configured = false; f.state.local = null;
  gate.resolve();
  await assert.rejects(saving, /CONFLICT/);
  assert.equal(f.state.configured, false);
  assert.equal(f.state.local, null);
  assert.equal(f.state.revision, 2);
  assert.equal(f.state.calls.filter(call => call === "GET").length, 0,
    "no asynchronously executed initial GET can lend a new generation to old intent");
});

test("explicit new save can use a generation observed before its click", async () => {
  const f = fixture();
  f.state.revision = 2; f.state.configured = false; f.state.local = null;
  assert.equal(await f.saveCredential(config, "2"), true);
  assert.equal(f.state.local.revision, "3");
});

test("unknown save failure is never retried and does not block subsequent clear", async () => {
  const f = fixture({ beforePut: () => { throw Error("unknown result"); } });
  await assert.rejects(f.saveCredential(config), /unknown result/);
  assert.equal(await f.clearCredential(), true);
  assert.equal(f.state.configured, false);
  assert.equal(f.state.calls.filter(call => Array.isArray(call) && call[0] === "PUT").length, 1);
});

test("storage-denied browser cannot report save or clear success", async () => {
  const f = fixture({ storageFailure: true });
  await assert.rejects(f.saveCredential(config), /后台凭据已保存.*浏览器保存失败/);
  await assert.rejects(f.clearCredential(), /后台凭据已清除.*浏览器凭据仍未清除/);
  assert.equal(f.state.configured, false);
});

test("actual shared transports reject stale generations before model submission", async () => {
  const { request, streamNdjson, checkCredentialGeneration } = await import("../src/lib/api.ts");
  const originalFetch = globalThis.fetch, originalStorage = globalThis.localStorage;
  const calls = [];
  globalThis.localStorage = { getItem: key => key === "vr-llm" ? JSON.stringify(config) : null };
  let current = { configured: false, revision: "2" };
  globalThis.fetch = async (url, options) => {
    calls.push(url);
    assert.equal(url, "/api/ai/credential-status", "stale credentials must never reach model route");
    return Response.json(current);
  };
  try {
    for (const operation of [
      () => request("/native-intel/ai/analyze", "POST", { llm: config }),
      () => streamNdjson("/chat", { llm: config }),
      () => checkCredentialGeneration("/debate", { llm: config }),
    ]) await assert.rejects(operation(), /配置已变化/);
    assert.equal(calls.length, 3);
    current = { configured: true, revision: "1" };
    await checkCredentialGeneration("/chat", { llm: config });
    await assert.rejects(checkCredentialGeneration("/chat", { llm: { ...config, apiKey: "SYNTHETIC_OTHER" } }), /配置已变化/);
    const before = calls.length;
    await checkCredentialGeneration("/ai/connection-test", { llm: { ...config, revision: undefined } });
    assert.equal(calls.length, before, "explicit draft connection probe remains independent");
    current = null;
    await assert.rejects(checkCredentialGeneration("/chat", { llm: config }), /配置已变化/);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalStorage === undefined) delete globalThis.localStorage; else globalThis.localStorage = originalStorage;
  }
});

for (const [name, statusReply] of [
  ["missing revision", value => ({ configured: value.configured })],
  ["malformed revision", value => ({ ...value, revision: "02" })],
  ["wrong generation", value => ({ ...value, revision: "9" })],
]) test(`malformed mutation receipt cannot claim saved mirror: ${name}`, async () => {
  const f = fixture({ statusReply });
  await assert.rejects(f.saveCredential(config), /配置已变化/);
  assert.equal(f.state.local.revision, "1");
});

test("all three actual transports preserve dispatch revision without mutating caller", async () => {
  const api = await import("../src/lib/api.ts");
  const legacy = await import("../src/lib/ndjson.ts");
  const golden = JSON.parse(readFileSync(new URL("./fixtures/credential-model-wire.json", import.meta.url), "utf8"));
  const originalFetch = globalThis.fetch, originalStorage = globalThis.localStorage;
  const bodies = [];
  globalThis.localStorage = { getItem: key => key === "vr-llm" ? JSON.stringify(config) : null };
  globalThis.fetch = async (url, options) => {
    if (url === "/api/ai/credential-status") return Response.json({ configured: true, revision: "1" });
    bodies.push(JSON.parse(options.body));
    if (url === "/api/synthetic-json") return Response.json({ ok: true });
    return new Response('{"type":"delta","text":"synthetic"}\n{"type":"done","rounds":1,"trace":[]}\n');
  };
  const body = { llm: Object.freeze({...config}) };
  try {
    await api.request("/synthetic-json", "POST", body);
    await api.streamNdjson("/synthetic-stream", body);
    await legacy.streamNdjson("/api/synthetic-legacy", body, () => {});
    assert.deepEqual(bodies, [golden, golden, golden]);
    assert.equal(body.llm.revision, "1");
    assert.deepEqual(api.modelRequestWireBody({ llm: { ...config, unknown: "preserved-for-backend-rejection" } }),
      { llm: { ...golden.llm, unknown: "preserved-for-backend-rejection" } });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalStorage === undefined) delete globalThis.localStorage; else globalThis.localStorage = originalStorage;
  }
});
