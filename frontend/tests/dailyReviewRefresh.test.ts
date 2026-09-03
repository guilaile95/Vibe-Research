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

test("portfolioAdvice body only user_request + llm", async () => {
  let body: any = null;
  const orig = globalThis.fetch;
  globalThis.fetch = (async (_url: any, init?: any) => {
    body = JSON.parse(init?.body || "{}");
    return new Response(JSON.stringify({ data: { schema_version: "portfolio-advice-v0.1" } }), {
      status: 200,
    });
  }) as any;
  try {
    const { api } = await import("../src/lib/api.ts");
    await api.portfolioAdvice({
      user_request: null,
      llm: { provider: "cli-codex", baseURL: "", apiKey: "", model: "codex" },
    });
    assert.deepEqual(Object.keys(body).sort(), ["llm", "user_request"]);
    assert.equal(body.user_request, null);
    assert.equal(body.llm.provider, "cli-codex");
    assert.equal(body.holdings, undefined);
    assert.equal(body.context, undefined);
    assert.equal(body.messages, undefined);
  } finally {
    globalThis.fetch = orig;
  }
});
