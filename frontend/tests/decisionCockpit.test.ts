import assert from "node:assert/strict";
import test from "node:test";

// 决策舱前端契约测试：后端权威数据绝不经由前端提交。
// 验证「前端绝不提交候选池/持仓快照/信号/证据/actions/trade_date_override」的 API 形态：
//  generate 仅发送 trade_date + llm + force；watchlist 仅发送 codes。

test("generateTomorrowPlan body carries only trade_date/llm/force (no authoritative data)", async () => {
  let capturedBody: any = null;
  const origFetch = globalThis.fetch;
  globalThis.fetch = (async (_url: any, init: any) => {
    capturedBody = JSON.parse(init.body);
    return new Response(JSON.stringify({ data: { id: 1, skipped: false } }), { status: 200 });
  }) as any;
  try {
    const { generateTomorrowPlan } = await import("../src/lib/decisionCockpit.ts");
    await generateTomorrowPlan(
      "2026-07-24",
      { provider: "cli-openai", baseURL: "", apiKey: "", model: "x" },
      false,
    );
    assert.equal(capturedBody.trade_date, "2026-07-24");
    assert.equal(capturedBody.force, false);
    assert.equal(capturedBody.llm.model, "x");
    // 绝不提交权威数据字段
    assert.equal(capturedBody.candidates, undefined);
    assert.equal(capturedBody.signals, undefined);
    assert.equal(capturedBody.portfolio_snapshot, undefined);
    assert.equal(capturedBody.account_funding_snapshot, undefined);
    assert.equal(capturedBody.actions, undefined);
    assert.equal(capturedBody.trade_date_override, undefined);
  } finally {
    globalThis.fetch = origFetch;
  }
});

test("force regenerate sets force=true", async () => {
  let capturedBody: any = null;
  const origFetch = globalThis.fetch;
  globalThis.fetch = (async (_url: any, init: any) => {
    capturedBody = JSON.parse(init.body);
    return new Response(JSON.stringify({ data: { id: 2, skipped: false } }), { status: 200 });
  }) as any;
  try {
    const { generateTomorrowPlan } = await import("../src/lib/decisionCockpit.ts");
    await generateTomorrowPlan("2026-07-24", null, true);
    assert.equal(capturedBody.force, true);
    assert.equal(capturedBody.llm, null);
  } finally {
    globalThis.fetch = origFetch;
  }
});

test("freezePlan posts expected_version only", async () => {
  let capturedBody: any = null;
  let capturedPath = "";
  const origFetch = globalThis.fetch;
  globalThis.fetch = (async (url: any, init: any) => {
    capturedPath = String(url);
    capturedBody = JSON.parse(init.body);
    return new Response(JSON.stringify({ data: { id: 5, status: "frozen" } }), { status: 200 });
  }) as any;
  try {
    const { freezePlan } = await import("../src/lib/decisionCockpit.ts");
    await freezePlan(5, 3);
    assert.match(capturedPath, /\/api\/decision-cockpit\/tomorrow-plan\/5\/freeze/);
    assert.equal(capturedBody.expected_version, 3);
  } finally {
    globalThis.fetch = origFetch;
  }
});

test("importLocalWatchlist sends only codes (no etag when none)", async () => {
  let capturedBody: any = null;
  const origFetch = globalThis.fetch;
  globalThis.fetch = (async (_url: any, init: any) => {
    capturedBody = JSON.parse(init.body);
    return new Response(JSON.stringify({ data: { codes: ["600519"], added: [], updated_at: "x", etag: "y" } }), { status: 200 });
  }) as any;
  try {
    const { importLocalWatchlist } = await import("../src/lib/decisionCockpit.ts");
    await importLocalWatchlist(["600519"]);
    assert.deepEqual(capturedBody.codes, ["600519"]);
    assert.equal(capturedBody.expected_etag, undefined);
  } finally {
    globalThis.fetch = origFetch;
  }
});
