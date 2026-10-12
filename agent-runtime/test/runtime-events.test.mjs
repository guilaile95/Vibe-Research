import assert from "node:assert/strict";
import crypto from "node:crypto";
import test from "node:test";

import { AgentRuntime, RuntimeError } from "../src/runtime.mjs";

const MESSAGE = { type: "item.completed", item: { id: "answer", type: "agent_message", text: "draft" } };
const COMPLETED = { type: "turn.completed", usage: {} };
const PHASES = ["item.started", "item.updated", "item.completed"];

// Exercise the actual chat loop with an already-created synthetic session.
// Do not construct AgentRuntime: construction/session creation and status probing
// may access local configuration or invoke the bundled CLI, even with a fake SDK.
function fixture(stream) {
  const runtime = Object.create(AgentRuntime.prototype);
  runtime.status = () => ({ installed: true, authenticated: true });
  const observed = { consumed: 0, closed: false, signal: null, output: [] };
  const current = {
    turns: 0,
    controller: null,
    transcriptDigest: crypto.createHash("sha256").update("[]").digest("hex"),
    thread: {
      async runStreamed(_prompt, { signal }) {
        observed.signal = signal;
        return { events: (async function* () {
          try {
            for (const event of stream) {
              observed.consumed += 1;
              yield event;
            }
          } finally {
            observed.closed = true;
          }
        })() };
      },
    },
  };
  runtime.sessions = new Map([["synthetic", current]]);
  const run = () => runtime.chat({
    session: "synthetic", message: "question", context: "synthetic page",
    onEvent: (event) => observed.output.push(event),
  });
  return { runtime, current, observed, run };
}

async function rejectsItem(event, prefix = []) {
  const f = fixture([...prefix, event, MESSAGE, COMPLETED]);
  const digestBefore = f.current.transcriptDigest;
  await assert.rejects(f.run(), (error) => {
    assert.ok(error instanceof RuntimeError);
    assert.equal(error.code, "TOOL_SURFACE_VIOLATION");
    assert.equal(error.status, 503);
    assert.doesNotMatch(error.message, /PRIVATE_SENTINEL/);
    return true;
  });
  assert.equal(f.observed.consumed, prefix.length + 1, "stop at the first disallowed item");
  assert.equal(f.observed.signal.aborted, true);
  assert.equal(f.observed.closed, true, "close the SDK iterator on rejection");
  assert.equal(f.runtime.sessions.has("synthetic"), false);
  assert.equal(f.current.turns, 0);
  assert.equal(f.current.transcriptDigest, digestBefore);
  assert.equal(f.current.controller, null);
  assert.equal(f.observed.output.some((event) => event.type === "done"), false);
  return f;
}

for (const phase of PHASES) {
  for (const kind of ["command_execution", "file_change", "mcp_tool_call", "web_search", "image_view", "collab_tool_call", "future_PRIVATE_SENTINEL_action"]) {
    test(`${phase} rejects ${kind} without waiting for completion`, async () => {
      for (const status of [undefined, "in_progress", "completed", "failed"]) {
        const f = await rejectsItem({ type: phase, item: { type: kind, status, text: "PRIVATE_SENTINEL" } });
        assert.deepEqual(f.observed.output, []);
      }
    });
  }
  test(`${phase} rejects malformed and missing item kinds`, async () => {
    for (const item of [undefined, null, [], "PRIVATE_SENTINEL", {}, { type: "" }, { type: null }, { type: 1 }]) {
      await rejectsItem({ type: phase, item });
    }
  });
}

test("legitimate lifecycle items and usage remain compatible; only completed messages emit text", async () => {
  const stream = [{ type: "thread.started", thread_id: "fake" }, { type: "turn.started" }];
  for (const kind of ["reasoning", "todo_list", "error"]) {
    for (const phase of PHASES) stream.push({ type: phase, item: { id: kind, type: kind, text: "PRIVATE_SENTINEL", message: "nonfatal PRIVATE_SENTINEL", items: [] } });
  }
  stream.push(
    { type: "item.started", item: { type: "agent_message", text: "partial" } },
    { type: "item.updated", item: { type: "agent_message", text: "partial update" } },
    MESSAGE,
    { type: "item.completed", item: { type: "agent_message", text: " second" } },
    { ...COMPLETED, usage: { input_tokens: 10, output_tokens: 4, reasoning_output_tokens: 2, future_counter: 1 } },
  );
  const f = fixture(stream);
  assert.equal(await f.run(), "draft second");
  assert.deepEqual(f.observed.output.map((event) => event.type), ["delta", "delta", "done"]);
  assert.deepEqual(f.observed.output.filter((event) => event.type === "delta").map((event) => event.text), ["draft", " second"]);
  assert.equal(f.observed.signal.aborted, false);
  assert.equal(f.current.turns, 1);
  assert.equal(f.runtime.sessions.has("synthetic"), true);
});

test("a violation after visible draft or turn completion still cannot commit success", async () => {
  for (const prefix of [[MESSAGE], [MESSAGE, COMPLETED]]) {
    const f = await rejectsItem({ type: "item.started", item: { type: "mcp_tool_call" } }, prefix);
    assert.deepEqual(f.observed.output.map((event) => event.type), ["delta"]);
  }
});

for (const [name, stream, expected] of [
  ["fatal stream error", [MESSAGE, { type: "error", message: "PRIVATE_SENTINEL" }], "CHAT_FAILED"],
  ["failed turn", [MESSAGE, { type: "turn.failed", error: { message: "PRIVATE_SENTINEL" } }], "CHAT_FAILED"],
  ["missing terminal event", [MESSAGE], "EMPTY_RESPONSE"],
  ["no answer", [COMPLETED], "EMPTY_RESPONSE"],
]) {
  test(`${name} remains unsuccessful`, async () => {
    const f = fixture(stream);
    await assert.rejects(f.run(), (error) => error.code === expected && !error.message.includes("PRIVATE_SENTINEL"));
    assert.equal(f.runtime.sessions.has("synthetic"), false);
    assert.equal(f.current.turns, 0);
    assert.equal(f.observed.output.some((event) => event.type === "done"), false);
  });
}
