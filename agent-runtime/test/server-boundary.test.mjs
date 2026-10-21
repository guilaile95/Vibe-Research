import test from "node:test";
import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { EventEmitter } from "node:events";
import { createAgentServer } from "../src/server.mjs";

async function request({ path = "/login", method = "POST", headers = {}, body = "{}", port = 18302 } = {}) {
  const calls = [];
  const runtime = {
    status() { calls.push("status"); return {}; },
    login() { calls.push("login"); return { state: "started" }; },
    cancel() { calls.push("cancel"); return { cancelled: true }; },
    async chat(input) { calls.push("chat"); input.onEvent({ type: "done" }); },
  };
  const server = createAgentServer(runtime);
  const req = Readable.from([Buffer.from(body)]);
  Object.assign(req, { url: path, method, socket: { localPort: port }, headers: {
    host: `127.0.0.1:${port}`, "content-type": "application/json", ...headers,
  }});
  const res = new EventEmitter();
  let output = "";
  const done = new Promise(resolve => {
    res.writeHead = status => { res.status = status; res.headersSent = true; };
    res.write = text => { output += text; };
    res.end = text => { output += text ?? ""; resolve(); };
  });
  server.emit("request", req, res);
  await done;
  return { status: res.status, calls, output };
}

test("host, browser-origin and media-type rejections precede every side effect", async () => {
  for (const path of ["/login", "/cancel", "/chat", "/continue"]) {
    for (const headers of [
      { host: "attacker.example:18302" }, { host: "127.0.0.1:8911" },
      { host: "2130706433:18302" }, { host: "localhost.attacker.example:18302" },
      { origin: "null" }, { origin: "http://localhost:5173" },
      { "sec-fetch-site": "cross-site" }, { "sec-fetch-site": "same-site" },
      { "content-type": "text/plain" }, { "content-type": "application/x-www-form-urlencoded" },
    ]) {
      const result = await request({ path, headers });
      assert.ok([403, 415].includes(result.status));
      assert.deepEqual(result.calls, []);
    }
    for (const body of ["", "null", "[]", '"text"', "1", "{invalid"]) {
      const result = await request({ path, body });
      assert.equal(result.status, 400);
      assert.deepEqual(result.calls, []);
    }
  }
});
test("direct backend requests on configured port preserve login, status, cancel and stream", async () => {
  for (const host of ["127.0.0.1:18302", "localhost:18302", "[::1]:18302"]) {
    assert.equal((await request({ headers: { host } })).status, 202);
  }
  for (const path of ["/cancel", "/chat", "/continue"]) {
    const result = await request({ path, headers: { "content-type": "application/json; charset=utf-8" } });
    assert.equal(result.status, 200);
    assert.equal(result.calls.length, 1);
  }
  assert.equal((await request({ path: "/status", method: "GET" })).status, 200);
  assert.equal((await request({ path: "/health", method: "GET" })).status, 200);
  const preflight = await request({ method: "OPTIONS", headers: { origin: "https://attacker.example" } });
  assert.equal(preflight.status, 403);
  assert.deepEqual(preflight.calls, []);
});

test("oversized JSON is rejected before runtime effects", async () => {
  const result = await request({ body: JSON.stringify({ message: "x".repeat(1_000_001) }) });
  assert.equal(result.status, 413);
  assert.deepEqual(result.calls, []);
});
