import assert from "node:assert/strict";
import test from "node:test";
import { applyNdjsonLine, createNdjsonProtocolState, streamNdjson } from "../src/lib/api.ts";
import { parseLeadAnalysisContext, type LeadAnalysisContext } from "../src/lib/leadAnalysisContext.ts";

const context: LeadAnalysisContext = {
  schema_version: "daily-review-lead-context.v1", kind: "activity",
  subject: { code: "600519", name: "贵州茅台" }, source_path: "capital_activity.amount_top[0]",
  source: { status: "normal", source: "fixture", trade_date: null, data_time: null, fetched_at: "2026-09-25 16:00:00", is_stale: null },
  review_generated_at: "2026-09-25 16:01:00", cache_stale: true,
  facts: { amount: 0, change_pct: null }, unknowns: ["源时间未知"],
};

test("lead provenance passes through the stream without replacing missing source time or zero values", () => {
  const state = createNdjsonProtocolState(); let received: LeadAnalysisContext | undefined;
  applyNdjsonLine(state, JSON.stringify({ type: "lead_context", context }), { onLeadContext: (value) => { received = value; } });
  applyNdjsonLine(state, JSON.stringify({ type: "delta", text: "线索草稿" }));
  applyNdjsonLine(state, JSON.stringify({ type: "done" }));
  assert.deepEqual(received, context);
  assert.equal(received?.source.data_time, null);
  assert.equal(received?.facts.amount, 0);
  assert.equal(state.sawDone, true);
  assert.equal(state.sawError, false);
});

test("malformed and late provenance cannot complete as a successful valid source", () => {
  for (const value of [null, {}, { ...context, source: {} }, { ...context, unknowns: [4] }, { ...context, facts: { amount: {} } }]) {
    const state = createNdjsonProtocolState(); let called = false;
    applyNdjsonLine(state, JSON.stringify({ type: "lead_context", context: value }), { onLeadContext: () => { called = true; } });
    assert.equal(state.sawError, true);
    assert.equal(called, false);
  }
  assert.equal(parseLeadAnalysisContext({ ...context, facts: { amount: Infinity } }), undefined);
  const state = createNdjsonProtocolState();
  applyNdjsonLine(state, JSON.stringify({ type: "done" }));
  applyNdjsonLine(state, JSON.stringify({ type: "lead_context", context }));
  assert.equal(state.sawError, true);
});

test("lead context coexists with call IDs, partial tool outcomes and done metadata", () => {
  const state = createNdjsonProtocolState();
  const calls: string[] = [];
  const outcomes: string[] = [];
  const metadata = {
    result_type: "daily_review_ai", trade_date: "2026-09-25",
    schema_version: "daily_review_ai.v1", generated_at: "2026-09-25 16:02:00",
  };
  const events = [
    { type: "lead_context", context },
    { type: "tool", tool: "query_quote", args: { code: "600519" }, call_id: "quote-1" },
    { type: "tool_result", tool: "query_quote", call_id: "quote-1", status: "partial", truncated: true },
    { type: "delta", text: "待核验草稿" },
    { type: "done", trace: [{ tool: "query_quote", args: { code: "600519" } }], rounds: 1, result: metadata },
  ];
  for (const event of events) applyNdjsonLine(state, JSON.stringify(event), {
    onTool: (_tool, _args, callId) => { calls.push(callId || ""); },
    onToolResult: (result) => { outcomes.push(`${result.call_id}:${result.status}:${result.truncated}`); },
  });
  assert.deepEqual(calls, ["quote-1"]);
  assert.deepEqual(outcomes, ["quote-1:partial:true"]);
  assert.equal(state.content, "待核验草稿");
  assert.equal(state.rounds, 1);
  assert.deepEqual(state.result, metadata);
  assert.equal(state.sawDone, true);
  assert.equal(state.sawError, false);
});

test("lead streams preserve partial text but reject truncation, error and malformed context", async (t) => {
  const encode = (events: unknown[]) => events.map((event) => JSON.stringify(event)).join("\n") + "\n";
  for (const [name, events, expected] of [
    ["truncated", [{ type: "lead_context", context }, { type: "delta", text: "保留片段" }], /未返回完成信号/],
    ["error", [{ type: "lead_context", context }, { type: "delta", text: "保留片段" }, { type: "error", message: "测试读取失败" }, { type: "done" }], /测试读取失败/],
    ["malformed", [{ type: "lead_context", context: {} }, { type: "done" }], /线索分析来源格式错误/],
  ] as const) {
    await t.test(name, async () => {
      const original = globalThis.fetch;
      let partial = "";
      globalThis.fetch = async () => new Response(encode([...events]), { headers: { "Content-Type": "application/x-ndjson" } });
      try {
        await assert.rejects(streamNdjson("/daily-review/lead-analysis", {}, {
          onDelta: (value) => { partial += value; },
        }), expected);
        assert.equal(partial, name === "malformed" ? "" : "保留片段");
      } finally { globalThis.fetch = original; }
    });
  }
});

test("lead stream forwards cancellation without reporting completion", async () => {
  const original = globalThis.fetch;
  const controller = new AbortController();
  let capturedSignal: AbortSignal | null | undefined;
  globalThis.fetch = async (_input, init) => {
    capturedSignal = init?.signal;
    throw new DOMException("Aborted", "AbortError");
  };
  controller.abort();
  try {
    await assert.rejects(streamNdjson("/daily-review/lead-analysis", {}, {}, controller.signal), { name: "AbortError" });
    assert.equal(capturedSignal, controller.signal);
  } finally { globalThis.fetch = original; }
});
