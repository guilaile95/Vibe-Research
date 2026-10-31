import { installCredentialFixture, withCredentialStatus } from './credentialTransportFixture.mjs';
import assert from "node:assert/strict";
import test from "node:test";

/**
 * 每日复盘：初始 GET vs 显式刷新 POST 契约。
 * 模拟 fetch 记录方法；不挂载 React。
 */

test("api.dailyReview uses GET /api/daily-review", async () => {
  const calls: Array<{ url: string; method: string }> = [];
  const orig = globalThis.fetch;
  globalThis.fetch = (async (url: any, init?: any) => {
    calls.push({ url: String(url), method: (init?.method || "GET").toUpperCase() });
    return new Response(
      JSON.stringify({
        data: { generated_at: "2026-07-24 10:00:00", status: "normal" },
        cache_meta: { stale: false, source: "memory" },
      }),
      { status: 200 },
    );
  }) as any;
  try {
    const { api } = await import("../src/lib/api.ts");
    const res = await api.dailyReview();
    assert.equal(res.data.generated_at, "2026-07-24 10:00:00");
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/daily-review$/);
    assert.equal(calls[0].method, "GET");
  } finally {
    globalThis.fetch = orig;
  }
});

test("api.dailyReviewRefresh uses POST /api/daily-review/refresh", async () => {
  const calls: Array<{ url: string; method: string }> = [];
  const orig = globalThis.fetch;
  globalThis.fetch = (async (url: any, init?: any) => {
    calls.push({ url: String(url), method: (init?.method || "GET").toUpperCase() });
    return new Response(
      JSON.stringify({
        data: { generated_at: "2026-07-24 11:00:00", status: "normal" },
        cache_meta: { stale: false, source: "refresh" },
      }),
      { status: 200 },
    );
  }) as any;
  try {
    // re-import may be cached; call through dynamic import of module already loaded
    const mod = await import("../src/lib/api.ts");
    const res = await mod.api.dailyReviewRefresh();
    assert.equal(res.data.generated_at, "2026-07-24 11:00:00");
    assert.equal(res.cache_meta?.source, "refresh");
    const post = calls.find((c) => c.method === "POST");
    assert.ok(post, "expected POST");
    assert.match(post!.url, /\/api\/daily-review\/refresh/);
  } finally {
    globalThis.fetch = orig;
  }
});

test("portfolioAdvice body only user_request + llm", async t => {
  const llm = { provider: "cli-codex", baseURL: "", apiKey: "", model: "codex", revision: "1" };
  installCredentialFixture(t, llm);
  let body: any = null;
  const orig = globalThis.fetch;
  globalThis.fetch = withCredentialStatus(async (_url: any, init?: any) => {
    body = JSON.parse(init?.body || "{}");
    return new Response(JSON.stringify({ data: { schema_version: "portfolio-advice-v0.1" } }), {
      status: 200,
    });
  }) as any;
  try {
    const { api } = await import("../src/lib/api.ts");
    await api.portfolioAdvice({
      user_request: null,
      llm,
    });
    assert.deepEqual(Object.keys(body).sort(), ["llm", "user_request"]);
    assert.equal(body.user_request, null);
    assert.equal(body.llm.provider, "cli-codex");
    assert.equal(Object.hasOwn(body.llm, "revision"), true);
    assert.equal(body.holdings, undefined);
    assert.equal(body.context, undefined);
    assert.equal(body.messages, undefined);
  } finally {
    globalThis.fetch = orig;
  }
});

test("failed refresh preserves string error and exposes structured latest attempt", async () => {
  const orig = globalThis.fetch;
  const attempt = { state: "failed", started_at: "2026-10-31 14:00:00", finished_at: "2026-10-31 14:03:30", reason_code: "SOURCE_TIMEOUT", failed_sources: [], pending_sources: ["breadth"] };
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "关键市场数据暂不可用，本次刷新未完成", refresh_attempt: attempt }), { status: 503 })) as any;
  try {
    const { api, ApiError } = await import("../src/lib/api.ts");
    await assert.rejects(api.dailyReviewRefresh(), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 503);
      assert.match(error.message, /关键市场数据/);
      assert.deepEqual(error.refreshAttempt, attempt);
      return true;
    });
  } finally { globalThis.fetch = orig; }
});
