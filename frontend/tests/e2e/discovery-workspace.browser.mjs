import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(here, "../../dist");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(typeof address === "object" && address ? address.port : 0));
    });
  });
}

function startStaticServer(port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let pathname = decodeURIComponent((request.url || "/").split("?")[0]);
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dist, pathname);
    if (!existsSync(target) || path.extname(target) === "") target = path.join(dist, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function launchBrowser() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  try {
    return await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : { channel: "chrome" }) });
  } catch (error) {
    if (executablePath) throw error;
    return chromium.launch({ headless: true });
  }
}

function opportunity(overrides) {
  return {
    security_code: "600519",
    name: "贵州茅台",
    strategy: "SWING",
    sector: "食品饮料",
    themes: ["消费"],
    discovery_state: "QUEUED",
    research_priority: "HIGH",
    reason_codes: ["SECTOR_CONTEXT_SUPPORT", "CATALYST_DISCLOSED"],
    supporting_observations: [
      { code: "POSITIVE_RETURN_20D", label: "20 日相对表现", value: 0.12, source_ref: "research-data-plane:return_20d" },
      { code: "LIQUIDITY_AT_OR_ABOVE_MARKET_MEDIAN", label: "成交额位于市场中位数以上", value: 1_250_000_000, source_ref: "market:a-share-snapshot:amount" },
      { code: "SECTOR_CONTEXT_SUPPORTIVE", label: "行业相对市场状态", value: 1.25, source_ref: "market:a-share-snapshot:industry" },
      { code: "CATALYST_CLUE_AVAILABLE", label: "近期公告线索", value: { announcement_count: 2, intel_mentions: null, intel_sources: 1, intel_mapping_status: "MAPPED" }, source_ref: "announcement:fixture" },
    ],
    uncertainties: [],
    data_health: "normal",
    catalyst_status: "AVAILABLE",
    fundamental_status: "AVAILABLE",
    evidence_gate: "SUFFICIENT_FOR_RESEARCH",
    restricted_universe: { status: "CLEAR", reason_codes: [], listing_age_status: "KNOWN" },
    discovered_at: "2026-08-30T02:00:00Z",
    as_of: "2026-08-28",
    provenance_refs: ["market:fixture", "rdp:fixture"],
    ...overrides,
  };
}

const shortOnly = opportunity({
  security_code: "000001",
  name: "平安银行",
  strategy: "SHORT",
  sector: "银行",
  themes: ["高流动性"],
  research_priority: "MEDIUM",
  reason_codes: ["SHORT_VOLUME_ACTIVITY", "SHORT_MARKET_LIQUIDITY"],
  supporting_observations: [
    { code: "POSITIVE_SESSION_MOMENTUM", label: "当日价格动量为正", value: 2.5, source_ref: "market:a-share-snapshot:change_pct" },
    { code: "TURNOVER_IN_ACTIVE_MARKET_QUARTILE", label: "换手率位于活跃区间", value: 8.25, source_ref: "market:a-share-snapshot:turnover_pct" },
  ],
});
const swing = opportunity({});
const restricted = opportunity({
  security_code: "600221",
  name: "*ST海航",
  strategy: "SWING",
  sector: "交通运输",
  themes: [],
  research_priority: "LOW",
  reason_codes: ["RESTRICTED_RESEARCH_ONLY", "ST_NAME_MARKER"],
  uncertainties: ["受限股票需要继续核对研究资格", "FUNDAMENTAL_FRESHNESS_UNKNOWN"],
  catalyst_status: "PARTIAL",
  evidence_gate: "PARTIAL",
  restricted_universe: { status: "RESTRICTED", reason_codes: ["ST_NAME_MARKER"], listing_age_status: "KNOWN" },
});
const mediumOnly = opportunity({
  security_code: "300750",
  name: "宁德时代",
  strategy: "MEDIUM",
  sector: "电力设备",
  themes: ["新能源"],
  reason_codes: ["MEDIUM_FUNDAMENTAL_AVAILABLE", "MEDIUM_SECTOR_SUPPORT"],
  supporting_observations: [
    { code: "POSITIVE_RETURN_60D", label: "60 日收益为正", value: 0.25, source_ref: "research-data-plane:return_60d" },
    { code: "BASIC_VALUATION_AVAILABLE", label: "基础估值", value: { pe_ttm: 18.5, pb: null }, source_ref: "market:a-share-snapshot:pe_pb" },
    { code: "FUNDAMENTAL_FACT_AVAILABLE", label: "财务事实", value: { revenue_yoy: 12.5, operating_cash_flow: -250_000_000, roe: null }, source_ref: "astock.financials" },
    { code: "UNRECOGNIZED_METRIC", label: "原始观察值", value: 0.123456, source_ref: "fixture:unknown" },
  ],
});
const unknown = opportunity({
  security_code: "300012",
  name: "华测检测",
  strategy: "SWING",
  sector: null,
  themes: [],
  research_priority: "MEDIUM",
  reason_codes: ["SECTOR_CONTEXT_UNKNOWN", "FUNDAMENTAL_UNKNOWN"],
  supporting_observations: [{ code: "LIQUIDITY", label: "流动性", value: "AVAILABLE", source_ref: "market:fixture" }],
  uncertainties: ["行业上下文未知", "财务事实缺失"],
  data_health: "unknown",
  catalyst_status: "PARTIAL",
  fundamental_status: "UNKNOWN",
  evidence_gate: "UNKNOWN",
});

function snapshot({ partial = false, stale = false } = {}) {
  const degraded = partial || stale;
  const fetchedAt = degraded ? "2026-08-30T03:00:00Z" : "2026-08-30T02:00:00Z";
  return {
    schema_version: "full-market-discovery.v0.1",
    status: stale ? "stale" : partial ? "partial" : "normal",
    as_of: "2026-08-28",
    fetched_at: fetchedAt,
    last_successful_at: fetchedAt,
    refresh_attempted_at: stale ? "2026-08-30T04:00:00Z" : fetchedAt,
    market_context: {
      status: degraded ? "partial" : "normal",
      core_universe_count: 5280,
      outside_core_count: 120,
      sector_count: degraded ? 2 : 4,
      market_average_change_pct: 0.38,
      amount_median: 180000000,
      turnover_active_threshold: 2.1,
      source_ref: "market:fixture",
    },
    funnel: {
      core_universe: 5280,
      cheap_scan_passed: 96,
      qualification_candidates: 24,
      queue_items: { SHORT: 1, SWING: degraded ? 3 : 2, MEDIUM: 1 },
      excluded: 1,
    },
    datasets: [
      { dataset_id: "market-snapshot", status: "normal", as_of: "2026-08-28", fetched_at: fetchedAt, reason_code: null, provenance_refs: ["market:fixture"] },
      { dataset_id: "sector-context", status: degraded ? "unavailable" : "normal", as_of: degraded ? null : "2026-08-28", fetched_at: fetchedAt, reason_code: degraded ? "PROVIDER_UNAVAILABLE" : null, provenance_refs: ["sector:fixture"] },
      { dataset_id: "fundamental-qualification", status: degraded ? "partial" : "normal", as_of: null, fetched_at: fetchedAt, reason_code: degraded ? "SOME_SECURITIES_UNKNOWN" : null, provenance_refs: ["financial:fixture"] },
      { dataset_id: "catalyst-qualification", status: degraded ? "partial" : "normal", as_of: "2026-08-30", fetched_at: fetchedAt, reason_code: degraded ? "SOURCE_PARTIAL" : null, provenance_refs: ["announcement:fixture", "native-intel:fixture"] },
    ],
    queues: {
      SHORT: [shortOnly],
      SWING: degraded ? [swing, unknown, restricted] : [swing, restricted],
      MEDIUM: [mediumOnly],
    },
    excluded: [{
      security_code: "603001",
      name: "退市风险样本",
      strategy: "SWING",
      reason_codes: ["RESTRICTED_QUALIFICATION_BLOCKED"],
      data_health: "partial",
      restricted_universe: { status: "RESTRICTED", reason_codes: ["DELISTING_RISK"], listing_age_status: "KNOWN" },
      as_of: "2026-08-28",
    }],
    limitations: degraded ? ["部分来源失败；UNKNOWN 保持 UNKNOWN，其他可用股票继续形成研究队列。"] : [],
    cache: { hit: stale, age_seconds: stale ? null : 0, refresh_failed: stale },
  };
}

const ok = (data) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ data }) });

function nativeIntelContext() {
  return {
    status: "normal",
    retrieved_at: "2026-08-30T03:00:00Z",
    authority_ref: "vibe:native-intel:fixture",
    usage_boundary: "observation_only_not_an_investment_authority",
    window_hours: 168,
    security: { code: "600519", company_name: "贵州茅台" },
    mapping: { status: "MAPPED", term_count: 1, terms: [{ term: "600519", term_kind: "security_code", source_ref: "fixture" }], errors: [] },
    observation: { items: [], item_count: 0, mention_count: 0, source_count: 0, first_seen_at: null, last_seen_at: null },
    rank_history: { available: false, reason: "fixture_has_no_rank" },
  };
}

function relativePeriod(stock, industry, vsIndustry, market, vsMarket) {
  return {
    stock_return_pct: stock,
    industry_median_pct: industry,
    vs_industry_pct_points: vsIndustry,
    market_median_pct: market,
    vs_market_pct_points: vsMarket,
    industry_valid_count: 3,
    industry_member_count: 3,
    industry_coverage: 1,
    market_valid_count: 4,
    market_total_count: 4,
    market_coverage: 1,
  };
}

function stockRelativeContext(code) {
  return {
    schema_version: "stock-relative-context.v0.1",
    status: "normal",
    source: "RESEARCH_DATA_PLANE+EASTMONEY_CURRENT_INDUSTRY",
    fetched_at: "2026-09-11T08:00:00Z",
    code,
    comparison_date: "2026-09-11",
    industry_name: "电子",
    industry_status: "normal",
    industry_membership_semantics: "CURRENT_MEMBERSHIP_SNAPSHOT",
    dataset_id: "ashare_daily_unadjusted",
    provider_id: "local_bulk_dump",
    adjustment: "UNADJUSTED",
    return_semantics: "UNADJUSTED_RAW_PRICE_CHANGE",
    relative_unit: "PERCENTAGE_POINTS",
    stock: { return_5d_pct: 12, return_20d_pct: 10, return_60d_pct: 30 },
    periods: {
      "5D": relativePeriod(12, 6, 6, 5, 7),
      "20D": relativePeriod(10, 8, 2, 5.5, 4.5),
      "60D": relativePeriod(30, 20, 10, 15, 15),
    },
    provenance: {
      classification_provider: "EASTMONEY",
      membership_source: "astock.a_share_snapshot.industry=f100",
      membership_semantics: "CURRENT_MEMBERSHIP_SNAPSHOT",
      rdp: { artifact_sha256: "fixture" },
    },
    warnings: [],
    limitations: [],
  };
}

function stockValuationContextPayload(code) {
  const metric = (stock, median, delta, rank) => ({
    stock_value: stock,
    stock_sign: stock == null ? "missing" : stock > 0 ? "positive" : stock === 0 ? "zero" : "negative",
    industry_positive_median: median,
    vs_industry_positive_median: delta,
    rank_among_positive: rank,
    positive_sample_count: 2,
    rank_order: "ASCENDING_POSITIVE_VALUES",
    industry_observed_count: 4,
    industry_missing_count: 0,
    industry_positive_count: 2,
    industry_zero_count: 1,
    industry_negative_count: 1,
    industry_median_status: "NORMAL",
  });
  return {
    schema_version: "stock-valuation-context.v0.1",
    status: "normal",
    source: "EASTMONEY_A_SHARE_SNAPSHOT",
    fetched_at: "2026-09-12T08:00:00Z",
    code,
    industry_name: "电子",
    industry_status: "normal",
    industry_membership_semantics: "CURRENT_MEMBERSHIP_SNAPSHOT",
    valuation_semantics: "CURRENT_MEMBER_VALUATION_DISTRIBUTION_ONLY",
    historical_valuation_status: "NOT_AVAILABLE",
    sector_index_valuation_authority: "NOT_AVAILABLE",
    industry_member_count: 4,
    pe_source: "eastmoney_clist_f115",
    pb_source: "eastmoney_clist_f23",
    pe_ttm: metric(10, 15, -5, 1),
    pb: metric(1, 1.5, -0.5, 1),
    provenance: {
      classification_provider: "EASTMONEY",
      membership_source: "astock.a_share_snapshot.industry=f100",
      membership_semantics: "CURRENT_MEMBERSHIP_SNAPSHOT",
      pe_ttm_field: "f115",
      pb_field: "f23",
      dynamic_pe_field: "f9",
      dynamic_pe_used: false,
    },
    warnings: [],
    limitations: [],
  };
}

let server;
let browser;
const apiRequests = [];
const browserErrors = [];
let discoveryRefreshes = 0;
try {
  assert.ok(existsSync(path.join(dist, "index.html")), "frontend/dist missing; run npm run build first");
  const port = await freePort();
  server = await startStaticServer(port);
  browser = await launchBrowser();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.addInitScript(() => localStorage.setItem("vr-theme", "dark"));
  page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });
  page.on("pageerror", (error) => browserErrors.push(`pageerror: ${error.message}`));
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    apiRequests.push({ method: request.method(), pathname: url.pathname, search: url.search });
    if (url.pathname === "/api/screener/discovery" && request.method() === "GET") {
      const refresh = url.searchParams.get("refresh") === "true";
      if (refresh) discoveryRefreshes += 1;
      const payload = snapshot({
        partial: refresh && discoveryRefreshes === 1,
        stale: refresh && discoveryRefreshes > 1,
      });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
      return;
    }
    if (url.pathname === "/api/position/derived" && request.method() === "GET") {
      await route.fulfill(ok({ derivation_status: "OK", bootstrap_status: "BOOTSTRAPPED", canonical: true, ledger_start: null, positions: [], data_limitations: [] }));
      return;
    }
    if (url.pathname === "/api/evidence" && request.method() === "GET") {
      await route.fulfill(ok({ items: [], total: 0, limit: 200, offset: 0 }));
      return;
    }
    if (url.pathname === "/api/native-intel/security-context/600519" && request.method() === "GET") {
      await route.fulfill(ok(nativeIntelContext()));
      return;
    }
    if (url.pathname === "/api/campaigns" && request.method() === "GET") {
      assert.equal(url.searchParams.get("security_code"), "600519");
      await route.fulfill(ok([]));
      return;
    }
    if (url.pathname === "/api/stock-relative-context" && request.method() === "GET") {
      const code = url.searchParams.get("code") || "600519";
      await route.fulfill(ok(stockRelativeContext(code)));
      return;
    }
    if (url.pathname === "/api/stock-valuation-context" && request.method() === "GET") {
      const code = url.searchParams.get("code") || "600519";
      await route.fulfill(ok(stockValuationContextPayload(code)));
      return;
    }
    if (url.pathname === "/api/research-events" && request.method() === "GET") {
      const code = url.searchParams.get("security_code") || "600519";
      await route.fulfill(ok({
        schema_version: "research_event_calendar.v0.1",
        status: "NORMAL",
        as_of: "2026-08-30",
        fetched_at: "2026-08-30T02:00:00.000000Z",
        window: { date_from: "2026-08-16", date_to: "2026-11-28", semantics: "CALENDAR_DAYS" },
        universe: {
          kind: "SINGLE_SECURITY",
          status: "NORMAL",
          campaign_count: 0,
          unique_security_count: 1,
          max_unique_securities: 1,
          securities: [{ security_code: code, security_name: null, campaign_ids: [] }],
        },
        events: [],
        sources: [],
        limitations: ["NO_EXPLICIT_EVENT_CATALYST_LINK"],
        writes: { campaign: 0, thesis: 0, evidence: 0, decision: 0, trade: 0, account: 0 },
      }));
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `unmocked ${request.method()} ${url.pathname}` }) });
  });

  await page.goto(`http://127.0.0.1:${port}/screener`, { waitUntil: "networkidle" });
  const workspace = page.getByTestId("discovery-workspace");
  await workspace.waitFor();

  // A: /screener is the one Discovery entry; the default SWING queue explains research-only opportunities.
  assert.equal(await page.getByTestId("discovery-tab").getAttribute("aria-selected"), "true");
  assert.equal(await page.getByTestId("strategy-SWING").getAttribute("aria-selected"), "true");
  assert.equal(await page.getByTestId("full-market-form").count(), 0);
  await page.getByTestId("discovery-summary").getByText(/行情归属 2026-08-28/).waitFor();
  assert.doesNotMatch(await page.getByTestId("discovery-summary").innerText(), /行情归属 2026-08-30/);
  const firstCard = page.getByTestId("discovery-item-SWING-600519");
  const firstSummary = page.getByTestId("discovery-summary-observations-600519");
  await firstSummary.getByText("20 日相对表现", { exact: true }).waitFor();
  assert.equal(await firstSummary.locator("div").filter({ hasText: "20 日相对表现" }).locator("dd").innerText(), "+12.00%");
  assert.equal(await firstSummary.locator("div").filter({ hasText: "成交额位于市场中位数以上" }).locator("dd").innerText(), "12.50 亿元");
  assert.equal(await firstSummary.locator("div").filter({ hasText: "行业相对市场状态" }).locator("dd").innerText(), "+1.25%");
  assert.equal(await firstSummary.locator("dt").count(), 3);
  assert.equal(await firstSummary.getByText("资讯提及：未知", { exact: true }).count(), 0);
  assert.match(await page.getByTestId("discovery-queue-boundary").innerText(), /仅筛选本次候选队列，每策略最多12条，同优先级顺序非价值排名/);
  await firstCard.getByRole("link", { name: "进入候选研究" }).waitFor();
  assert.match(await page.getByTestId("strategy-SWING").innerText(), /波段/);
  assert.equal(await page.getByTestId("full-market-tab").innerText(), "全市场筛选");
  const diagnostics = page.getByTestId("discovery-diagnostics");
  assert.equal(await diagnostics.getAttribute("open"), null);
  assert.equal(await page.getByTestId("discovery-evidence-600519").getAttribute("open"), null);
  assert.equal(await firstCard.getByText("CATALYST_DISCLOSED", { exact: true }).isVisible(), false);
  await firstCard.getByText("完整依据与来源", { exact: true }).click();
  await firstCard.getByText("资讯提及：未知", { exact: true }).waitFor();
  await firstCard.getByText("CATALYST_DISCLOSED", { exact: true }).waitFor();
  await firstCard.getByText("完整依据与来源", { exact: true }).click();
  await diagnostics.locator("summary").click();
  await diagnostics.getByText("扫描股票池", { exact: true }).waitFor();
  await diagnostics.getByText("market-snapshot", { exact: true }).waitFor();
  await diagnostics.locator("summary").click();

  // Results precede diagnostics on desktop and narrow screens; collapsed details do not hide the research entry.
  const screenshots = process.env.DISCOVERY_SCREENSHOT_DIR;
  if (screenshots) mkdirSync(screenshots, { recursive: true });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 568, height: 698 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.getByRole("main").evaluate((element) => element.scrollTo(0, 0));
    const firstBounds = await firstCard.boundingBox();
    const diagnosticsBounds = await diagnostics.boundingBox();
    assert.ok(firstBounds && diagnosticsBounds && firstBounds.y < diagnosticsBounds.y, "candidates must precede diagnostics");
    assert.ok(firstBounds.y >= 0 && firstBounds.y < viewport.height, `first candidate must enter the initial viewport at ${viewport.width}px`);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `no page horizontal overflow at ${viewport.width}px`);
    assert.ok(await page.getByRole("main").evaluate((element) => element.scrollWidth <= element.clientWidth), `no content horizontal overflow at ${viewport.width}px`);
    if (screenshots) await page.screenshot({ path: path.join(screenshots, `discovery-${viewport.width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });

  // All existing filters operate on the same queue without changing its backend ordering.
  await page.getByLabel("发现行业或主题").selectOption("消费");
  await page.getByTestId("discovery-item-SWING-600221").waitFor({ state: "detached" });
  assert.equal(await page.getByTestId("discovery-item-SWING-600221").count(), 0);
  await page.getByLabel("发现行业或主题").selectOption("ALL");
  await page.getByTestId("discovery-item-SWING-600221").waitFor();
  await page.getByLabel("研究优先级", { exact: true }).selectOption("LOW");
  await firstCard.waitFor({ state: "detached" });
  assert.equal(await firstCard.count(), 0);
  await page.getByLabel("研究优先级", { exact: true }).selectOption("ALL");
  await firstCard.waitFor();
  const discoveryText = await workspace.innerText();
  assert.doesNotMatch(discoveryText, /\bBUY\b|Opportunity Score|综合评分/);
  assert.equal(await page.locator('[data-testid*="market-cloud"], [data-testid*="market-intel"]').count(), 0);
  assert.doesNotMatch(discoveryText, /Market Cloud|市场情报/);

  // C: Restricted items remain discoverable but visibly carry stricter, research-only semantics.
  await page.getByLabel("研究资格", { exact: true }).selectOption("RESTRICTED");
  const restrictedCard = page.getByTestId("discovery-item-SWING-600221");
  await restrictedCard.waitFor();
  await page.getByTestId("discovery-gaps-600221").getByText("受限研究：需要进一步核对资格", { exact: true }).waitFor();
  assert.equal(await page.getByTestId("discovery-gaps-600221").getByText("财务报告期与时效尚未确认", { exact: true }).count(), 0);
  assert.equal(await page.getByTestId("discovery-evidence-600221").getAttribute("open"), null);
  await restrictedCard.getByText("完整依据与来源", { exact: true }).click();
  await page.getByTestId("discovery-evidence-600221").getByText("财务报告期与时效尚未确认", { exact: true }).waitFor();
  await restrictedCard.getByText("RESTRICTED_RESEARCH_ONLY", { exact: true }).waitFor();
  await restrictedCard.getByText("完整依据与来源", { exact: true }).click();
  assert.equal(await page.getByTestId("discovery-item-SWING-600519").count(), 0);
  await page.getByLabel("研究资格", { exact: true }).selectOption("ALL");

  // D: strategy queues differ; there is no unified score forcing one common ranking.
  await page.getByTestId("strategy-SHORT").click();
  const shortCard = page.getByTestId("discovery-item-SHORT-000001");
  await shortCard.waitFor();
  const shortSummary = page.getByTestId("discovery-summary-observations-000001");
  assert.equal(await shortSummary.locator("div").filter({ hasText: "当日价格动量为正" }).locator("dd").innerText(), "+2.50%");
  assert.equal(await shortSummary.locator("div").filter({ hasText: "换手率位于活跃区间" }).locator("dd").innerText(), "+8.25%");
  assert.equal(await page.getByTestId("discovery-item-MEDIUM-300750").count(), 0);
  await page.getByTestId("strategy-MEDIUM").click();
  const mediumCard = page.getByTestId("discovery-item-MEDIUM-300750");
  await mediumCard.waitFor();
  const mediumSummary = page.getByTestId("discovery-summary-observations-300750");
  assert.equal(await mediumSummary.locator("div").filter({ hasText: "60 日收益为正" }).locator("dd").innerText(), "+25.00%");
  await mediumSummary.getByText("市盈率（TTM）：18.50 倍", { exact: true }).waitFor();
  await mediumSummary.getByText("市净率：未知", { exact: true }).waitFor();
  await mediumSummary.getByText("营收同比：+12.50%", { exact: true }).waitFor();
  await mediumSummary.getByText("经营现金流：-2.50 亿元", { exact: true }).waitFor();
  await mediumSummary.getByText("净资产收益率：未知", { exact: true }).waitFor();
  await mediumCard.getByText("完整依据与来源", { exact: true }).click();
  assert.equal(await page.getByTestId("discovery-evidence-300750").locator("dl > div").filter({ hasText: "原始观察值" }).locator("dd").first().innerText(), "0.123456");
  assert.equal(await page.getByTestId("discovery-item-SHORT-000001").count(), 0);
  await page.getByTestId("strategy-SWING").click();

  // URL is the single source of filter/mode state: refresh, history and mode toggle retain it.
  const persisted = new URLSearchParams({ mode: "discovery", strategy: "SWING", sector: "交通运输", priority: "LOW", restricted: "RESTRICTED", health: "normal" });
  await page.goto(`http://127.0.0.1:${port}/screener?${persisted}#discovery-item-SWING-600221`, { waitUntil: "networkidle" });
  await restrictedCard.waitFor();
  await page.reload({ waitUntil: "networkidle" });
  await restrictedCard.waitFor();
  assert.equal(await page.getByLabel("发现行业或主题").inputValue(), "交通运输");
  assert.equal(await page.getByLabel("研究优先级", { exact: true }).inputValue(), "LOW");
  assert.equal(await page.getByLabel("研究资格", { exact: true }).inputValue(), "RESTRICTED");
  assert.equal(await page.getByLabel("发现数据状态", { exact: true }).inputValue(), "normal");
  assert.equal(await page.getByTestId("strategy-SWING").getAttribute("aria-selected"), "true");
  assert.equal(await restrictedCard.getAttribute("data-return-selected"), "true");
  await page.getByTestId("strategy-MEDIUM").click();
  await page.getByTestId("discovery-open-full-market").waitFor();
  await page.goBack();
  await restrictedCard.waitFor();
  assert.equal(await page.getByTestId("strategy-SWING").getAttribute("aria-selected"), "true");
  await page.goForward();
  await page.getByTestId("discovery-open-full-market").waitFor();
  assert.equal(await page.getByTestId("strategy-MEDIUM").getAttribute("aria-selected"), "true");
  await page.getByTestId("discovery-open-full-market").click();
  await page.locator('[data-testid="full-market-tab"][aria-selected="true"]').waitFor();
  assert.equal(await page.getByTestId("full-market-tab").getAttribute("aria-selected"), "true");
  await page.reload({ waitUntil: "networkidle" });
  assert.equal(await page.getByTestId("full-market-tab").getAttribute("aria-selected"), "true");
  assert.equal(new URL(page.url()).searchParams.get("sector"), "交通运输");
  await page.getByTestId("discovery-tab").click();
  await page.getByTestId("discovery-open-full-market").waitFor();
  assert.equal(await page.getByTestId("strategy-MEDIUM").getAttribute("aria-selected"), "true");
  assert.equal(await page.getByLabel("研究优先级", { exact: true }).inputValue(), "LOW");
  await page.goto(`http://127.0.0.1:${port}/screener`, { waitUntil: "networkidle" });
  await firstCard.waitFor();

  // Light and dark both keep the same Discovery workspace mounted.
  assert.equal(await page.locator("html").evaluate((element) => element.classList.contains("dark")), true);
  await page.getByRole("button", { name: /亮色模式|切换到亮色主题/ }).click();
  assert.equal(await page.locator("html").evaluate((element) => element.classList.contains("light")), true);
  await page.getByRole("button", { name: /暗色模式|切换到暗色主题/ }).click();
  assert.equal(await page.locator("html").evaluate((element) => element.classList.contains("dark")), true);

  // B: one failed provider produces PARTIAL/UNKNOWN, not a blank page or a fabricated HIGH opportunity.
  const partialResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/screener/discovery" && new URL(response.url()).searchParams.get("refresh") === "true");
  await page.getByTestId("refresh-discovery").click();
  assert.equal((await partialResponse).status(), 200);
  await page.getByTestId("discovery-summary").getByText("部分可用", { exact: true }).first().waitFor();
  const unknownCard = page.getByTestId("discovery-item-SWING-300012");
  await unknownCard.waitFor();
  const unknownGaps = page.getByTestId("discovery-gaps-300012");
  await unknownGaps.getByText("数据状态：未知", { exact: true }).waitFor();
  assert.equal(await unknownGaps.getByText("财务事实缺失", { exact: true }).count(), 0);
  assert.equal(await page.getByTestId("discovery-evidence-300012").getAttribute("open"), null);
  await unknownCard.getByText("完整依据与来源", { exact: true }).click();
  await page.getByTestId("discovery-evidence-300012").getByText("基本面：未知", { exact: true }).waitFor();
  await page.getByTestId("discovery-evidence-300012").getByText("财务事实缺失", { exact: true }).waitFor();
  await unknownCard.getByText("完整依据与来源", { exact: true }).click();
  assert.equal((await unknownCard.getByText("研究优先级：高", { exact: true }).count()), 0);
  await page.getByTestId("discovery-source-warning").getByText("行业背景：不可用", { exact: true }).waitFor();
  assert.equal(await diagnostics.getAttribute("open"), null);
  await page.getByLabel("发现数据状态", { exact: true }).selectOption("unknown");
  await firstCard.waitFor({ state: "detached" });
  assert.equal(await firstCard.count(), 0);
  await unknownCard.waitFor();
  await page.getByLabel("发现数据状态", { exact: true }).selectOption("ALL");
  await page.getByTestId("discovery-item-SWING-600519").waitFor();

  // Failed refresh keeps the successful snapshot timestamp and labels the separate attempt time.
  const staleResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/screener/discovery" && new URL(response.url()).searchParams.get("refresh") === "true");
  await page.getByTestId("refresh-discovery").click();
  assert.equal((await staleResponse).status(), 200);
  await page.getByTestId("discovery-summary").getByText("历史结果", { exact: true }).waitFor();
  const staleSummary = await page.getByTestId("discovery-summary").innerText();
  assert.match(staleSummary, /最后成功更新于 2026-08-30 11:00/);
  assert.match(staleSummary, /刷新失败于 2026-08-30 12:00/);
  assert.doesNotMatch(staleSummary, /抓取于 2026-08-30 12:00/);

  if (screenshots) {
    await page.getByRole("main").evaluate((element) => element.scrollTo(0, 0));
    await page.screenshot({ path: path.join(screenshots, "discovery-stale.png"), fullPage: true });
    await unknownCard.screenshot({ path: path.join(screenshots, "discovery-unknown-card.png") });
  }

  // E: explicit handoff preserves identity and loads P1 Candidate without creating formal state.
  await page.getByLabel("发现行业或主题").selectOption("消费");
  await page.getByLabel("研究优先级", { exact: true }).selectOption("HIGH");
  await page.getByLabel("研究资格", { exact: true }).selectOption("CLEAR");
  await page.getByLabel("发现数据状态", { exact: true }).selectOption("normal");
  const candidateHref = await page.getByTestId("discovery-candidate-600519").getAttribute("href");
  const handoff = new URL(candidateHref, page.url());
  assert.deepEqual([...handoff.searchParams.keys()].sort(), ["return_to", "source", "strategy"]);
  assert.equal(handoff.searchParams.get("source"), "discovery");
  assert.equal(handoff.searchParams.get("strategy"), "SWING");
  const returnTo = handoff.searchParams.get("return_to");
  assert.equal(new URL(returnTo, page.url()).hash, "#discovery-item-SWING-600519");
  await page.getByTestId("discovery-candidate-600519").click();
  await page.waitForURL((url) => url.pathname === "/candidates/600519");
  const candidate = page.getByTestId("candidate-workspace");
  await candidate.waitFor();
  assert.equal(await candidate.getAttribute("data-security-code"), "600519");
  await candidate.locator('[data-position-state="NOT_HELD"]').waitFor();
  await candidate.getByTestId("candidate-campaign-panel").getByText("暂无候选投资计划", { exact: true }).waitFor();
  assert.equal(await page.getByTestId("candidate-stock-data-entry").getAttribute("href"), returnTo);
  await page.goBack();
  await firstCard.waitFor();
  assert.equal(await firstCard.getAttribute("data-return-selected"), "true");
  await page.goForward();
  await candidate.waitFor();
  await page.getByTestId("candidate-stock-data-entry").click();
  await firstCard.waitFor();
  assert.equal(await page.getByLabel("发现行业或主题").inputValue(), "消费");
  assert.equal(await page.getByLabel("研究优先级", { exact: true }).inputValue(), "HIGH");
  assert.equal(await page.getByLabel("研究资格", { exact: true }).inputValue(), "CLEAR");
  assert.equal(await page.getByLabel("发现数据状态", { exact: true }).inputValue(), "normal");
  await page.waitForFunction(() => {
    const card = document.getElementById("discovery-item-SWING-600519");
    const bounds = card?.getBoundingClientRect();
    return bounds && document.activeElement === card && bounds.top < innerHeight && bounds.bottom > 0;
  });
  assert.equal(await firstCard.getAttribute("data-return-selected"), "true");
  assert.equal(
    apiRequests.filter(({ method, pathname }) => method !== "GET" && ["/api/campaigns", "/api/evidence", "/api/thesis"].includes(pathname)).length,
    0,
    "Discovery handoff must not auto-create Campaign, Evidence, or Thesis state",
  );
  assert.deepEqual(browserErrors, []);
  console.log("NORTH-STAR-P2 Discovery browser A-E vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
