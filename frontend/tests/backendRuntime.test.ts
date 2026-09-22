import assert from "node:assert/strict";
import test from "node:test";

import { readBackendRuntime } from "../src/lib/backendRuntime.ts";

const health = { ok: true, service: "vibe-research-api", version: "1.2.3" };
const runtime = {
  service: "vibe-research-api",
  version: "1.2.3",
  git_sha: "a".repeat(40),
  source_state: "modified",
  source_directory: "E:/fixture/checkout",
  working_directory: "E:/fixture/checkout/backend",
};

test("runtime fetch reuses relative proxy and saved auth, returning only display fields", async (t) => {
  const calls: string[] = [];
  t.mock.method(globalThis, "fetch", async (input, options) => {
    const url = String(input);
    calls.push(url);
    assert.equal(options?.method, "GET");
    assert.equal(new Headers(options?.headers).get("Authorization"), "Bearer fixture-access-key");
    assert.ok(options?.signal instanceof AbortSignal);
    return Response.json(url === "/api/health" ? health : { data: {
      ...runtime, token: "fixture-sensitive-token", proxy_url: "https://user:password@proxy.invalid",
    } });
  });
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: (key: string) => key === "vr-access-key" ? "fixture-access-key" : null,
  } });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else Reflect.deleteProperty(globalThis, "localStorage");
  });
  const check = await readBackendRuntime();
  assert.deepEqual(calls.sort(), ["/api/health", "/api/runtime-info"]);
  assert.equal(check.connected, true);
  assert.equal(check.infoStatus, "available");
  assert.deepEqual(check.runtime, runtime);
  assert.doesNotMatch(JSON.stringify(check), /fixture-sensitive-token|password|proxy\.invalid/);
});

test("older and protected backends keep independent service connectivity", async (t) => {
  for (const [status, expected] of [[404, "unsupported"], [401, "auth_required"], [403, "auth_required"], [500, "unavailable"]] as const) {
    const mock = t.mock.method(globalThis, "fetch", async (input) => (
      String(input) === "/api/health" ? Response.json(health)
        : Response.json({ detail: "fixture-sensitive-token at https://proxy.invalid" }, { status })
    ));
    const check = await readBackendRuntime();
    assert.equal(check.connected, true);
    assert.equal(check.version, "1.2.3");
    assert.equal(check.runtime, null);
    assert.equal(check.infoStatus, expected);
    assert.doesNotMatch(JSON.stringify(check), /fixture-sensitive-token|proxy\.invalid/);
    mock.mock.restore();
  }
});

test("network failure and HTML proxy fallback never claim a healthy backend", async (t) => {
  for (const htmlFallback of [false, true]) {
    const mock = t.mock.method(globalThis, "fetch", async () => {
      if (htmlFallback) return new Response("<html>Frontend only</html>");
      throw new TypeError("fixture-sensitive-token");
    });
    assert.deepEqual(await readBackendRuntime(), {
      connected: false, version: null, runtime: null, infoStatus: "unavailable",
    });
    mock.mock.restore();
  }
});

test("invalid or unknown Git identity is never presented as a real SHA", async (t) => {
  for (const gitFields of [
    { git_sha: "fixture-sensitive-token", source_state: "clean" },
    { git_sha: "a".repeat(40), source_state: "unknown" },
  ]) {
    const mock = t.mock.method(globalThis, "fetch", async (input) => Response.json(
      String(input) === "/api/health" ? health : { data: { ...runtime, ...gitFields } },
    ));
    const check = await readBackendRuntime();
    assert.equal(check.runtime?.git_sha, null);
    assert.equal(check.runtime?.source_state, "unknown");
    mock.mock.restore();
  }
});
