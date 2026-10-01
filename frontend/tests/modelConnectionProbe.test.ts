import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createModelConnectionProbe, modelProbeDestination, canonicalModelProbeURL, type ProbeState } from "../src/lib/modelConnectionProbe.ts";
import { testModelConnection, type LlmConfig } from "../src/lib/llm.ts";

const cfg: LlmConfig = { provider: "openai", model: "synthetic", baseURL: "https://example.com/v1", apiKey: "fixture-only" };
function deferred() { let resolve!: (value?: unknown) => void; let reject!: (error: unknown) => void; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return {promise,resolve,reject}; }
const tick = () => new Promise((resolve) => setImmediate(resolve));

test("manual start tests explicit draft once, not on construction; result is qualified and not saved", async () => {
  const states: ProbeState[] = []; const calls: LlmConfig[] = []; const pending = deferred();
  const probe = createModelConnectionProbe(async (config) => { calls.push(config); await pending.promise; }, s=>states.push(s));
  assert.equal(calls.length, 0);
  const first = probe.start(cfg); const second = probe.start(cfg);
  assert.equal(calls.length, 1); assert.deepEqual(calls[0], cfg);
  pending.resolve(); await Promise.all([first, second]);
  assert.equal(states.at(-1)?.status, "success");
  assert.match(states.at(-1)!.message, /不验证模型质量.*不代表配置已保存/);
  assert.doesNotMatch(JSON.stringify(states), /fixture-only/);
  probe.dispose();
});

test("cancel and dispose abort the request and discard late completions", async () => {
  for (const action of ["cancel", "dispose"] as const) {
    const states: ProbeState[] = []; const pending = deferred(); let signal!: AbortSignal;
    const probe = createModelConnectionProbe(async (_config, s) => {signal=s; await pending.promise;}, s=>states.push(s));
    const task = probe.start(cfg); probe[action](); assert.equal(signal.aborted,true);
    const length = states.length; pending.resolve(); await task;
    assert.equal(states.length,length); assert.notEqual(states.at(-1)?.status,"success");
  }
});

test("configuration A to B to A cannot revive an old result or clear the new pending request", async () => {
  const first = deferred(), second = deferred(); let n=0; const states: ProbeState[]=[];
  const probe=createModelConnectionProbe(()=>++n===1?first.promise:second.promise,s=>states.push(s));
  const old=probe.start(cfg); probe.invalidate(); probe.invalidate(); const latest=probe.start(cfg);
  first.resolve(); await old; assert.equal(states.at(-1)?.status,"pending");
  second.resolve(); await latest; assert.equal(states.at(-1)?.status,"success");
});

test("timeout aborts locally without promising the provider stopped billing", async () => {
  const states: ProbeState[]=[]; const pending=deferred(); let signal!:AbortSignal;
  const probe=createModelConnectionProbe((_cfg,s)=>{signal=s;return pending.promise;},s=>states.push(s),5);
  const task=probe.start(cfg); await new Promise(r=>setTimeout(r,20));
  assert.equal(signal.aborted,true); assert.equal(states.at(-1)?.status,"error");
  assert.match(states.at(-1)!.message,/仍可能计费/); pending.resolve(); await task;
  assert.equal(states.at(-1)?.status,"error");
});

test("all CLI modes avoid transport and failures never expose exception contents", async () => {
  let calls=0; const states:ProbeState[]=[];
  const probe=createModelConnectionProbe(async()=>{calls++;throw new Error("SYNTHETIC_PRIVATE_DETAIL");},s=>states.push(s));
  await probe.start({...cfg,provider:"cli-codex"}); assert.equal(calls,0);
  await probe.start(cfg); assert.equal(calls,1); assert.doesNotMatch(JSON.stringify(states),/SYNTHETIC_PRIVATE_DETAIL/);
});

test("display destination strips paths and rejects embedded credentials, query, fragment and unsupported schemes", () => {
  assert.equal(modelProbeDestination("https://example.com/v1"),"https://example.com");
  for(const url of ["https://user:password@example.com", "https://example.com?key=secret", "https://example.com#secret", "file:///tmp/test", "bad"]) assert.equal(modelProbeDestination(url),null);
});

test("connection helper sends only explicit LLM config and preserves backend versus provider auth distinction", async (t) => {
  const original=globalThis.fetch; const captured:Array<{url:unknown;body:unknown}>=[];
  let outcome="done";
  globalThis.fetch=async (url,init)=>{
    captured.push({url,body:JSON.parse(String(init?.body))});
    if(outcome==="backend401") return new Response("{}",{status:401});
    return new Response(outcome==="provider401" ? '{"type":"error","message":"模型连接测试失败，请检查配置后重试"}\n' : '{"type":"done","trace":[],"rounds":1}\n',{status:200});
  };
  t.after(()=>{globalThis.fetch=original;});
  await testModelConnection(cfg);
  assert.deepEqual(captured[0],{url:"/api/ai/connection-test",body:{llm:cfg}});
  outcome="provider401"; await assert.rejects(testModelConnection(cfg),e=>e instanceof Error && !e.message.includes("VR_API_KEY"));
  outcome="backend401"; await assert.rejects(testModelConnection(cfg),e=>e instanceof Error && e.message.includes("VR_API_KEY"));
  await tick();
});


test("disclosed recipient and submitted canonical URL cannot diverge across parser quirks", () => {
  for (const url of [String.raw`https://trusted.example\@other.example/v1`, "https://trusted.example\n@other.example/v1", "https://example.com/with space", "https://example.com?", "https://example.com#"]) {
    assert.equal(canonicalModelProbeURL(url), null);
    assert.equal(modelProbeDestination(url), null);
  }
  assert.equal(canonicalModelProbeURL("HTTPS://EXAMPLE.COM:443/v1"), "https://example.com/v1");
  assert.equal(canonicalModelProbeURL("http://0x7f000001/v1"), "http://127.0.0.1/v1");
  const source = readFileSync(new URL("../src/pages/Settings.tsx", import.meta.url), "utf8");
  assert.match(source, /probe\.start\(\{ provider: providerOf\(apiId\), baseURL: probeBaseURL/);
});
