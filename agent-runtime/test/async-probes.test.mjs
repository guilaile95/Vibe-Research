import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { AgentRuntime } from "../src/runtime.mjs";
import { runProbe } from "../src/probe.mjs";
import { effectiveMcpNames } from "../src/security.mjs";

function bare() {
  const runtime = Object.create(AgentRuntime.prototype);
  Object.assign(runtime, { sessions: new Map(), pending: new Map(), paths: { codexHome: "/synthetic" },
    binary: "never-executed", sourceEnv: {}, loginState: null, probeController: new AbortController() });
  return runtime;
}

test("status singleflight shares slow probe, caches briefly, never calls a model", async () => {
  const runtime = bare();
  let release, calls = 0;
  const held = new Promise(resolve => { release = resolve; });
  runtime.probeProcess = async (_binary, args) => {
    calls++;
    if (args[0] === "--version") { await held; return { status: 0, stdout: "codex-cli 0.149.0" }; }
    return { status: 0, stdout: "Logged in using ChatGPT" };
  };
  const a = runtime.status(), b = runtime.status();
  assert.equal(calls, 1);
  let ticked = false;
  await new Promise(resolve => setImmediate(() => { ticked = true; resolve(); }));
  assert.equal(ticked, true);
  release();
  assert.deepEqual(await a, await b);
  assert.equal(calls, 2);
  assert.equal((await runtime.status()).modelConnectivity, "unknown");
  assert.equal(calls, 2);
  runtime.statusCache.at -= 2001;
  await runtime.status();
  assert.equal(calls, 4);
});

test("cancel during pending status is immediate and never creates an SDK session", async () => {
  const runtime = bare();
  let release;
  runtime.status = () => new Promise(resolve => { release = resolve; });
  const turn = runtime.chat({ session: "pending", message: "synthetic" });
  assert.deepEqual(runtime.cancel("pending"), { cancelled: true });
  await assert.rejects(turn, error => error.code === "CANCELLED");
  assert.equal(runtime.pending.size, 0);
  assert.equal(runtime.sessions.size, 0);
  release({ installed: true, authenticated: true });
});

test("admission includes status phase and rejects a fifth active turn", async () => {
  const runtime = bare();
  runtime.status = () => new Promise(() => {});
  const turns = Array.from({ length: 4 }, (_, i) => runtime.chat({ session: `s${i}`, message: "synthetic" }));
  await assert.rejects(runtime.chat({ session: "fifth", message: "synthetic" }), error => error.code === "SESSION_BUSY");
  for (let i = 0; i < 4; i++) runtime.cancel(`s${i}`);
  const results = await Promise.allSettled(turns);
  assert.ok(results.every(result => result.status === "rejected" && result.reason.code === "CANCELLED"));
});

function childFixture() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
  let killed = 0;
  child.kill = () => { killed++; }; // Closing separately proves ownership until actual exit.
  return { child, get killed() { return killed; } };
}

test("probe cancellation kills child but settles only after process close", async () => {
  const fixture = childFixture();
  const controller = new AbortController();
  let done = false;
  const promise = runProbe("synthetic", [], { signal: controller.signal, spawnProcess: () => fixture.child }).then(result => { done = true; return result; });
  controller.abort();
  await Promise.resolve();
  assert.equal(fixture.killed, 1); assert.equal(done, false);
  fixture.child.emit("close", null, "SIGKILL");
  assert.equal((await promise).error.code, "ABORT_ERR");
});

test("probe timeout and output cap are bounded without synchronous subprocesses", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  for (const reason of ["timeout", "output"]) {
    const fixture = childFixture();
    const promise = runProbe("synthetic", [], { timeout: 25, maxBuffer: 10, spawnProcess: () => fixture.child });
    if (reason === "timeout") t.mock.timers.tick(25);
    else fixture.child.stdout.emit("data", Buffer.alloc(11));
    assert.equal(fixture.killed, 1);
    fixture.child.emit("close", null, "SIGKILL");
    assert.equal((await promise).error.code, reason === "timeout" ? "ETIMEDOUT" : "MAX_BUFFER");
  }
});

test("MCP async discovery preserves disable flags and cancellation signal", async () => {
  const controller = new AbortController();
  const names = await effectiveMcpNames({ binary: "synthetic", codexHome: "/synthetic", cwd: "/synthetic", signal: controller.signal,
    run: async (_binary, args, options) => {
      assert.ok(args.includes("features.apps=false"));
      assert.ok(args.includes("features.plugins=false"));
      assert.equal(options.signal, controller.signal);
      assert.equal(options.timeout, 2000);
      return { status: 0, stdout: '[{"name":"b"},{"name":"a"},{"name":"a"}]' };
    } });
  assert.deepEqual(names, ["a", "b"]);
});
