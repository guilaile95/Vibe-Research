import assert from "node:assert/strict";
import test from "node:test";

/**
 * 板块研究 API 客户端：路径构造（禁止双 /api）与 import body 仅 external_id。
 * 风格对齐 myReportsApi.test.ts。
 */

// 拦截 fetch，记录最终请求路径与 body。
const requests: { url: string; method?: string; body?: string | null }[] = [];
const realFetch = globalThis.fetch;
globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  requests.push({
    url,
    method: init?.method,
    body: typeof init?.body === "string" ? init.body : init?.body != null ? String(init.body) : null,
  });
  if (url.startsWith("/api/sector-research/")) {
    const body = JSON.stringify({
      data: {
        sector_key: "pcb",
        discovered: [],
        filtered: [],
        error: null,
        status: "normal",
        warnings: [],
        companies: [],
        source: "a-stock-data",
        fetched_at: "2025-01-01T00:00:00Z",
        id: "r1",
        name: "x.pdf",
        industry: "PCB",
        size: 1,
        ext: "pdf",
        ts: 0,
      },
    });
    return new Response(body, { status: 200, headers: { "Content-Type": "application/json" } });
  }
  return realFetch(input, init);
}) as unknown as typeof fetch;

function discoverPath(
  sectorKey: string,
  opts?: { days?: number; maxPages?: number; scope?: string },
): string {
  const q = new URLSearchParams();
  if (opts?.days != null) q.set("days", String(opts.days));
  if (opts?.maxPages != null) q.set("max_pages", String(opts.maxPages));
  if (opts?.scope) q.set("scope", opts.scope);
  const qs = q.toString();
  return `/sector-research/reports/${encodeURIComponent(sectorKey)}${qs ? `?${qs}` : ""}`;
}

function importPath(sectorKey: string): string {
  return `/sector-research/import/${encodeURIComponent(sectorKey)}`;
}

function dataPath(sectorKey: string): string {
  return `/sector-research/data/${encodeURIComponent(sectorKey)}`;
}

function marketContextPath(sectorKey?: string): string {
  return `/sector-research/market-context${sectorKey ? `?sector_key=${encodeURIComponent(sectorKey)}` : ""}`;
}

/** 与 api.importSectorReport 一致：body 仅 external_id */
function buildImportBody(externalId: string): Record<string, unknown> {
  return { external_id: externalId };
}

test("discoverSectorReports path has exactly one /api prefix (no /api/api)", () => {
  const path = discoverPath("pcb", { days: 365, maxPages: 3, scope: "industry" });
  assert.ok(path.startsWith("/sector-research/"));
  assert.ok(!path.startsWith("/api/"));
  const full = `/api${path}`;
  assert.ok(full.startsWith("/api/sector-research/"));
  assert.ok(!full.startsWith("/api/api"), "must not double the /api prefix");
  assert.ok(full.includes("days=365"));
  assert.ok(full.includes("max_pages=3"));
  assert.ok(full.includes("scope=industry"));
});

test("importSectorReport path has exactly one /api prefix", () => {
  const path = importPath("pcb");
  assert.ok(path.startsWith("/sector-research/import/"));
  const full = `/api${path}`;
  assert.ok(full.startsWith("/api/sector-research/import/"));
  assert.ok(!full.startsWith("/api/api"));
});

test("getSectorResearchData path has exactly one /api prefix", () => {
  const path = dataPath("pcb");
  assert.ok(path.startsWith("/sector-research/data/"));
  const full = `/api${path}`;
  assert.ok(full.startsWith("/api/sector-research/data/"));
  assert.ok(!full.startsWith("/api/api"));
});

test("sector market context uses one endpoint for overview and mapped detail", () => {
  assert.equal(`/api${marketContextPath()}`, "/api/sector-research/market-context");
  assert.equal(`/api${marketContextPath("solid-state-battery")}`, "/api/sector-research/market-context?sector_key=solid-state-battery");
  assert.ok(!`/api${marketContextPath("pcb")}`.startsWith("/api/api"));
});

test("importSectorReport body contains only external_id", () => {
  const body = buildImportBody("INFO99");
  assert.deepEqual(body, { external_id: "INFO99" });
  assert.equal(Object.keys(body).length, 1);
  assert.ok(!("info_code" in body));
  assert.ok(!("pdf_url" in body));
  assert.ok(!("title" in body));
});

test("discoverSectorReports issues a fetch to the correct URL", async () => {
  requests.length = 0;
  await globalThis.fetch(`/api${discoverPath("pcb", { scope: "all", days: 90 })}`, { method: "GET" });
  assert.equal(requests.length, 1);
  assert.ok(requests[0].url.includes("/sector-research/reports/pcb"));
  assert.ok(requests[0].url.includes("scope=all"));
  assert.ok(!requests[0].url.startsWith("/api/api"));
});

test("importSectorReport issues POST with external_id-only body", async () => {
  requests.length = 0;
  const body = buildImportBody("AP202501010001");
  await globalThis.fetch(`/api${importPath("pcb")}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].method, "POST");
  assert.ok(requests[0].url.includes("/sector-research/import/pcb"));
  assert.ok(!requests[0].url.startsWith("/api/api"));
  const parsed = JSON.parse(requests[0].body || "{}");
  assert.deepEqual(parsed, { external_id: "AP202501010001" });
});
