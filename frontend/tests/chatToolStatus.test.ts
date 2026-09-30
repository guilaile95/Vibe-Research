import assert from "node:assert/strict";
import test from "node:test";
import { applyNdjsonLine, createNdjsonProtocolState } from "../src/lib/api.ts";
import { applyChatToolResult, chatToolStatusLabel, parseStoredChatTools, type ChatToolUse } from "../src/lib/chatToolStatus.ts";

test("tool attempt stays pending until its own validated result arrives", () => {
  const state = createNdjsonProtocolState();
  let tools: ChatToolUse[] = [];
  const handlers = {
    onTool: (name: string, _args: Record<string, unknown>, callId?: string) => {
      tools.push({ name, arg: "", callId, status: "pending", truncated: false });
    },
    onToolResult: (result: Parameters<typeof applyChatToolResult>[1]) => { tools = applyChatToolResult(tools, result); },
  };
  for (const callId of ["one", "two"]) applyNdjsonLine(state,
    JSON.stringify({ type: "tool", tool: "query_quote", args: {}, call_id: callId }), handlers);
  assert.equal(chatToolStatusLabel(tools[0], true), "请求中");
  assert.equal(chatToolStatusLabel(tools[0], false), "未确认完成");
  applyNdjsonLine(state, JSON.stringify({ type: "tool_result", tool: "query_quote", call_id: "two", status: "empty", truncated: false }), handlers);
  assert.equal(tools[0].status, "pending");
  assert.equal(chatToolStatusLabel(tools[1], false), "无返回数据");
  applyNdjsonLine(state, JSON.stringify({ type: "tool_result", tool: "query_quote", call_id: "one", status: "partial", truncated: true }), handlers);
  assert.equal(chatToolStatusLabel(tools[0], false), "返回受限 · 部分结果");
  assert.equal(state.sawError, false);
});

test("legacy and interrupted tools never hydrate as successful lookups", () => {
  const tools = parseStoredChatTools([
    { name: "query_news", arg: "600519" },
    { name: "query_quote", arg: "600519", status: "pending" },
    { name: "query_kline", arg: "600519", status: "error", truncated: false },
    { name: "query_quote", arg: "600519", status: "success", truncated: true },
    null, { name: 5, arg: "" },
  ]);
  assert.equal(tools.length, 4);
  assert.deepEqual(tools.map((tool) => chatToolStatusLabel(tool, false)),
    ["结果未知", "结果未知", "获取失败", "已返回 · 部分结果"]);
  assert.deepEqual(parseStoredChatTools(JSON.parse(JSON.stringify(tools))), tools);
});

test("tool result parser rejects malformed or late outcomes and ignores mismatched IDs", () => {
  const valid = { type: "tool_result", call_id: "one", tool: "query_quote", status: "success", truncated: false };
  for (const payload of [{ ...valid, status: "made-up" }, { ...valid, truncated: "false" }, { ...valid, call_id: "" }]) {
    const state = createNdjsonProtocolState();
    applyNdjsonLine(state, JSON.stringify(payload), { onToolResult: () => assert.fail("must reject malformed result") });
    assert.equal(state.sawError, true);
  }
  const state = createNdjsonProtocolState();
  applyNdjsonLine(state, JSON.stringify({ type: "done" }));
  applyNdjsonLine(state, JSON.stringify(valid), { onToolResult: () => assert.fail("must reject late result") });
  assert.equal(state.sawError, true);
  const tools: ChatToolUse[] = [{ name: "query_quote", callId: "different", arg: "", status: "pending", truncated: false }];
  assert.deepEqual(applyChatToolResult(tools, { ...valid, status: "success" }), tools);
});
