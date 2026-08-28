/**
 * Top Risk Analysis E2E — pure frontend + Playwright page.route mocks.
 *
 * Architecture:
 * - Playwright loads the Vite build from a Node static server (frontend/dist only)
 * - ALL /api/* traffic is intercepted via page.route (NO real market data backend)
 * - Covers normal / partial / unavailable envelopes, error handling, race guards,
 *   decision_run_id navigation
 */
import { chromium } from "playwright";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

let frontendPort = 0;
let browserLabel = "unknown";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      /* retry */
    }
    await sleep(400);
  }
  throw new Error(`timeout waiting ${url}`);
}

function startStaticServer(dir) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  };

  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    if (rawUrl.startsWith("/api/")) {
      res.writeHead(404, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ detail: "use page.route mocks" }));
      return;
    }

    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || (existsSync(target) && path.extname(target) === "")) {
      target = path.join(dir, "index.html");
    }
    const ext = path.extname(target);
    const type = mime[ext] || "application/octet-stream";
    res.setHeader("Content-Type", type);
    createReadStream(target).pipe(res);
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (typeof address !== "object" || !address) {
        server.close();
        reject(new Error("static server did not expose a TCP port"));
        return;
      }
      resolve({ server, port: address.port });
    });
  });
}

async function launchBrowser() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  const launchOpts = {
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  };
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const b = await chromium.launch(launchOpts);
      browserLabel = `local chromium-${b.version()}`;
      return b;
    } catch (error) {
      lastError = error;
      if (attempt === 0) {
        launchOpts.channel = "chrome";
      }
    }
  }
  throw lastError || new Error("failed to launch any Chromium");
}

function stockName(code) {
  if (code === "000001") return "平安银行";
  if (code === "000002") return "万科A";
  return `测试股${code}`;
}

function valuationPayload(code) {
  return {
    name: stockName(code),
    code,
    price: code === "000001" ? 11.5 : 8.2,
    mcap_yi: code === "000001" ? 2200 : 950,
    pe_ttm: 5.2,
    pb: 0.65,
    eps_26e: 1.8,
    eps_27e: 2.0,
    pe_26e: 6.4,
    cagr_pct: 12,
    peg: 0.43,
    digest_years: 3.1,
    analyst_count: 18,
  };
}

function jsonOk(body) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data: body }),
  };
}

function jsonErr(status, detail) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify({ detail }),
  };
}

function technicalIndicatorsEnvelope(code) {
  return {
    schema_version: "technical-indicators-v0.1",
    code,
    period: "daily",
    trade_date: "2026-07-29",
    fetched_at: "2026-07-30T09:30:12.123456Z",
    status: "normal",
    warnings: [],
    limitations: [],
    latest: {
      sma5: 11.2, sma10: 11.1, sma20: 11.0, sma60: 10.8,
      ema12: 11.15, ema26: 10.95,
      macd_dif: 0.12, macd_dea: 0.08, macd_histogram: 0.08,
      rsi14: 55.0,
      bollinger_upper: 11.5, bollinger_middle: 11.0, bollinger_lower: 10.5,
      volume_ratio_5_20: 1.2,
    },
    triggers: [],
    series: [],
  };
}

function nativeIntelUnavailableEnvelope(code) {
  return {
    status: "unavailable",
    error: "Native Intel 暂不可用",
    window_hours: 168,
    security: { code, company_name: stockName(code) },
    mapping: {
      status: "EXACT_CODE_ONLY",
      term_count: 1,
      terms: [{ term: code, term_kind: "security_code", source_ref: "user_query_exact" }],
      errors: [],
    },
    observation: { items: [], item_count: 0 },
  };
}

/**
 * Build a realistic normal top risk envelope.
 */
function topRiskNormalEnvelope(code) {
  const name = stockName(code);
  const riskScore = code === "000002" ? 82 : 45;
  return {
    schema_version: "top-risk-analysis-v0.1",
    source: "Vibe-Research top-risk engine",
    source_tier: "reference",
    code,
    name,
    trade_date: "2026-07-29",
    fetched_at: "2026-07-30T09:30:12.123456Z",
    status: "normal",
    is_stale: false,
    risk_score: riskScore,
    confidence: 75,
    coverage: { completed: 3, total: 3, ratio: 1.0 },
    signal: "unknown",
    signal_eligible: false,
    config_hash: "cfg_abc123",
    input_fingerprint: "inp_def456",
    decision_run_id: "tr_abc1234567890def",
    trace_archive_status: "archived",
    warnings: [],
    limitations: [],
    data: {
      name,
      completed_steps: 3,
      total_steps: 3,
      risk_drivers: ["拥挤度"],
      safety_signals: [],
      narrative: `${name}（${code}）顶部风险分数 ${riskScore}/100；主要风险：拥挤度。`,
    },
    trace: [
      {
        step_id: "crowding",
        label: "拥挤度",
        direction: "RISK",
        weight: 1.0,
        step_risk: 0.45,
        confidence: 75,
        skipped: false,
        skip_reason: null,
        reasons: ["近期量能放大"],
        details: { turnover_z: 2.1 },
      },
    ],
  };
}

function topRiskPartialEnvelope(code) {
  return {
    ...topRiskNormalEnvelope(code),
    status: "partial",
    is_stale: false,
    risk_score: 30,
    confidence: 60,
    coverage: { completed: 2, total: 3, ratio: 0.67 },
    limitations: [
      { field: "valuation", reason_code: "SOURCE_PARTIAL", detail: "估值分位无数据" },
    ],
    trace: [],
  };
}

function topRiskUnavailableEnvelope(code) {
  return {
    schema_version: "top-risk-analysis-v0.1",
    source: "Vibe-Research top-risk engine",
    source_tier: "reference",
    code,
    name: stockName(code),
    trade_date: null,
    fetched_at: "2026-07-30T09:30:12.123456Z",
    status: "unavailable",
    is_stale: true,
    risk_score: null,
    confidence: null,
    coverage: { completed: 0, total: 0, ratio: 0.0 },
    signal: "unknown",
    signal_eligible: false,
    config_hash: null,
    input_fingerprint: null,
    decision_run_id: null,
    trace_archive_status: "skipped",
    warnings: [],
    limitations: [
      { field: "price_history", reason_code: "SOURCE_UNAVAILABLE", detail: "核心行情数据当前不可用。" },
    ],
    data: null,
    trace: [],
  };
}

function topRiskNullEnvelope(code) {
  return {
    ...topRiskNormalEnvelope(code),
    risk_score: null,
    confidence: null,
    coverage: null,
    decision_run_id: null,
    data: null,
    trace: [],
  };
}

/**
 * Controllable mock state for top-risk scenarios.
 */
function createApiMockController() {
  const state = {
    topRiskMode: "normal", // normal | partial | unavailable | null | error
    topRiskHolds: new Map(),
    topRiskCalls: [],
    valuationCalls: [],
    klineCalls: [],
    objectEndpointCalls: [],
    expectedHttpErrors: [],
    unexpectedHttpResponses: [],
    unexpectedApiCalls: [],
  };

  async function handleTopRisk(route) {
    const request = route.request();
    const url = request.url();
    const code = new URL(url).searchParams.get("code") || "000001";
    const mode = state.topRiskMode;
    const call = { code, mode, url, ts: Date.now(), held: false, fulfilled: false };
    state.topRiskCalls.push(call);

    if (mode === "error") {
      const expectedHttpError = {
        code,
        url,
        status: 502,
        responseObserved: false,
        consoleObserved: false,
        closed: false,
      };
      state.expectedHttpErrors.push(expectedHttpError);
      await route.fulfill(jsonErr(502, "模拟顶部风险失败"));
      call.fulfilled = true;
      return;
    }

    const hold = state.topRiskHolds.get(code);
    if (hold && !hold.released) {
      call.held = true;
      hold.started = true;
      await new Promise((resolve) => {
        hold.release = () => {
          if (hold.released) return;
          hold.released = true;
          resolve();
        };
      });
    }

    let body;
    switch (mode) {
      case "partial":
        body = topRiskPartialEnvelope(code);
        break;
      case "unavailable":
        body = topRiskUnavailableEnvelope(code);
        break;
      case "null":
        body = topRiskNullEnvelope(code);
        break;
      case "normal":
      default:
        body = topRiskNormalEnvelope(code);
        break;
    }
    await route.fulfill(jsonOk(body));
    call.fulfilled = true;
    if (state.topRiskHolds.get(code) === hold) {
      state.topRiskHolds.delete(code);
    }
  }

  async function handle(route) {
    const request = route.request();
    const url = request.url();
    if (!url.includes("/api/")) {
      await route.continue();
      return;
    }

    const pathname = new URL(url).pathname;

    // Top risk endpoint: explicit mock
    if (pathname === "/api/market/top-risk") {
      await handleTopRisk(route);
      return;
    }

    // Native Intel failure is isolated from this unrelated StockData path.
    if (pathname.startsWith("/api/native-intel/security-context/")) {
      const code = pathname.split("/").pop() || "000001";
      await route.fulfill(jsonOk(nativeIntelUnavailableEnvelope(code)));
      return;
    }

    // Candidate Research is mounted on StockData and reads the existing Campaign
    // list contract even when this smoke scenario is focused on top risk.
    if (pathname === "/api/campaigns" && request.method() === "GET") {
      const code = new URL(url).searchParams.get("security_code");
      if (!/^\d{6}$/.test(code || "")) {
        await route.fulfill(jsonErr(400, "invalid security_code"));
        return;
      }
      await route.fulfill(jsonOk([]));
      return;
    }

    // StockData also requests technical indicators; keep this unrelated panel
    // explicit so the top-risk E2E remains fully mocked after integration.
    if (pathname === "/api/market/technical-indicators") {
      const code = new URL(url).searchParams.get("code") || "000001";
      await route.fulfill(jsonOk(technicalIndicatorsEnvelope(code)));
      return;
    }

    // K-line mock
    if (pathname === "/api/kline" || pathname.endsWith("/kline")) {
      state.klineCalls.push({ url, ts: Date.now() });
      await route.fulfill(jsonOk([
        { date: "2026-07-20", open: 11, close: 11.5, high: 11.6, low: 10.9, volume: 1000000, amount: 1e8 },
        { date: "2026-07-21", open: 11.5, close: 11.3, high: 11.7, low: 11.2, volume: 1100000, amount: 1.1e8 },
      ]));
      return;
    }

    // Mock valuation (provides the complete Valuation contract for the stock header)
    if (pathname === "/api/valuation" || pathname.endsWith("/valuation")) {
      state.valuationCalls.push({ url, ts: Date.now() });
      const code = new URL(url).searchParams.get("code") || "000001";
      await route.fulfill(jsonOk(valuationPayload(code)));
      return;
    }

    // Valuation percentile mock
    if (pathname === "/api/valuation/percentile" || pathname.endsWith("/valuation/percentile")) {
      state.valuationCalls.push({ url, ts: Date.now() });
      await route.fulfill(jsonOk({
        period: "近5年",
        metrics: {
          pe_ttm: { current: 5.2, percentile: 25, min: 3, max: 12, p20: 4, p50: 6, p80: 9, n: 1200 },
          pb: { current: 0.65, percentile: 30, min: 0.4, max: 1.5, p20: 0.5, p50: 0.8, p80: 1.1, n: 1200 },
        },
      }));
      return;
    }

    // Object endpoints must mirror their real empty response contracts. Returning
    // [] here is invalid and crashes StockData when it reads nested array lengths.
    if (pathname === "/api/dragon-tiger") {
      const call = { pathname, fulfilled: false };
      state.objectEndpointCalls.push(call);
      await route.fulfill(jsonOk({
        records: [],
        seats: { buy: [], sell: [] },
        institution: { buy_amt: 0, sell_amt: 0, net_amt: 0 },
      }));
      call.fulfilled = true;
      return;
    }
    if (pathname === "/api/lockup") {
      const call = { pathname, fulfilled: false };
      state.objectEndpointCalls.push(call);
      await route.fulfill(jsonOk({ history: [], upcoming: [] }));
      call.fulfilled = true;
      return;
    }
    if (pathname === "/api/blocks") {
      const call = { pathname, fulfilled: false };
      state.objectEndpointCalls.push(call);
      await route.fulfill(jsonOk({ total: 0, boards: [], concept_tags: [] }));
      call.fulfilled = true;
      return;
    }

    // Reports mock (array)
    if (pathname.includes("/reports")) {
      const code = new URL(url).searchParams.get("code") || "000001";
      await route.fulfill(jsonOk([{ title: `${stockName(code)}深度报告`, publishDate: "2026-07-01", orgSName: "测试证券", emRatingName: "增持" }]));
      return;
    }

    // Announcements / financials mocks (array/object)
    if (pathname.includes("/announcements")) {
      await route.fulfill(jsonOk([{ date: "2026-07-10", title: "董事会决议公告", type: "告", url: "" }]));
      return;
    }
    if (pathname.includes("/financials")) {
      await route.fulfill(jsonOk({ period: "2025Q4", revenue: "1000亿", revenue_yoy: "8%", net_profit: "200亿", net_profit_yoy: "10%", eps: "1.50", bvps: "15.0", roe: "12%", gross_margin: "40%", net_margin: "20%", op_cf_ps: "2.1" }));
      return;
    }

    // Auto-fired collection endpoints share an array contract.
    if (
      pathname === "/api/news"
      || pathname === "/api/margin"
      || pathname === "/api/block-trade"
      || pathname === "/api/holders"
      || pathname === "/api/dividend"
      || pathname === "/api/fund-flow"
      || pathname === "/api/hot-concepts"
      || pathname === "/api/investor-qa"
    ) {
      await route.fulfill(jsonOk([]));
      return;
    }

    state.unexpectedApiCalls.push(url);
    await route.fulfill(jsonErr(501, `未配置 E2E mock: ${pathname}`));
  }

  function setTopRiskMode(mode) {
    state.topRiskMode = mode;
  }

  function recordResponse(response) {
    const url = response.url();
    if (!url.includes("/api/")) return;
    const status = response.status();
    const expected = state.expectedHttpErrors.find((entry) =>
      !entry.closed
      && !entry.responseObserved
      && entry.url === url
      && entry.status === status
    );
    if (expected) {
      expected.responseObserved = true;
      return;
    }
    if (status >= 400) {
      state.unexpectedHttpResponses.push({ url, status });
    }
  }

  function consumeExpectedConsoleError(text) {
    const match = /^Failed to load resource: the server responded with a status of (\d+)(?: \([^)]*\))?$/.exec(text);
    if (!match) return false;
    const status = Number(match[1]);
    const expected = state.expectedHttpErrors.find((entry) =>
      !entry.closed
      && entry.responseObserved
      && !entry.consoleObserved
      && entry.status === status
      && new URL(entry.url).pathname === "/api/market/top-risk"
    );
    if (!expected) return false;
    expected.consoleObserved = true;
    expected.consoleText = text;
    return true;
  }

  function armTopRiskHold(code) {
    if (state.topRiskHolds.has(code)) {
      throw new Error(`top-risk hold already armed for ${code}`);
    }
    state.topRiskHolds.set(code, { code, started: false, released: false, release: null });
  }

  function releaseTopRiskHold(code) {
    const hold = state.topRiskHolds.get(code);
    if (!hold || !hold.started || typeof hold.release !== "function") {
      throw new Error(`top-risk hold is not active for ${code}`);
    }
    hold.release();
  }

  function clearTopRiskHolds() {
    for (const hold of state.topRiskHolds.values()) {
      if (typeof hold.release === "function") hold.release();
    }
    state.topRiskHolds.clear();
  }

  function closeExpectedHttpError(code) {
    const expected = state.expectedHttpErrors.find((entry) =>
      !entry.closed && entry.code === code && entry.responseObserved && entry.consoleObserved
    );
    if (!expected) return null;
    expected.closed = true;
    return expected;
  }

  return {
    state,
    handle,
    recordResponse,
    consumeExpectedConsoleError,
    setTopRiskMode,
    armTopRiskHold,
    releaseTopRiskHold,
    clearTopRiskHolds,
    closeExpectedHttpError,
    resetTopRiskCalls() {
      state.topRiskCalls = [];
    },
  };
}

async function fillCode(page, code) {
  const input = page.locator('input[placeholder*="A 股"]').first();
  await input.click({ clickCount: 3 });
  await input.fill(code);
}

async function clickQuery(page) {
  await page.getByRole("button", { name: "查询" }).click();
}

async function waitForStockHeader(page, code, name) {
  await page.getByRole("heading", { name }).waitFor({ state: "visible", timeout: 15000 });
  await page.getByText(code, { exact: true }).first().waitFor({ state: "visible", timeout: 10000 });
}

function topRiskCard(page) {
  return page.locator(".card-surface").filter({
    has: page.getByRole("heading", { name: /顶部风险分析/ }),
  }).first();
}

function stockDataCard(page, name) {
  return page.locator(".card-surface").filter({
    has: page.getByRole("heading", { name, exact: true }),
  }).first();
}

function metricCell(card, label) {
  return card.getByText(label, { exact: true }).locator("..");
}

async function expectMetricValue(card, metricLabel, expectedValue, label, errors) {
  const cell = metricCell(card, metricLabel);
  if (!await expectVisible(cell, `${label}: ${metricLabel} metric cell missing`, errors)) return false;
  const value = cell.locator("p").nth(1);
  if (!await expectVisible(value, `${label}: ${metricLabel} value missing`, errors)) return false;
  const actual = (await value.innerText()).trim();
  if (actual !== expectedValue) {
    errors.push(`${label}: ${metricLabel} expected ${expectedValue}, got ${actual}`);
    return false;
  }
  return true;
}

async function assertMainStockData(page, { name, price, peTtm }, label, errors) {
  await expectVisible(
    page.getByRole("heading", { name, exact: true }),
    `${label}: stock title ${name} missing`,
    errors,
  );
  const card = stockDataCard(page, name);
  await expectMetricValue(card, "现价", price, label, errors);
  await expectMetricValue(card, "PE(TTM)", peTtm, label, errors);
}

async function expectNoErrorBoundary(page, label, errors) {
  const retryButtons = page.getByRole("button", { name: /重试重新挂载|重新加载页面/ });
  const count = await retryButtons.count();
  const visibleIndexes = [];
  for (let index = 0; index < count; index++) {
    if (await retryButtons.nth(index).isVisible()) {
      visibleIndexes.push(index);
    }
  }
  if (visibleIndexes.length > 0) {
    errors.push(`${label}: error boundary buttons visible at indexes ${visibleIndexes.join(", ")}`);
    return false;
  }
  return true;
}

async function waitForDomToSettle(locator, label, errors, quietMs = 400, timeoutMs = 4000) {
  const result = await locator.evaluate(
    (element, options) => new Promise((resolve) => {
      let mutations = 0;
      let quietTimer;
      let timeoutTimer;
      let finished = false;
      const observer = new MutationObserver(() => {
        mutations += 1;
        clearTimeout(quietTimer);
        quietTimer = setTimeout(() => finish(true), options.quietMs);
      });
      const finish = (settled) => {
        if (finished) return;
        finished = true;
        observer.disconnect();
        clearTimeout(quietTimer);
        clearTimeout(timeoutTimer);
        resolve({ settled, mutations, text: element.innerText });
      };
      observer.observe(element, { childList: true, characterData: true, subtree: true });
      quietTimer = setTimeout(() => finish(true), options.quietMs);
      timeoutTimer = setTimeout(() => finish(false), options.timeoutMs);
    }),
    { quietMs, timeoutMs },
  );
  if (!result.settled) {
    errors.push(`${label}: DOM did not settle within ${timeoutMs}ms (${result.mutations} mutations)`);
    return false;
  }
  return true;
}

async function observeDomTextWindow(
  locator,
  { durationMs = 750, requiredTexts = [], forbiddenTexts = [] },
  label,
  errors,
) {
  const result = await locator.evaluate(
    (element, options) => new Promise((resolve) => {
      const snapshots = [element.innerText];
      const observer = new MutationObserver(() => snapshots.push(element.innerText));
      observer.observe(element, { childList: true, characterData: true, subtree: true });
      setTimeout(() => {
        observer.disconnect();
        snapshots.push(element.innerText);
        resolve({ snapshots });
      }, options.durationMs);
    }),
    { durationMs },
  );

  for (const [index, snapshot] of result.snapshots.entries()) {
    for (const required of requiredTexts) {
      if (!snapshot.includes(required)) {
        errors.push(`${label}: required text disappeared during DOM window at snapshot ${index}: ${required}`);
        return false;
      }
    }
    for (const forbidden of forbiddenTexts) {
      if (snapshot.includes(forbidden)) {
        errors.push(`${label}: stale text appeared during DOM window at snapshot ${index}: ${forbidden}`);
        return false;
      }
    }
  }
  return true;
}

async function expectVisible(locator, label, errors, timeout = 8000) {
  try {
    await locator.waitFor({ state: "visible", timeout });
    return true;
  } catch (error) {
    errors.push(`${label}: ${error.message}`);
    return false;
  }
}

async function waitUntil(predicate, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return true;
    await sleep(30);
  }
  return false;
}

async function queryStock(page, code, name, label, errors) {
  await page.goto(`http://127.0.0.1:${frontendPort}/stock-data`, {
    waitUntil: "domcontentloaded",
  });
  if (!await expectVisible(
    page.getByRole("heading", { name: "个股数据" }),
    `${label}: page title not visible`,
    errors,
    15000,
  )) return false;

  await fillCode(page, code);
  await clickQuery(page);
  try {
    await waitForStockHeader(page, code, name);
    return true;
  } catch (error) {
    const bodyText = await page.locator("body").innerText();
    errors.push(`${label}: stock header missing: ${error.message} | body: ${bodyText.slice(0, 300)}`);
    return false;
  }
}

async function runNormalEnvelopeTest(page, mock, errors) {
  const label = "top-risk-normal";
  mock.setTopRiskMode("normal");
  mock.clearTopRiskHolds();
  mock.state.objectEndpointCalls = [];

  if (!await queryStock(page, "000001", "平安银行", label, errors)) return;
  await assertMainStockData(
    page,
    { name: "平安银行", price: "11.5", peTtm: "5.2" },
    label,
    errors,
  );

  const card = topRiskCard(page);
  if (!await expectVisible(card, `${label}: card/title not visible`, errors, 10000)) return;
  await expectVisible(card.getByText("正常", { exact: true }), `${label}: normal status not visible`, errors);
  await expectVisible(card.getByText("45", { exact: true }), `${label}: risk score not visible`, errors);
  await expectVisible(card.getByText("不参与", { exact: true }), `${label}: unknown signal must be non-participating`, errors);
  await expectVisible(card.getByText("signal: unknown", { exact: true }), `${label}: unknown signal label missing`, errors);
  await expectVisible(
    card.getByText("平安银行（000001）顶部风险分数 45/100；主要风险：拥挤度。", { exact: true }),
    `${label}: narrative missing`,
    errors,
  );

  const traceDetails = card.locator("details").filter({
    hasText: "步骤级分析明细（1 步）",
  }).first();
  const traceSummary = traceDetails.locator("summary").filter({
    hasText: "步骤级分析明细（1 步）",
  });
  if (await expectVisible(traceSummary, `${label}: native trace summary missing`, errors)) {
    if (await traceDetails.evaluate((element) => element.open)) {
      errors.push(`${label}: trace details should be collapsed before interaction`);
    }
    await traceSummary.click();
    if (!await traceDetails.evaluate((element) => element.open)) {
      errors.push(`${label}: trace details did not open after summary click`);
    }
    await expectVisible(
      traceDetails.getByText("拥挤度", { exact: true }),
      `${label}: trace step label not visible after expand`,
      errors,
    );
    await expectVisible(
      traceDetails.getByText("风险 · risk 0.45 · 置信 75", { exact: true }),
      `${label}: trace direction/risk/confidence not visible after expand`,
      errors,
    );
    await expectVisible(
      traceDetails.getByText("近期量能放大", { exact: true }),
      `${label}: trace reason not visible after expand`,
      errors,
    );
  }

  if (await card.getByText(/signal:\s*hold/i).count() > 0) {
    errors.push(`${label}: unknown signal was rendered as hold`);
  }

  const decisionLink = card.getByRole("link", { name: "决策依据 #tr_abc1234567890def" });
  if (await expectVisible(decisionLink, `${label}: decision_run_id link missing`, errors)) {
    const href = await decisionLink.getAttribute("href");
    if (href !== "/decision-evidence?run_id=tr_abc1234567890def") {
      errors.push(`${label}: decision_run_id link href mismatch (${href})`);
    }
  }

  const expectedObjectEndpoints = ["/api/dragon-tiger", "/api/lockup", "/api/blocks"];
  const allObjectMocksRequested = await waitUntil(() =>
    expectedObjectEndpoints.every((pathname) =>
      mock.state.objectEndpointCalls.some((call) => call.pathname === pathname && call.fulfilled)
    )
  );
  if (!allObjectMocksRequested) {
    errors.push(
      `${label}: object endpoint mocks were not all fulfilled (${JSON.stringify(mock.state.objectEndpointCalls)})`,
    );
  }
  await waitForDomToSettle(page.locator("body"), `${label}: empty object response consumption`, errors);
  await expectNoErrorBoundary(
    page,
    `${label}: dragonTiger/lockup/blocks empty objects crashed the page`,
    errors,
  );
}

async function runPartialEnvelopeTest(page, mock, errors) {
  const label = "top-risk-partial";
  mock.setTopRiskMode("partial");
  mock.clearTopRiskHolds();

  if (!await queryStock(page, "000002", "万科A", label, errors)) return;
  const card = topRiskCard(page);
  if (!await expectVisible(card, `${label}: card not visible`, errors, 10000)) return;
  await expectVisible(card.getByText("部分缺失", { exact: true }), `${label}: partial status missing`, errors);
  await expectVisible(
    card.getByText("valuation: 估值分位无数据", { exact: true }),
    `${label}: partial limitation missing`,
    errors,
  );
}

async function runUnavailableEnvelopeTest(page, mock, errors) {
  const label = "top-risk-unavailable";
  mock.setTopRiskMode("unavailable");
  mock.clearTopRiskHolds();

  if (!await queryStock(page, "000003", "测试股000003", label, errors)) return;
  const card = topRiskCard(page);
  if (!await expectVisible(card, `${label}: card not visible`, errors, 10000)) return;
  await expectVisible(card.getByText("不可用", { exact: true }), `${label}: unavailable status missing`, errors);
  await expectVisible(
    card.getByText("交易日未知 · 数据陈旧", { exact: true }),
    `${label}: fail-closed stale freshness missing`,
    errors,
  );
  await expectVisible(
    card.getByText("price_history: 核心行情数据当前不可用。", { exact: true }),
    `${label}: unavailable limitation missing`,
    errors,
  );
}

async function runHttpErrorTest(page, mock, errors) {
  const label = "top-risk-error";
  mock.setTopRiskMode("error");
  mock.clearTopRiskHolds();

  if (!await queryStock(page, "000004", "测试股000004", label, errors)) return;
  await expectVisible(
    page.getByRole("alert").filter({ hasText: "模拟顶部风险失败" }),
    `${label}: HTTP error detail not rendered`,
    errors,
  );
  await assertMainStockData(
    page,
    { name: "测试股000004", price: "8.2", peTtm: "5.2" },
    `${label}: main data after top-risk HTTP error`,
    errors,
  );
  await waitForDomToSettle(page.locator("body"), `${label}: HTTP error DOM`, errors);
  await expectNoErrorBoundary(
    page,
    `${label}: top-risk HTTP error crashed the main page`,
    errors,
  );
  const errorAccounted = await waitUntil(() =>
    mock.state.expectedHttpErrors.some((entry) =>
      entry.code === "000004" && entry.responseObserved && entry.consoleObserved && !entry.closed
    )
  );
  if (!errorAccounted) {
    errors.push(
      `${label}: expected /api/market/top-risk HTTP 502 was not fully accounted (${JSON.stringify(mock.state.expectedHttpErrors)})`,
    );
    return;
  }
  if (!mock.closeExpectedHttpError("000004")) {
    errors.push(`${label}: failed to close expected top-risk HTTP error accounting`);
  }
}

async function runNullEnvelopeTest(page, mock, errors) {
  const label = "top-risk-null";
  mock.setTopRiskMode("null");
  mock.clearTopRiskHolds();

  if (!await queryStock(page, "000005", "测试股000005", label, errors)) return;
  const card = topRiskCard(page);
  if (!await expectVisible(card, `${label}: card not visible`, errors, 10000)) return;

  await expectMetricValue(card, "风险分数", "—", label, errors);
  await expectMetricValue(card, "置信度", "—", label, errors);
  await expectMetricValue(card, "覆盖", "—", label, errors);
  await expectVisible(
    card.getByText("decision_run_id: —", { exact: true }),
    `${label}: null decision_run_id did not render —`,
    errors,
  );
}

async function runRaceTest(page, mock, errors) {
  const label = "top-risk-race";
  mock.setTopRiskMode("normal");
  mock.clearTopRiskHolds();
  mock.armTopRiskHold("000001");
  try {
    mock.resetTopRiskCalls();

    if (!await queryStock(page, "000001", "平安银行", label, errors)) return;
    const firstStarted = await waitUntil(() =>
      mock.state.topRiskCalls.some((call) => call.code === "000001" && call.held && !call.fulfilled)
    );
    if (!firstStarted) {
      errors.push(`${label}: held 000001 top-risk request did not start`);
      return;
    }

    // Switch to 000002 while the 000001 top-risk response is explicitly held.
    await fillCode(page, "000002");
    await clickQuery(page);
    try {
      await waitForStockHeader(page, "000002", "万科A");
    } catch (error) {
      errors.push(`${label}: second query failed: ${error.message}`);
      return;
    }

    const card = topRiskCard(page);
    await expectVisible(
      card.getByText("万科A（000002）顶部风险分数 82/100；主要风险：拥挤度。", { exact: true }),
      `${label}: newest 000002 top-risk response not visible`,
      errors,
      10000,
    );

    mock.releaseTopRiskHold("000001");

    const firstFulfilled = await waitUntil(() =>
      mock.state.topRiskCalls.some((call) => call.code === "000001" && call.fulfilled),
      5000,
    );
    if (!firstFulfilled) {
      errors.push(`${label}: released 000001 response never fulfilled`);
      return;
    }

    await observeDomTextWindow(
      page.locator("body"),
      {
        durationMs: 750,
        requiredTexts: ["万科A（000002）顶部风险分数 82/100；主要风险：拥挤度。"],
        forbiddenTexts: ["平安银行（000001）顶部风险分数 45/100；主要风险：拥挤度。"],
      },
      `${label}: stale response observation`,
      errors,
    );
    await expectMetricValue(card, "风险分数", "82", `${label}: final newest result`, errors);
    await expectVisible(
      card.getByText("万科A（000002）顶部风险分数 82/100；主要风险：拥挤度。", { exact: true }),
      `${label}: final newest narrative missing after observation window`,
      errors,
    );
  } finally {
    mock.clearTopRiskHolds();
  }
}

async function main() {
  const errors = [];
  let server = null;
  let browser = null;

  if (!existsSync(frontendDist) || !existsSync(path.join(frontendDist, "index.html"))) {
    console.error("frontend/dist missing — run: npm run build");
    process.exit(2);
  }

  try {
    const staticServer = await startStaticServer(frontendDist);
    server = staticServer.server;
    frontendPort = staticServer.port;
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);

    browser = await launchBrowser();
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    const mock = createApiMockController();
    await page.route("**/api/**", (route) => mock.handle(route));
    page.on("response", (response) => mock.recordResponse(response));

    page.on("pageerror", (err) => {
      errors.push(`pageerror: ${err.message} @@ ${err.stack?.split("\n").slice(0, 3).join(" | ") ?? "(no stack)"}`);
    });
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (mock.consumeExpectedConsoleError(text)) return;
      errors.push(`console.error: ${text}`);
    });

    await runNormalEnvelopeTest(page, mock, errors);
    await runPartialEnvelopeTest(page, mock, errors);
    await runUnavailableEnvelopeTest(page, mock, errors);
    await runHttpErrorTest(page, mock, errors);
    await runNullEnvelopeTest(page, mock, errors);
    await runRaceTest(page, mock, errors);

    if (mock.state.unexpectedApiCalls.length > 0) {
      errors.push(`unexpected API calls: ${mock.state.unexpectedApiCalls.join(", ")}`);
    }
    if (mock.state.unexpectedHttpResponses.length > 0) {
      errors.push(`unexpected HTTP error responses: ${JSON.stringify(mock.state.unexpectedHttpResponses)}`);
    }
    const unclosedExpectedErrors = mock.state.expectedHttpErrors.filter((entry) => !entry.closed);
    if (unclosedExpectedErrors.length > 0) {
      errors.push(`unclosed expected HTTP errors: ${JSON.stringify(unclosedExpectedErrors)}`);
    }

    await context.close();
  } catch (e) {
    errors.push(`fatal: ${e && e.stack ? e.stack : String(e)}`);
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch {
        /* ignore */
      }
    }
    if (server) {
      await new Promise((resolve) => server.close(() => resolve()));
    }
  }

  if (errors.length) {
    console.error(`FAIL top-risk E2E (${browserLabel})`);
    for (const e of errors) console.error(` - ${e}`);
    process.exit(1);
  }
  console.log(`PASS top-risk E2E (${browserLabel}) port=${frontendPort}`);
}

main();
