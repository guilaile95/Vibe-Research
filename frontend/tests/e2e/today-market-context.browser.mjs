/** Today market context: layout, unified intel, and two-source failure isolation. */
import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const frontendDist = join(root, "frontend", "dist");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const freePort = () => new Promise((resolve, reject) => {
  const server = createServer();
  server.on("error", reject);
  server.listen(0, "127.0.0.1", () => {
    const address = server.address();
    server.close(() => resolve(address.port));
  });
});

function staticServer(directory, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let target = join(directory, (request.url || "/").split("?")[0] === "/" ? "index.html" : (request.url || "/").split("?")[0]);
    if (!existsSync(target)) target = join(directory, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

function chromiumPath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH && existsSync(process.env.PLAYWRIGHT_CHROMIUM_PATH)) return process.env.PLAYWRIGHT_CHROMIUM_PATH;
  for (const base of [join(process.env.LOCALAPPDATA || "", "ms-playwright"), join(process.env.HOME || "", ".cache", "ms-playwright")]) {
    if (!existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      for (const candidate of [join(base, entry, "chrome-win64", "chrome.exe"), join(base, entry, "chrome-linux", "chrome")]) {
        if (existsSync(candidate)) return candidate;
      }
    }
  }
  return undefined;
}

async function launchBrowser() {
  const executablePath = chromiumPath();
  try {
    return await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  } catch {
    return chromium.launch({ headless: true, channel: "chrome" });
  }
}

const now = "2026-08-29T03:00:00Z";
const radar = {
  generated_at: now,
  recent_days: 7,
  stats: { total_sources: 12, failed_sources: 0, industries: 12 },
  industries: [{
    key: "ai",
    name: "AI 人工智能",
    accent: "#f97316",
    items: [{
      title: "RADAR_NEWS_MUST_NOT_RENDER",
      zh: "赛道原始新闻不应显示",
      source: "Radar Source",
      time: "08-29 10:00",
      published_at: now,
      url: "https://example.test/radar",
    }],
  }],
};
const nativeRuntime = {
  status: "normal",
  generated_at: now,
  store: { readable: true, schema_version: "native-intel-v0.1", item_count: 1 },
  last_run: { run_id: "today-e2e", status: "ok", started_at: now, finished_at: now, source_ok: 2, source_failed: 0, item_seen: 1, item_new: 1 },
  sources: { total: 2, healthy: 2, failing: 0, never_run: 0, failing_names: [] },
};
const nativeItem = {
  item_id: 1,
  title: "半导体产业链出现重要进展",
  url: "https://example.test/native",
  source_id: "official",
  source_name: "公开来源",
  hint: "a-share",
  published_at: now,
  first_seen_at: now,
  last_seen_at: now,
  observation_count: 2,
};
const nativeItems = { status: "normal", items: [nativeItem], total: 1, limit: 40, offset: 0 };
const nativeTrending = {
  status: "normal",
  generated_at: now,
  window_hours: 24,
  item_count: 1,
  items: [nativeItem],
  entities: [{ term: "半导体", term_kind: "concept", security_code: null, item_count: 1, source_count: 2, previous_item_count: 0, delta: 1 }],
};

const marketCloud = (scope) => ({
  status: "normal",
  warnings: [],
  is_stale: false,
  fetched_at: now,
  data: {
    scope,
    period: "today",
    stock_count: 1,
    valid_count: 1,
    industry_count: 1,
    no_industry_count: 0,
    industries: [{
      name: "白酒",
      stock_count: 1,
      total_float_cap: 1_000_000_000,
      avg_change_pct: 1.2,
      up_count: 1,
      down_count: 0,
      stocks: [{
        code: "600519",
        name: "贵州茅台",
        price: 1500,
        change_pct: 1.2,
        amount: 100_000_000,
        float_market_cap: 1_000_000_000,
        turnover_pct: 0.8,
        industry: "白酒",
      }],
    }],
  },
});

let scenario = "normal";
let nativeRefreshCalls = 0;
let radarRefreshCalls = 0;
const requestedScopes = [];

async function handleApi(route) {
  const request = route.request();
  const url = new URL(request.url());
  const pathName = url.pathname;

  if (pathName === "/api/market/cloud") {
    const scope = url.searchParams.get("scope") || "all";
    requestedScopes.push(scope);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: marketCloud(scope) }) });
  }
  if (pathName === "/api/native-intel/status") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(nativeRuntime) });
  if (pathName === "/api/native-intel/items") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(nativeItems) });
  if (pathName === "/api/native-intel/trending") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(nativeTrending) });
  if (pathName === "/api/native-intel/refresh") {
    nativeRefreshCalls += 1;
    if (scenario === "native-fail") return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "native refresh failed" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ accepted: true, status: "normal" }) });
  }
  if (pathName === "/api/radar" && request.method() === "GET") {
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(radar) });
  }
  if (pathName === "/api/radar/refresh") {
    radarRefreshCalls += 1;
    if (scenario === "radar-fail") return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "radar refresh failed" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(radar) });
  }
  if (pathName === "/api/daily-review") {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: { schema_version: "daily-review-v0.1", status: "partial", trade_date: "2026-08-29", generated_at: now, data_cutoff: now, warnings: [] } }),
    });
  }
  if (pathName === "/api/daily-review/history") {
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], count: 0, limit: 20, offset: 0 }) });
  }
  if (pathName === "/api/watchlist") {
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ codes: [], etag: "today-e2e" }) });
  }
  if (pathName === "/api/intel-digests/latest") {
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ digest: null }) });
  }
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "unavailable", data: null, warnings: [] }) });
}

let server;
let browser;
try {
  assert.ok(existsSync(join(frontendDist, "index.html")), "frontend must be built first");
  const port = await freePort();
  server = await staticServer(frontendDist, port);
  browser = await launchBrowser();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/**", handleApi);

  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const marketPanel = page.getByTestId("market-intel-panel");
  await marketPanel.waitFor({ state: "visible", timeout: 15000 });
  const chart = page.locator("[data-market-cloud-chart]");
  await chart.waitFor({ state: "visible", timeout: 15000 });

  const chartBox = await chart.boundingBox();
  assert.ok(chartBox && chartBox.width > 1400, `expected wide market cloud, got ${chartBox?.width}`);
  assert.ok(chartBox && chartBox.height >= 620, `expected tall market cloud, got ${chartBox?.height}`);

  const order = await page.evaluate(() => ({
    market: document.querySelector("[data-market-cloud]")?.getBoundingClientRect().top,
    intel: document.querySelector('[data-testid="market-intel-panel"]')?.getBoundingClientRect().top,
    review: document.querySelector("#daily-review-section-title")?.getBoundingClientRect().top,
  }));
  assert.ok(order.market < order.intel && order.intel < order.review, `unexpected Today order: ${JSON.stringify(order)}`);
  assert.equal(await page.getByRole("heading", { name: "市场情报", exact: true }).count(), 1);
  assert.equal(await page.getByText("Investment News", { exact: true }).count(), 0);
  assert.equal(await page.getByText("关注雷达", { exact: true }).count(), 0);
  await marketPanel.getByText("半导体产业链出现重要进展", { exact: true }).waitFor();
  await marketPanel.getByText("半导体", { exact: false }).first().waitFor();
  await marketPanel.getByRole("button", { name: /AI 人工智能/ }).waitFor();
  assert.equal(await marketPanel.getByText("RADAR_NEWS_MUST_NOT_RENDER", { exact: true }).count(), 0);
  assert.equal(await marketPanel.getByRole("button", { name: "刷新", exact: true }).count(), 1);

  await page.getByTestId("market-cloud-scope-cyb").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="market-cloud-scope-cyb"]')?.getAttribute("aria-pressed") === "true");
  assert.ok(requestedScopes.includes("cyb"), "scope switch did not request cyb");
  assert.equal(await page.locator('nav a[href="/intel"]').count(), 0, "sidebar must not expose /intel");

  scenario = "radar-fail";
  nativeRefreshCalls = 0;
  radarRefreshCalls = 0;
  await marketPanel.getByRole("button", { name: "刷新", exact: true }).click();
  await marketPanel.getByText("PARTIAL · 部分可用", { exact: true }).waitFor();
  await marketPanel.getByText("赛道摘要：", { exact: false }).waitFor();
  await marketPanel.getByText("半导体产业链出现重要进展", { exact: true }).waitFor();
  assert.equal(nativeRefreshCalls, 1);
  assert.equal(radarRefreshCalls, 1);

  scenario = "native-fail";
  nativeRefreshCalls = 0;
  radarRefreshCalls = 0;
  await marketPanel.getByRole("button", { name: "刷新", exact: true }).click();
  await marketPanel.getByText("公开资讯：", { exact: false }).waitFor();
  await marketPanel.getByRole("button", { name: /AI 人工智能/ }).waitFor();
  assert.equal(nativeRefreshCalls, 1);
  assert.equal(radarRefreshCalls, 1);

  await page.goto(`http://127.0.0.1:${port}/sectors`, { waitUntil: "domcontentloaded" });
  await page.getByText("板块强度", { exact: true }).waitFor();
  assert.equal(await page.locator("[data-market-cloud]").count(), 0);

  await page.goto(`http://127.0.0.1:${port}/intel`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("market-intel-panel").waitFor({ state: "visible" });
  assert.equal(await page.getByText("Investment News", { exact: true }).count(), 0);
  assert.equal(await page.getByText("关注雷达", { exact: true }).count(), 0);
  assert.deepEqual(pageErrors, []);
  console.log("Today market context browser vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
  await sleep(50);
}
