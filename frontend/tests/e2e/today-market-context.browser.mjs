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
  hint: "semi",
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
    // store 读取失败的真实形状（native_intel_service）：HTTP 200 + status unavailable +
    // store.readable=false，且没有 item_count / sources。
    if (scenario === "native-store-unavailable") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      status: "unavailable",
      error: "本地资讯数据存储不可用，无法读写",
      generated_at: now,
      store: { readable: false, db_path: "unreadable.sqlite3" },
    }) });
    const status = scenario === "native-unavailable" ? "unavailable" : scenario === "both-partial" ? "partial" : "normal";
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      ...nativeRuntime,
      status,
      sources: status === "unavailable" ? { ...nativeRuntime.sources, healthy: 0, failing: 2, failing_names: ["公开来源"] } : nativeRuntime.sources,
    }) });
  }
  if (pathName === "/api/native-intel/items") {
    if (scenario === "native-fail") return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "native intel unavailable" }) });
    // 真实路由在 store 失败分支返回 HTTP 200 + items=[] + 硬编码 total=0。
    if (scenario === "native-store-unavailable") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      status: "unavailable",
      error: "本地资讯数据存储不可用，无法读写",
      items: [],
      total: 0,
      limit: 40,
      offset: 0,
    }) });
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
    // 权威真的读到过、且自报可用，但窗口内确实没有趋势 —— 这才是「确定为空」。
    if (scenario === "native-trending-empty") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      ...nativeTrending,
      status: "normal",
      item_count: 0,
      items: [],
      entities: [],
    }) });
    if (scenario === "native-store-unavailable") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      status: "unavailable",
      error: "本地资讯数据存储不可用，无法读写",
      window_hours: 24,
      item_count: 0,
      items: [],
      entities: [],
    }) });
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
      body: JSON.stringify({ data: { schema_version: "daily-review-v0.1", status: "partial", trade_date: "2026-08-29", generated_at: now, data_cutoff: now, warnings: [], ...(scenario === "daily-populated" ? {
        market_environment: {
          indices: { status: "normal", data: [{name: "上证指数", price: 3100, change_pct: 1.2}, {name: "深证成指", price: 10000, change_pct: -0.2}, {name: "创业板指", price: 2000, change_pct: 0.6}, {name: "科创50", price: 900, change_pct: 0.3}] },
          global_indices: {status: "unavailable", data: []},
          breadth: {status: "normal", data: {up_count: 3200, down_count: 1800, total_amount: 1200000000000}},
        },
        sector_rotation: {industry: {status: "partial", data: {top: [], bottom: []}}, highlights: {strongest_industry: {name: "半导体", change_pct: 2.5}, weakest_industry: {name: "银行", change_pct: -0.8}}},
        capital_activity: {amount_top: [{code: "600519", name: "贵州茅台", amount: 2000000000, change_pct: 1.2}]},
        short_term_emotion: {status: "normal", data: {date: "2026-08-29", zt_count: 45, dt_count: 3, max_boards: 4, lianban_stocks: []}},
        data_health: {components: {turnover: "normal", industry_boards: "partial"}},
      } : {}) } }),
    });
  }
  if (pathName === "/api/daily-review/history") {
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], count: 0, limit: 20, offset: 0 }) });
  }
  if (pathName === "/api/watchlist") {
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: {status: "valid", data: {codes: scenario === "daily-populated" ? ["600519", "000001", "000002", "300750"] : [], updated_at: now}, etag: "today-e2e"} }) });
  }
  if (pathName === "/api/quote") {
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: Object.fromEntries(["600519", "000001", "000002", "300750"].map((code) => [code, {code, name: `样本 ${code}`, price: 1456.78, change_pct: 1.25}])) }) });
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
  assert.ok(todayCloudBox && todayIntelBox && dailyReviewBox && dailyReviewBox.y < todayCloudBox.y && todayCloudBox.y < todayIntelBox.y, "Today should order the review header, the market view, then the intel summary");
  const leads = page.getByTestId("today-research-leads");
  await leads.getByText("行业排名暂不可用", { exact: true }).waitFor();
  const leadsBox = await leads.boundingBox();
  assert.ok(leadsBox && todayCloudBox && leadsBox.y < todayCloudBox.y, "research leads should precede the heatmap");
  assert.equal(await page.locator("#market-detail-emotion").getAttribute("open"), null);
  await leads.getByRole("button", { name: "查看情绪详情", exact: false }).click();
  assert.notEqual(await page.locator("#market-detail-emotion").getAttribute("open"), null);
  await page.locator("#market-detail-emotion > summary").click();
  assert.equal(await todayIntel.getByTestId("market-intel-brief-item").count(), 1);
  assert.equal(await todayIntel.getByTestId("market-intel-brief-diagnostics").getAttribute("open"), null);
  const mainNav = page.locator('nav[aria-label="主导航"]');

  // IA-CONVERGENCE-V1：主侧栏恰为 10 个常驻入口，顺序即分组顺序。
  assert.deepEqual(
    await mainNav.locator("a").evaluateAll((links) => links.map((link) => link.textContent.trim())),
    ["今天", "决策待办", "自选股", "投资研究", "研究资料", "我的持仓", "交易记录", "决策复盘", "数据健康", "设置"],
  );
  assert.equal(await mainNav.locator('a[href="/daily-review"]').count(), 1, "Today must have one primary-nav entry");
  assert.equal(await mainNav.locator('a[href="/market-cloud"]').count(), 0, "Market Heat must not be duplicated in the sidebar");
  assert.equal(await mainNav.locator('a[href="/intel"]').count(), 0, "Intel Radar must not be duplicated in the sidebar");
  assert.equal(await page.getByRole("link", { name: "资讯", exact: true }).count(), 0, "legacy short Intel label must not remain");

  // IA-CONVERGENCE-V1：今天页的主辅区与三视图切换。
  const todayAux = page.getByTestId("today-aux");
  await todayAux.waitFor();
  assert.equal(await page.getByTestId("today-main").count(), 1, "今天页应恰好有一个主区");
  for (const [testid, href] of [
    ["today-aux-decision-inbox", "/decision-inbox"],
    ["today-aux-review-due", "/decision-performance"],
    ["today-aux-watchlist", "/watchlist"],
    ["today-aux-data-health", "/data-health"],
  ]) {
    assert.equal(
      await todayAux.getByTestId(testid).getAttribute("href"),
      href,
      `辅区入口 ${testid} 应指向 ${href}`,
    );
  }
  for (const key of ["market", "history", "compare"]) {
    assert.equal(await page.getByTestId(`today-view-tab-${key}`).count(), 1, `应有「${key}」视图页签`);
  }
  // 切换视图：不得触发任何写请求、不得自动保存快照或自动生成 AI 复盘。
  const todayWrites = [];
  page.on("request", (request) => {
    const method = request.method();
    if (method !== "GET" && method !== "OPTIONS" && request.url().includes("/api/")) {
      todayWrites.push(`${method} ${request.url()}`);
    }
  });
  await page.getByTestId("today-view-tab-history").click();
  await page.getByTestId("today-view-tab-compare").click();
  await page.getByTestId("today-view-tab-market").click();
  assert.deepEqual(todayWrites, [], `切换视图不得产生写请求: ${todayWrites.join("; ")}`);
  await page.getByTestId("today-ai-review").locator("summary").click();
  await page.getByRole("button", {name: "让 AI 复盘今天", exact: true}).waitFor();
  const aiBox = await page.getByTestId("today-ai-review").boundingBox();
  const mainBox = await page.getByTestId("today-main").boundingBox();
  assert.ok(aiBox && mainBox && aiBox.width >= mainBox.width - 2, "expanded AI review should use the full reading width");
  await page.getByTestId("today-ai-review").locator("summary").click();
  assert.deepEqual(todayWrites, [], "opening the saved AI review must not automatically generate a new one");
  // 切回当前市场后，实时数据与市场云图仍然在位（历史/对比不覆盖实时数据）。
  await todayCloud.locator("[data-market-cloud-chart]").waitFor({ state: "visible", timeout: 15000 });
  assert.equal(await todaySurface.getByTestId("market-intel-panel").count(), 1, "切回当前市场后市场情报仍在位");

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
  // IA-CONVERGENCE-V1：/intel 归「投资研究·资讯中心」，不再挂在「今天」下。
  await page.waitForFunction(() => {
    const el = document.querySelector('nav[aria-label="主导航"] a[href="/screener"]');
    return !!el && el.getAttribute("aria-current") === "page";
  });
  assert.equal(
    await page.locator('[data-testid="section-nav"] a[href="/intel"]').getAttribute("aria-current"),
    "page",
    "/intel 应在二级导航点亮资讯中心",
  );
  assert.equal(await page.getByRole("heading", { name: "市场情报", exact: true }).count(), 1);
  assert.equal(await page.locator("[data-market-cloud]").count(), 0, "Intel must not embed Market Cloud");
  // normal：trending 读取成功且有数据 → 保持真实趋势展示，不出现「空窗口」提示。
  await marketPanel.locator('[aria-label="近 24 小时关注趋势"]').waitFor();
  assert.equal(await marketPanel.getByTestId("market-intel-trending-empty").count(), 0);
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
  scenario = "native-fail";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const failedIntel = page.getByTestId("market-intel-panel");
  await failedIntel.getByTestId("market-intel-brief-diagnostics").locator("summary").click();
  await failedIntel.getByText("公开资讯：", { exact: false }).waitFor();
  // 公开资讯权威从未读取：计数块必须显示未知，不得把未知渲染成已核实的 0。
  assert.equal(
    await failedIntel.getByTestId("market-intel-stat-history").innerText(),
    "历史资讯 未知",
  );
  assert.equal(
    await failedIntel.getByTestId("market-intel-stat-sources").innerText(),
    "公开来源 未知",
  );
  assert.equal(
    (await failedIntel.getByTestId("market-intel-stat-sources").innerText()).includes("正常"),
    false,
    "unread source authority must not claim 正常",
  );
  // trending 请求被拒（trending 从未成功读取）→ 不得宣称「暂无趋势」。
  // 空态元素在 loading 阶段就已存在，断言必须等到数据到达后属性变成目标值。
  const unreadTrend = failedIntel.locator('[data-testid="market-intel-trending-empty"][data-trend-empty-reason="unread"]');
  await unreadTrend.waitFor();
  assert.doesNotMatch(
    await unreadTrend.innerText(),
    /暂无/,
    "unread trending must not be asserted as an empty window",
  );

  // store 读取失败：/items 用 HTTP 200 + 硬编码 total=0 表达失败，
  // 那个 0 不是计到的条数，不得渲染成「历史资讯 0」。
  scenario = "native-store-unavailable";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const storeFailedIntel = page.getByTestId("market-intel-panel");
  await storeFailedIntel.getByTestId("market-intel-brief-diagnostics").locator("summary").click();
  await storeFailedIntel.getByTestId("market-intel-stat-history").waitFor();
  assert.equal(
    await storeFailedIntel.getByTestId("market-intel-stat-history").innerText(),
    "历史资讯 未知",
  );
  assert.equal(
    await storeFailedIntel.getByTestId("market-intel-stat-sources").innerText(),
    "公开来源 未知",
  );
  // radar 权威本身读取正常，计数块不受影响。
  assert.equal(
    await storeFailedIntel.getByTestId("market-intel-stat-radar").innerText(),
    "赛道来源 12 · 12 赛道",
  );
  // HTTP 成功但权威自报 unavailable → 同样不得宣称「暂无趋势」。
  const unavailableTrend = storeFailedIntel.locator('[data-testid="market-intel-trending-empty"][data-trend-empty-reason="unavailable"]');
  await unavailableTrend.waitFor();
  assert.doesNotMatch(await unavailableTrend.innerText(), /暂无/);

  // 权威读取成功、自报可用、窗口内确实没有趋势 → 这才允许宣称「暂无」。
  scenario = "native-trending-empty";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const emptyTrendIntel = page.getByTestId("market-intel-panel");
  await emptyTrendIntel.getByTestId("market-intel-brief-diagnostics").locator("summary").click();
  const emptyTrend = emptyTrendIntel.locator('[data-testid="market-intel-trending-empty"][data-trend-empty-reason="empty"]');
  await emptyTrend.waitFor();
  assert.equal(await emptyTrend.innerText(), "当前窗口暂无可计算的关注趋势。");

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
  await unavailableIntel.getByTestId("market-intel-brief-diagnostics").locator("summary").click();
  await unavailableIntel.getByText("PARTIAL · 部分可用", { exact: true }).waitFor();
  await unavailableIntel.getByText("公开资讯：", { exact: false }).waitFor();
  assert.equal(await unavailableIntel.getByRole("button", { name: /AI 人工智能/ }).count(), 0, "Today keeps AI digest actions in the full intel workspace");
  await unavailableIntel
    .locator('[data-testid="market-intel-trending-empty"][data-trend-empty-reason="unavailable"]')
    .waitFor();
  await page.getByTestId("today-market-surface").locator("[data-market-cloud-chart]").waitFor({ state: "visible" });

  scenario = "radar-fail";
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const radarUnavailableIntel = page.getByTestId("market-intel-panel");
  await radarUnavailableIntel.getByTestId("market-intel-brief-diagnostics").locator("summary").click();
  await radarUnavailableIntel.getByText("PARTIAL · 部分可用", { exact: true }).waitFor();
  await radarUnavailableIntel.getByText("半导体产业链出现重要进展", { exact: true }).waitFor();
  await radarUnavailableIntel.getByText("赛道摘要：", { exact: false }).waitFor();
  assert.equal(
    await radarUnavailableIntel.getByTestId("market-intel-stat-radar").innerText(),
    "赛道来源 未知 · 未知 赛道",
    "radar 权威未读取时不得用本地列表长度或其他默认值冒充赛道计数",
  );

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

  scenario = "daily-populated";
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`http://127.0.0.1:${port}/daily-review`, { waitUntil: "domcontentloaded" });
  const populatedLeads = page.getByTestId("today-research-leads");
  await populatedLeads.getByText("半导体 · +2.5% · 行业涨幅排名居前", { exact: true }).waitFor();
  await populatedLeads.getByText("数据不完整", { exact: true }).waitFor();
  assert.equal(await populatedLeads.getByRole("link", {name: "候选研究", exact: false}).getAttribute("href"), "/candidates/600519");
  await populatedLeads.getByText("涨停 45 家 · 跌停 3 家 · 最高 4 板", {exact: true}).waitFor();
  await page.getByText("管理关注股票", {exact: true}).click();
  const watchCards = page.getByTestId("today-watch-manager-quotes");
  await watchCards.getByText("1456.78", {exact: true}).first().waitFor();
  assert.equal(await watchCards.locator(":scope > div").count(), 4);
  assert.equal(await watchCards.locator(":scope > div").evaluateAll((cards) => cards.every((card) => card.scrollWidth <= card.clientWidth)), true, "expanded watch quotes must fit the 300px side column");
  assert.equal(await watchCards.locator("p.font-mono").evaluateAll((prices) => prices.every((price) => price.scrollWidth <= price.clientWidth)), true, "quote prices must not overlap adjacent cards");
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
