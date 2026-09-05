import assert from "node:assert/strict";
import { createReadStream, existsSync } from "node:fs";
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
      { code: "RETURN_20D", label: "20 日相对表现", value: 0.12, source_ref: "rdp:fixture" },
      { code: "DISCLOSURE", label: "近期公告线索", value: "AVAILABLE", source_ref: "announcement:fixture" },
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
  uncertainties: ["Restricted Universe 需要 Candidate Gate 继续约束"],
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
  await page.getByTestId("discovery-item-SWING-600519").getByText("CATALYST_DISCLOSED", { exact: true }).waitFor();
  const discoveryText = await workspace.innerText();
  assert.doesNotMatch(discoveryText, /\bBUY\b|Opportunity Score|综合评分/);
  assert.equal(await page.locator('[data-testid*="market-cloud"], [data-testid*="market-intel"]').count(), 0);
  assert.doesNotMatch(discoveryText, /Market Cloud|市场情报/);

  // C: Restricted items remain discoverable but visibly carry stricter, research-only semantics.
  await page.getByLabel("Discovery restricted").selectOption("RESTRICTED");
  const restrictedCard = page.getByTestId("discovery-item-SWING-600221");
  await restrictedCard.waitFor();
  await restrictedCard.getByText("Restricted", { exact: true }).waitFor();
  await restrictedCard.getByText("RESTRICTED_RESEARCH_ONLY", { exact: true }).waitFor();
  assert.equal(await page.getByTestId("discovery-item-SWING-600519").count(), 0);
  await page.getByLabel("Discovery restricted").selectOption("ALL");

  // D: strategy queues differ; there is no unified score forcing one common ranking.
  await page.getByTestId("strategy-SHORT").click();
  await page.getByTestId("discovery-item-SHORT-000001").waitFor();
  assert.equal(await page.getByTestId("discovery-item-MEDIUM-300750").count(), 0);
  await page.getByTestId("strategy-MEDIUM").click();
  await page.getByTestId("discovery-item-MEDIUM-300750").waitFor();
  assert.equal(await page.getByTestId("discovery-item-SHORT-000001").count(), 0);
  await page.getByTestId("strategy-SWING").click();

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
  await unknownCard.getByText("UNKNOWN", { exact: true }).first().waitFor();
  await unknownCard.getByText("未知", { exact: true }).waitFor();
  assert.equal((await unknownCard.getByText("HIGH 优先", { exact: true }).count()), 0);
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

  // E: explicit handoff preserves identity and loads P1 Candidate without creating formal state.
  await page.getByTestId("discovery-candidate-600519").click();
  await page.waitForURL(/\/candidates\/600519$/);
  const candidate = page.getByTestId("candidate-workspace");
  await candidate.waitFor();
  assert.equal(await candidate.getAttribute("data-security-code"), "600519");
  await candidate.locator('[data-position-state="NOT_HELD"]').waitFor();
  await candidate.getByTestId("candidate-campaign-panel").getByText("暂无候选投资计划", { exact: true }).waitFor();
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
