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

const marketCloud = (scope, status = "normal") => ({
  status,
  warnings: status === "partial" ? ["部分行业数据缺失，仍显示有效快照"] : [],
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
const marketCloudAuthorization = [];

async function handleApi(route) {
  const request = route.request();
  const url = new URL(request.url());
  const pathName = url.pathname;

  if (pathName === "/api/market/cloud") {
    const scope = url.searchParams.get("scope") || "all";
    requestedScopes.push(scope);
    marketCloudAuthorization.push(request.headers()["authorization"] || null);
    if (scenario === "cloud-fail") {
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "market cloud unavailable" }) });
    }
    const cloudStatus = scenario === "cloud-partial" || scenario === "both-partial" ? "partial" : "normal";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: marketCloud(scope, cloudStatus) }) });
  }
  if (pathName === "/api/native-intel/status") {
    if (scenario === "native-fail") return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "native intel unavailable" }) });
    const status = scenario === "native-unavailable" ? "unavailable" : scenario === "both-partial" ? "partial" : "normal";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      ...nativeRuntime,
      status,
      sources: status === "unavailable" ? { ...nativeRuntime.sources, healthy: 0, failing: 2, failing_names: ["公开来源"] } : nativeRuntime.sources,
    }) });
  }
  if (pathName === "/api/native-intel/items") {
    if (scenario === "native-fail") return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "native intel unavailable" }) });
    const status = scenario === "native-unavailable" ? "unavailable" : "normal";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      ...nativeItems,
      status,
      items: status === "unavailable" ? [] : nativeItems.items,
      total: status === "unavailable" ? 0 : nativeItems.total,
    }) });
  }
  if (pathName === "/api/native-intel/trending") {
    if (scenario === "native-fail") return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "native intel unavailable" }) });
    const status = scenario === "native-unavailable" ? "unavailable" : "normal";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      ...nativeTrending,
      status,
      items: status === "unavailable" ? [] : nativeTrending.items,
      entities: status === "unavailable" ? [] : nativeTrending.entities,
    }) });
  }
  if (pathName === "/api/native-intel/refresh") {
    nativeRefreshCalls += 1;
    if (scenario === "native-fail") return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "native refresh failed" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ accepted: true, status: "normal" }) });
  }
  if (pathName === "/api/radar" && request.method() === "GET") {
    if (scenario === "radar-fail") return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "radar unavailable" }) });
    const radarPayload = scenario === "both-partial" ? { ...radar, stats: { ...radar.stats, failed_sources: 1 } } : radar;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(radarPayload) });
  }
  if (pathName === "/api/radar/refresh") {
    radarRefreshCalls += 1;
    if (scenario === "radar-fail") return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "radar refresh failed" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(radar) });
  }
  if (pathName === "/api/daily-review") {
    if (scenario === "daily-fail") {
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "daily review unavailable" }) });
    }
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
  await page.addInitScript(() => {
    localStorage.setItem("vr-access-key", "test-key");
    const originalFetch = window.fetch.bind(window);
    window.__marketCloudPendingScopes = [];
    window.__marketCloudAbortScopes = [];
    window.fetch = (input, init) => {
      const rawUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(rawUrl, window.location.origin);
      const scope = url.pathname === "/api/market/cloud" ? url.searchParams.get("scope") : null;
      if (scope === "star") {
        window.__marketCloudPendingScopes.push(scope);
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            window.__marketCloudAbortScopes.push(scope);
            reject(new DOMException("Aborted", "AbortError"));
          }, { once: true });
        });
      }
      return originalFetch(input, init);
    };
  });
  await page.route("**/api/**", handleApi);

  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "今天", exact: true }).waitFor();
  await page.locator("#daily-review-section-title").waitFor();
  const todaySurface = page.getByTestId("today-market-surface");
  const todayCloud = todaySurface.locator("[data-market-cloud]");
  const todayIntel = todaySurface.getByTestId("market-intel-panel");
  await todayCloud.locator("[data-market-cloud-chart]").waitFor({ state: "visible", timeout: 15000 });
  await todayIntel.getByText("半导体产业链出现重要进展", { exact: true }).waitFor();
  assert.equal(await todaySurface.locator("[data-market-cloud]").count(), 1, "Today should embed one Market Cloud");
  assert.equal(await todaySurface.getByTestId("market-intel-panel").count(), 1, "Today should embed one market intel panel");
  assert.equal(await todaySurface.getByTestId("today-market-cloud-link").getAttribute("href"), "/market-cloud");
  assert.equal(await todaySurface.getByTestId("today-intel-link").getAttribute("href"), "/intel");
  const todayCloudBox = await todayCloud.boundingBox();
  const todayIntelBox = await todayIntel.boundingBox();
  const dailyReviewBox = await page.locator("#daily-review-section-title").boundingBox();
  assert.ok(todayCloudBox && todayIntelBox && dailyReviewBox && todayCloudBox.y < todayIntelBox.y && todayIntelBox.y < dailyReviewBox.y, "Today should order Market Cloud, market intel, then Daily Review");
  const mainNav = page.locator('nav[aria-label="主导航"]');
  const todayGroup = mainNav.locator(':scope > div[class~="space-y-0.5"] > div.relative').first();
  const todayLink = todayGroup.locator(':scope > a');
  const todayChildren = todayGroup.locator(':scope > div[class*="pl-4"] > a');

  // Final IA: 今天 is the canonical entry; full Market Cloud and Intel routes remain in-page links.
  assert.equal(await todayLink.getAttribute("href"), "/daily-review");
  assert.equal(await todayChildren.count(), 0, "Today must not duplicate Market Cloud or Intel in the sidebar");
  const navOrder = await mainNav.locator(':scope > div[class~="space-y-0.5"]').evaluate((container) => (
    Array.from(container.children).flatMap((entry) => {
      if (entry.matches(".relative")) {
        const parent = entry.querySelector(":scope > a");
        const children = entry.querySelector(':scope > div[class*="pl-4"]');
        return [parent, ...(children ? Array.from(children.children) : [])];
      }
      return entry.matches("a") ? [entry] : [];
    })
      .filter((link) => link instanceof HTMLAnchorElement)
      .map((link) => link.textContent.trim())
  ));
  assert.deepEqual(navOrder.slice(0, 5), ["今天", "发现", "自选", "个股", "持仓"]);
  assert.equal(await mainNav.locator('a[href="/daily-review"]').count(), 1, "Today must have one primary-nav entry");
  assert.equal(await mainNav.locator('a[href="/market-cloud"]').count(), 0, "Market Heat must not be duplicated in the sidebar");
  assert.equal(await mainNav.locator('a[href="/intel"]').count(), 0, "Intel Radar must not be duplicated in the sidebar");
  assert.equal(await page.getByRole("link", { name: "资讯", exact: true }).count(), 0, "legacy short Intel label must not remain");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("today-market-surface").locator("[data-market-cloud-chart]").waitFor({ state: "visible", timeout: 15000 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "Today must not overflow horizontally on narrow screens");
  const narrowToolbar = await page.getByTestId("today-market-surface").locator('[role="toolbar"]').boundingBox();
  assert.ok(narrowToolbar && narrowToolbar.width <= 382, `narrow scope controls should fit viewport, got ${narrowToolbar?.width}`);
  await page.getByTestId("nav-drawer-trigger").click();
  const narrowSidebar = page.getByTestId("app-sidebar");
  await narrowSidebar.getByRole("link", { name: "今天", exact: true }).waitFor();
  assert.equal(await narrowSidebar.locator('a[href="/market-cloud"]').count(), 0);
  assert.equal(await narrowSidebar.locator('a[href="/intel"]').count(), 0);
  await page.getByTestId("nav-drawer-trigger").click();
  await page.setViewportSize({ width: 1920, height: 1080 });

  await page.goto(`http://127.0.0.1:${port}/market-cloud`, { waitUntil: "domcontentloaded" });
  const chart = page.locator("[data-market-cloud-chart]");
  await chart.waitFor({ state: "visible", timeout: 15000 });
  assert.equal(new URL(page.url()).pathname, "/market-cloud");
  await page.reload({ waitUntil: "domcontentloaded" });
  await chart.waitFor({ state: "visible", timeout: 15000 });
  assert.equal(new URL(page.url()).pathname, "/market-cloud");
  assert.equal(await mainNav.locator('a[href="/daily-review"]').getAttribute("aria-current"), "page");

  const chartBox = await chart.boundingBox();
  assert.ok(chartBox && chartBox.width > 1400, `expected wide market cloud, got ${chartBox?.width}`);
  assert.ok(chartBox && chartBox.height >= 620, `expected tall market cloud, got ${chartBox?.height}`);

  await page.getByTestId("market-cloud-scope-cyb").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="market-cloud-scope-cyb"]')?.getAttribute("aria-pressed") === "true");
  assert.ok(requestedScopes.includes("cyb"), "scope switch did not request cyb");

  await page.getByTestId("market-cloud-scope-star").click();
  await page.waitForFunction(() => window.__marketCloudPendingScopes?.includes("star"));
  await page.getByTestId("market-cloud-scope-sh").click();
  await page.waitForFunction(() => window.__marketCloudAbortScopes?.includes("star"));
  await page.waitForFunction(() => document.querySelector('[data-testid="market-cloud-scope-sh"]')?.getAttribute("aria-pressed") === "true");
  assert.ok(requestedScopes.includes("sh"), "scope switch did not request sh after aborting star");
  assert.ok(marketCloudAuthorization.length >= 3, "expected authenticated market cloud requests");
  assert.ok(marketCloudAuthorization.every((value) => value === "Bearer test-key"), `unexpected market cloud Authorization headers: ${JSON.stringify(marketCloudAuthorization)}`);

  await page.goto(`http://127.0.0.1:${port}/intel`, { waitUntil: "domcontentloaded" });
  const marketPanel = page.getByTestId("market-intel-panel");
  await marketPanel.waitFor({ state: "visible", timeout: 15000 });
  assert.equal(new URL(page.url()).pathname, "/intel");
  await page.reload({ waitUntil: "domcontentloaded" });
  await marketPanel.waitFor({ state: "visible", timeout: 15000 });
  assert.equal(new URL(page.url()).pathname, "/intel");
  assert.equal(await mainNav.locator('a[href="/daily-review"]').getAttribute("aria-current"), "page");
  assert.equal(await page.getByRole("heading", { name: "市场情报", exact: true }).count(), 1);
  assert.equal(await page.locator("[data-market-cloud]").count(), 0, "Intel must not embed Market Cloud");
  assert.equal(await page.getByText("Investment News", { exact: true }).count(), 0);
  assert.equal(await page.getByText("关注雷达", { exact: true }).count(), 0);
  await marketPanel.getByText("半导体产业链出现重要进展", { exact: true }).waitFor();
  await marketPanel.getByText("2026-08-29 11:00", { exact: true }).first().waitFor();
  await marketPanel.getByText("半导体", { exact: false }).first().waitFor();
  await marketPanel.getByRole("button", { name: /AI 人工智能/ }).waitFor();
  assert.equal(await marketPanel.getByText("RADAR_NEWS_MUST_NOT_RENDER", { exact: true }).count(), 0);
  assert.equal(await marketPanel.getByRole("button", { name: "刷新", exact: true }).count(), 1);

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

  // Initial-load fixtures: each surface keeps its own honest state.
  scenario = "cloud-fail";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  await page.getByText("市场快照暂不可用", { exact: true }).first().waitFor();
  await page.getByTestId("market-intel-panel").getByText("半导体产业链出现重要进展", { exact: true }).waitFor();
  await page.locator("#daily-review-section-title").waitFor();

  scenario = "cloud-partial";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("today-market-surface").getByText("部分数据缺失", { exact: true }).waitFor();
  await page.getByTestId("today-market-surface").locator("[data-market-cloud-chart]").waitFor({ state: "visible" });

  scenario = "native-unavailable";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const unavailableIntel = page.getByTestId("market-intel-panel");
  await unavailableIntel.getByText("PARTIAL · 部分可用", { exact: true }).waitFor();
  await unavailableIntel.getByText("公开资讯：", { exact: false }).waitFor();
  await unavailableIntel.getByRole("button", { name: /AI 人工智能/ }).waitFor();
  await page.getByTestId("today-market-surface").locator("[data-market-cloud-chart]").waitFor({ state: "visible" });

  scenario = "radar-fail";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const radarUnavailableIntel = page.getByTestId("market-intel-panel");
  await radarUnavailableIntel.getByText("PARTIAL · 部分可用", { exact: true }).waitFor();
  await radarUnavailableIntel.getByText("半导体产业链出现重要进展", { exact: true }).waitFor();
  await radarUnavailableIntel.getByText("赛道摘要：", { exact: false }).waitFor();

  scenario = "daily-fail";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  await page.getByText("每日复盘请求失败：", { exact: false }).waitFor();
  await page.getByTestId("today-market-surface").locator("[data-market-cloud-chart]").waitFor({ state: "visible" });
  await page.getByTestId("market-intel-panel").getByText("半导体产业链出现重要进展", { exact: true }).waitFor();

  scenario = "both-partial";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("today-market-surface").getByText("部分数据缺失", { exact: true }).waitFor();
  await page.getByTestId("market-intel-panel").getByText("PARTIAL · 部分可用", { exact: true }).waitFor();
  await page.getByTestId("today-market-surface").locator("[data-market-cloud-chart]").waitFor({ state: "visible" });

  scenario = "normal";

  await page.goto(`http://127.0.0.1:${port}/sectors`, { waitUntil: "domcontentloaded" });
  await page.getByText("板块强度", { exact: true }).waitFor();
  assert.equal(await page.locator("[data-market-cloud]").count(), 0);

  assert.deepEqual(pageErrors, []);
  console.log("Market surface navigation browser vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
  await sleep(50);
}
