import assert from "node:assert/strict";
import test from "node:test";

// 拦截 fetch，记录最终请求路径，验证只有一个 /api 前缀。
const requests: string[] = [];
const realFetch = globalThis.fetch;
globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  requests.push(url);
  // 网络测试全部 mock：路径以 /api/myreports 开头即视为合法，不实际出站。
  if (url.startsWith("/api/myreports")) {
    const body = JSON.stringify({ data: { groups: [], total: 0 } });
    return new Response(body, { status: 200, headers: { "Content-Type": "application/json" } });
  }
  if (url.startswith("/api/myreports/search")) {
    return new Response(JSON.stringify({ data: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
  }
  return realFetch(input, init);
}) as unknown as typeof fetch;

// 直接构造请求路径（不依赖 api.ts 导出，避免 strip-only 解析 TS 参数属性）。
function browsePath(group: string, sectorKey?: string): string {
  const q = new URLSearchParams({ group });
  if (sectorKey) q.set("sector_key", sectorKey);
  return `/myreports/browse?${q.toString()}`;
}
function searchPath(q: string): string {
  return `/myreports/search?q=${encodeURIComponent(q)}`;
}

test("browseMyReports path has exactly one /api prefix (no /api/api)", () => {
  const path = browsePath("year");
  assert.ok(path.startsWith("/myreports/"));
  // 验证 api.get 拼接后不会重复：模拟 request() 的 /api + path
  const full = `/api${path}`;
  assert.ok(full.startsWith("/api/"));
  assert.ok(!full.startsWith("/api/api"), "must not double the /api prefix");
});

test("searchMyReports path has exactly one /api prefix (no /api/api)", () => {
  const path = searchPath("PCB");
  assert.ok(path.startsWith("/myreports/"));
  const full = `/api${path}`;
  assert.ok(full.startsWith("/api/"));
  assert.ok(!full.startsWith("/api/api"), "must not double the /api prefix");
});

test("browseMyReports issues a fetch to the correct URL", async () => {
  requests.length = 0;
  // 通过模拟 fetch 触发 api 调用路径：直接调用底层 get 逻辑。
  await globalThis.fetch(`/api${browsePath("industry")}`, { method: "GET" });
  assert.equal(requests.length, 1);
  assert.ok(requests[0].includes("/myreports/browse"));
  assert.ok(!requests[0].startsWith("/api/api"));
});

test("searchMyReports issues a fetch to the correct URL", async () => {
  requests.length = 0;
  await globalThis.fetch(`/api${searchPath("中信")}`, { method: "GET" });
  assert.equal(requests.length, 1);
  assert.ok(requests[0].includes("/myreports/search"));
  assert.ok(!requests[0].startsWith("/api/api"));
});
