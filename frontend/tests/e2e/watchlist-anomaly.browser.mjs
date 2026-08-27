import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = join(fileURLToPath(import.meta.url), "..");
const dist = join(here, "../../dist");

function chromiumPath() {
  const roots = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  const candidates = [];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    for (const item of readdirSync(base)) {
      if (!/^chromium(_headless_shell)?-\d+$/.test(item)) continue;
      candidates.push(
        join(base, item, "chrome-win64", "chrome.exe"),
        join(base, item, "chrome-win", "chrome.exe"),
        join(base, item, "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
      );
    }
  }
  return candidates.filter((candidate) => existsSync(candidate)).sort().at(-1);
}

async function freePort() {
  const server = createServer();
  const port = await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function staticServer(directory, port) {
  const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" };
  const server = createServer((request, response) => {
    let pathname = decodeURIComponent((request.url || "/").split("?")[0]);
    if (pathname === "/") pathname = "/index.html";
    let target = join(directory, pathname);
    if (!existsSync(target) || extname(target) === "") target = join(directory, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

let server;
let browser;
try {
  assert.ok(existsSync(join(dist, "index.html")), "dist/index.html missing; run npm run build");
  const port = await freePort();
  server = await staticServer(dist, port);
  browser = await chromium.launch({ headless: true, executablePath: chromiumPath() });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/trendradar/watchlist-context") {
      return route.fulfill({ json: { data: {
        status: "OK",
        retrieved_at: "2026-08-27T16:00:00Z",
        authority_ref: "vibe:trendradar_watchlist_context:v0.1",
        usage_boundary: "observation_only_not_an_investment_authority",
        upstream: {
          repo: "sansan0/TrendRadar", source_commit: "8ee26026ba6c11dec41a95fb3895a7162876caa1",
          core_version: "6.10.0", mcp_version: "4.1.0", license: "GPL-3.0",
          core_image: "wantcat/trendradar:6.10.0@sha256:qualified",
          mcp_image: "wantcat/trendradar-mcp:4.1.0@sha256:qualified",
          integration_authority_ref: "vibe:trendradar_gateway:v0.1",
          usage_boundary: "observation_only_not_an_investment_authority",
        },
        watchlist: { status: "valid", codes: ["600519", "000001", "837023"], count: 3 },
        items: [
          {
            status: "OK", security: { code: "600519", company_name: "贵州茅台" },
            mapping: { status: "MAPPED", sector: { value: "白酒", source: "fixture" }, topics: [], matched_terms: ["600519", "白酒"], reasons: [], errors: [] },
            observation: { window_days: 7, window_semantics: "TrendRadar search_news date_range relative window", item_count: 1, rank_history_semantics: "missing means UNKNOWN", items: [{ title: "白酒行业公开资讯", platform: "微博", url: "https://example.test/news", timestamp: "2026-08-27T09:00:00Z", rank: 2, off_list: false, hotness_score: null, first_seen: null, last_seen: null, crawl_count: null, rank_timeline: null, matched_terms: ["白酒"] }] },
            source_statuses: [],
          },
          {
            status: "OK", security: { code: "000001", company_name: "平安银行" },
            mapping: { status: "EXACT_CODE_ONLY", sector: null, topics: [], matched_terms: ["000001"], reasons: [], errors: [] },
            observation: { window_days: 7, window_semantics: "TrendRadar search_news date_range relative window", item_count: 0, rank_history_semantics: "missing means UNKNOWN", items: [] },
            source_statuses: [],
          },
          {
            status: "UNAVAILABLE", error: "TrendRadar 暂不可用", security: { code: "837023", company_name: null },
            mapping: { status: "EXACT_CODE_ONLY", sector: null, topics: [], matched_terms: ["837023"], reasons: [], errors: [] },
            observation: { window_days: 7, window_semantics: "TrendRadar search_news date_range relative window", item_count: 0, rank_history_semantics: "missing means UNKNOWN", items: [] },
            source_statuses: [],
          },
        ],
      } } });
    }
    if (path === "/api/watchlist/anomalies") {
      return route.fulfill({ json: { data: {
        provider_id: "hithink_financial_api",
        provider_contract: "hithink-watchlist-anomalies-v0.1",
        as_of_ms: 1787529600000,
        unavailable_codes: ["837023"],
        items: [{
          code: "600519", provider_symbol: "600519.SH", name: "贵州茅台",
          type: "大幅上涨", reason: "成交活跃且价格快速上行", keywords: ["白酒"],
        }, {
          code: "600519", provider_symbol: "600519.SH", name: "贵州茅台",
          type: "快速反弹", reason: "盘中价格快速回升", keywords: [],
        }],
      } } });
    }
    if (path === "/api/watchlist") {
      return route.fulfill({ json: { data: {
        status: "valid", data: { codes: ["600519", "000001", "837023"], updated_at: "2026-08-24 09:30:00" }, etag: "e2e",
      } } });
    }
    if (path === "/api/quote") {
      return route.fulfill({ json: { data: {
        "600519": { name: "贵州茅台", price: 1300, change_pct: 2.5, amount_wan: 20_000 },
        "000001": { name: "平安银行", price: 11, change_pct: -1, amount_wan: 30_000 },
      } } });
    }
    return route.fulfill({ status: 503, json: { detail: "offline e2e fixture" } });
  });

  await page.goto(`http://127.0.0.1:${port}/watchlist`, { waitUntil: "networkidle" });
  await page.getByTestId("trendradar-watchlist-context").waitFor();
  await page.getByText("1 条公开标题", { exact: true }).waitFor();
  await page.getByText("当前窗口真实空态", { exact: true }).waitFor();
  assert.equal(await page.locator('[data-watchlist-attention-code="600519"]').count(), 1);
  assert.equal(await page.getByText("买卖建议", { exact: false }).count(), 1);
  await page.getByText("成交活跃且价格快速上行", { exact: true }).waitFor();
  await page.getByText("盘中价格快速回升", { exact: true }).waitFor();
  assert.equal(await page.getByText("当前数据源未返回异动记录", { exact: true }).count(), 1);
  assert.equal(await page.getByText("当前数据源未覆盖该标的异动查询", { exact: true }).count(), 1);
  await page.getByLabel("仅看有异动").check();
  assert.equal(await page.locator("tbody tr").count(), 1);
  await page.getByRole("link", { name: "600519", exact: true }).click();
  await page.waitForURL("**/stock-data?code=600519");
  await page.locator('[data-active-code="600519"]').waitFor();
  assert.deepEqual(pageErrors, []);
  console.log("watchlist anomaly browser vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
