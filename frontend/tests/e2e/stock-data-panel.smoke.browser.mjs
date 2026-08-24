/**
 * Stock data panel smoke E2E — pure frontend + Playwright page.route mocks.
 *
 * Architecture:
 * - Playwright loads the Vite build from a Node static server (frontend/dist only)
 * - ALL /api/* traffic is intercepted via page.route (NO real market data backend)
 * - Covers query binding, deferred K-line expand, cache, retry, and race guards
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

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
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

function startStaticServer(dir, port) {
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
    server.listen(port, "127.0.0.1", () => resolve(server));
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

function klineBars(code) {
  const base = code === "000001" ? 11 : 8;
  return Array.from({ length: 5 }, (_, i) => ({
    date: `2026-07-${String(20 + i).padStart(2, "0")}`,
    open: base + i * 0.1,
    close: base + i * 0.1 + 0.05,
    high: base + i * 0.1 + 0.2,
    low: base + i * 0.1 - 0.1,
    volume: 1000000 + i * 1000,
    amount: 1e8 + i * 1e6,
  }));
}

function technicalIndicatorsEnvelope(code, { status = "normal" } = {}) {
  const bars = klineBars(code);
  if (status === "unavailable") {
    return {
      schema_version: "technical-indicators-v0.2",
      code,
      period: "daily",
      trade_date: null,
      fetched_at: "2026-07-28T10:00:00Z",
      status: "unavailable",
      warnings: ["fixture unavailable"],
      limitations: [],
      latest: {
        close: null,
        sma5: null, sma10: null, sma20: null, sma60: null,
        ema12: null, ema26: null,
        macd_dif: null, macd_dea: null, macd_histogram: null,
        rsi14: null,
        bollinger_upper: null, bollinger_middle: null, bollinger_lower: null,
        volume_ratio_5_20: null,
        kdj_k: null, kdj_d: null, kdj_j: null,
      },
      triggers: [],
      series: [],
    };
  }

  const series = bars.map((b, i) => {
    const close = Number(b.close);
    const high = Number(b.high);
    const low = Number(b.low);
    // Ensure at least one day has BOLL outside candle range for coordinate coverage.
    const upper = i === bars.length - 1 ? high + 0.8 : high + 0.15;
    const lower = i === bars.length - 1 ? low - 0.8 : low - 0.15;
    return {
      date: b.date,
      sma20: close - 0.05,
      sma60: close - 0.12,
      bollinger_upper: upper,
      bollinger_middle: close,
      bollinger_lower: lower,
      macd_dif: 0.1,
      macd_dea: 0.05,
      macd_histogram: 0.05,
      rsi14: 55,
      volume_ratio_5_20: 1.1,
      kdj_k: 60 + i,
      kdj_d: 55 + i * 0.5,
      kdj_j: 70 + i,
    };
  });

  return {
    schema_version: "technical-indicators-v0.2",
    code,
    period: "daily",
    trade_date: bars[bars.length - 1]?.date ?? "2026-07-24",
    fetched_at: "2026-07-28T10:00:00Z",
    status,
    warnings: [],
    limitations: [],
    latest: {
      close: Number(bars[bars.length - 1].close),
      sma5: 11.2, sma10: 11.1, sma20: 11.0, sma60: 10.8,
      ema12: 11.15, ema26: 10.95,
      macd_dif: 0.12, macd_dea: 0.08, macd_histogram: 0.08,
      rsi14: 55.0,
      bollinger_upper: 11.5, bollinger_middle: 11.0, bollinger_lower: 10.5,
      volume_ratio_5_20: 1.2,
      kdj_k: 65.25,
      kdj_d: 58.50,
      kdj_j: 78.75,
    },
    triggers: [
      { type: "volume_spike", message: "5 日平均成交量超过 20 日平均成交量的 2 倍", value: 2.1 },
    ],
    series,
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

/**
 * Controllable mock state for kline race / delay / error scenarios.
 * Other endpoints return instant success payloads keyed by code.
 */
function createApiMockController() {
  const state = {
    klineDelayMs: 0,
    klineError: false,
    klineHold: null, // { resolve, code } pending fulfill
    klineCalls: [],
    valuationCalls: [],
    technicalIndicatorsStatus: "normal",
    technicalIndicatorsCalls: [],
  };

  function pathnameOf(url) {
    try {
      return new URL(url).pathname;
    } catch {
      return url;
    }
  }

  function codeOf(url) {
    try {
      return new URL(url).searchParams.get("code") || "";
    } catch {
      return "";
    }
  }

  async function handle(route) {
    const request = route.request();
    const url = request.url();
    if (!url.includes("/api/")) {
      await route.continue();
      return;
    }

    const pathname = pathnameOf(url);
    const code = codeOf(url);

    // K-line: delayed / error / hold for race tests
    if (pathname === "/api/kline" || pathname.endsWith("/kline")) {
      state.klineCalls.push({ code, url, ts: Date.now() });
      if (state.klineError) {
        await route.fulfill(jsonErr(500, "模拟 K 线失败"));
        return;
      }
      const manualHold = state.klineHold === "armed";
      const delayMs = state.klineDelayMs;
      if (manualHold || delayMs > 0) {
        await new Promise((resolve) => {
          state.klineHold = { resolve, code, route };
          if (!manualHold && delayMs > 0) {
            setTimeout(() => {
              if (state.klineHold && state.klineHold.route === route) {
                const hold = state.klineHold;
                state.klineHold = null;
                hold.resolve();
              }
            }, delayMs);
          }
        });
        await route.fulfill(jsonOk(klineBars(code)));
        return;
      }
      await route.fulfill(jsonOk(klineBars(code)));
      return;
    }

    if (pathname === "/api/valuation/percentile" || pathname.endsWith("/valuation/percentile")) {
      await route.fulfill(
        jsonOk({
          period: "近5年",
          metrics: {
            pe_ttm: {
              current: 5.2,
              percentile: 25,
              min: 3,
              max: 12,
              p20: 4,
              p50: 6,
              p80: 9,
              n: 1200,
            },
            pb: {
              current: 0.65,
              percentile: 30,
              min: 0.4,
              max: 1.5,
              p20: 0.5,
              p50: 0.8,
              p80: 1.1,
              n: 1200,
            },
          },
        }),
      );
      return;
    }

    if (pathname === "/api/valuation" || pathname.endsWith("/valuation")) {
      state.valuationCalls.push({ code, url, ts: Date.now() });
      await route.fulfill(jsonOk(valuationPayload(code || "000000")));
      return;
    }

    if (pathname.includes("/reports")) {
      await route.fulfill(
        jsonOk([
          {
            title: `${stockName(code)}深度报告`,
            publishDate: "2026-07-01",
            orgSName: "测试证券",
            emRatingName: "增持",
          },
        ]),
      );
      return;
    }

    if (pathname.includes("/financials")) {
      const latest = {
        period: "2026-06-30",
        period_end: "2026-06-30",
        report_date: null,
        revenue: "1000亿",
        revenue_yoy: "8%",
        net_profit: "200亿",
        net_profit_yoy: "10%",
        deduct_net_profit: "190亿",
        deduct_net_profit_yoy: "9%",
        eps: "1.50",
        bvps: "15.0",
        roe: "12%",
        gross_margin: "40%",
        net_margin: "20%",
        op_cf_ps: "2.1",
        current_ratio: "1.8",
        quick_ratio: "1.4",
        debt_to_equity_ratio: "0.5",
        debt_ratio: "33%",
        revenue_amount: 100_000_000_000,
        net_profit_amount: 20_000_000_000,
        parent_holder_net_profit_amount: 19_000_000_000,
        operating_cash_flow: 30_000_000_000,
        capital_expenditure: 4_000_000_000,
        free_cash_flow: 26_000_000_000,
        assets_total: 200_000_000_000,
        cash: 50_000_000_000,
        accounts_receivable: 10_000_000_000,
        total_debt: 80_000_000_000,
        holder_equity_total: 120_000_000_000,
        cash_conversion_ratio: 1.5,
        free_cash_flow_margin: 0.26,
        accrual_ratio: -0.05,
        receivables_pressure: 0.1,
        net_cash_ratio: -0.15,
      };
      await route.fulfill(
        jsonOk({
          ...latest,
          history: [latest, { ...latest, period: "2026-03-31", period_end: "2026-03-31" }],
          data_quality: {
            status: "normal",
            source: "tonghuashun_via_akshare",
            fetch_mode: "snapshot",
            report_basis: "cumulative_report_period",
            point_in_time_supported: false,
            publication_date_known: false,
            missing_fields: [],
            warnings: [],
          },
        }),
      );
      return;
    }

    if (pathname.includes("/announcements")) {
      await route.fulfill(
        jsonOk([{ date: "2026-07-10", title: "董事会决议公告", type: "公告", url: "" }]),
      );
      return;
    }

    if (pathname.includes("/news")) {
      await route.fulfill(
        jsonOk([{ 新闻标题: `${stockName(code)}相关新闻`, 发布时间: "2026-07-20", 文章来源: "测试", 新闻链接: "" }]),
      );
      return;
    }

    if (pathname.includes("/finance") && !pathname.includes("/financials")) {
      await route.fulfill(jsonOk({ 净利润: 100, 营业收入: 500, 报告期: "2025Q4" }));
      return;
    }

    if (pathname.includes("/info") && !pathname.includes("/info-")) {
      await route.fulfill(jsonOk({ 行业: "银行", 总股本: "194亿", 上市时间: "1991-04-03" }));
      return;
    }

    // 技术指标与价格触发：返回与 klineBars 日期对齐的 envelope
    if (pathname.includes("/technical-indicators")) {
      state.technicalIndicatorsCalls.push({ code, url, ts: Date.now() });
      await route.fulfill(
        jsonOk(
          technicalIndicatorsEnvelope(code || "000000", {
            status: state.technicalIndicatorsStatus,
          }),
        ),
      );
      return;
    }

    if (pathname.includes("/disclosure")) {
      await route.fulfill(
        jsonOk([{ date: "2026-07-01", title: "巨潮公告示例", url: "https://example.com" }]),
      );
      return;
    }

    // Top-risk analysis: explicit mock with normal envelope (deterministic)
    if (pathname.endsWith("/api/market/top-risk") || pathname.endsWith("/top-risk")) {
      await route.fulfill(
        jsonOk({
          schema_version: "top-risk-analysis-v0.1",
          source: "Vibe-Research top-risk engine",
          source_tier: "reference",
          code,
          name: stockName(code),
          trade_date: "2026-07-30",
          fetched_at: new Date().toISOString(),
          status: "normal",
          is_stale: false,
          risk_score: 42,
          confidence: 70,
          coverage: { completed: 4, total: 5, ratio: 0.8 },
          signal: "unknown",
          signal_eligible: false,
          trace_archive_status: "archived",
          warnings: [],
          limitations: [],
          data: {
            name: stockName(code),
            completed_steps: 4,
            total_steps: 5,
            risk_drivers: ["估值百分位过高"],
            safety_signals: ["机构持仓稳定"],
            narrative: "测试顶部风险分析结论",
          },
          trace: [
            {
              step_id: "valuation_percentile",
              label: "估值百分位",
              direction: "SAFE",
              weight: 1.0,
              step_risk: -0.2,
              confidence: 75,
              skipped: false,
              reasons: ["估值处于历史低位"],
              details: {},
            },
          ],
        }),
      );
      return;
    }

    // Auto-fired side panels: empty success
    if (
      pathname.includes("/margin")
      || pathname.includes("/block-trade")
      || pathname.includes("/holders")
      || pathname.includes("/dividend")
      || pathname.includes("/fund-flow")
      || pathname.includes("/hot-concepts")
      || pathname.includes("/investor-qa")
    ) {
      await route.fulfill(jsonOk([]));
      return;
    }

    if (pathname.includes("/dragon-tiger")) {
      await route.fulfill(
        jsonOk({
          records: [],
          seats: { buy: [], sell: [] },
          institution: { buy_amt: 0, sell_amt: 0, net_amt: 0 },
        }),
      );
      return;
    }

    if (pathname.includes("/lockup")) {
      await route.fulfill(jsonOk({ history: [], upcoming: [] }));
      return;
    }

    if (pathname.includes("/blocks")) {
      await route.fulfill(jsonOk({ total: 0, boards: [], concept_tags: [] }));
      return;
    }

    // Fallback for any other /api/*
    await route.fulfill(jsonOk({}));
  }

  async function releaseHeldKline() {
    if (state.klineHold && typeof state.klineHold.resolve === "function") {
      const hold = state.klineHold;
      state.klineHold = null;
      hold.resolve();
    }
  }

  function armManualHold() {
    state.klineDelayMs = 0;
    state.klineHold = "armed";
  }

  return {
    state,
    handle,
    setKlineDelay(ms) {
      state.klineDelayMs = ms;
    },
    setKlineError(flag) {
      state.klineError = !!flag;
    },
    setTechnicalIndicatorsStatus(status) {
      state.technicalIndicatorsStatus = status;
    },
    armManualHold() {
      state.klineHold = "armed";
    },
    async releaseHeldKline() {
      if (state.klineHold && state.klineHold !== "armed" && state.klineHold.resolve) {
        const hold = state.klineHold;
        state.klineHold = null;
        hold.resolve();
      }
    },
    resetKlineCalls() {
      state.klineCalls = [];
    },
    resetTechnicalIndicatorsCalls() {
      state.technicalIndicatorsCalls = [];
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

async function expandKline(page) {
  const btn = page.getByRole("button", { name: /历史 K 线/ }).first();
  await btn.waitFor({ state: "visible", timeout: 10000 });
  await btn.click();
}

async function collapseKline(page) {
  const btn = page.getByRole("button", { name: /历史 K 线/ }).first();
  await btn.click();
}

async function runSmoke(page, mock, errors) {
  const label = "stock-data-smoke";

  await page.goto(`http://127.0.0.1:${frontendPort}/stock-data`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("heading", { name: "个股数据" }).waitFor({ state: "visible", timeout: 15000 });

  // 1) Query 000001 → shows mock name + code
  await fillCode(page, "000001");
  await clickQuery(page);
  try {
    await waitForStockHeader(page, "000001", "平安银行");
  } catch (e) {
    errors.push(`${label}: after query 000001 missing header: ${e.message}`);
    return;
  }

  const health = page.getByTestId("fundamental-health");
  if (!(await health.isVisible().catch(() => false))) errors.push(`${label}: fundamental health module not visible`);
  for (const text of [
    "Growth · 增长",
    "Profitability · 盈利能力",
    "Cash Flow Quality · 现金流质量",
    "Balance Sheet Quality · 资产负债表",
    "Data Quality · 数据质量",
    "披露日期：未知（数据源未提供）",
    "现金转化率",
    "150.0%",
    "自由现金流",
    "260.00 亿元",
  ]) {
    if (!(await health.getByText(text, { exact: true }).first().isVisible().catch(() => false))) {
      errors.push(`${label}: fundamental health text not visible: ${text}`);
    }
  }
  const healthText = await health.innerText();
  for (const forbidden of ["归母净利润", "高增长", "高 ROE", "财务评分"]) {
    if (healthText.includes(forbidden)) errors.push(`${label}: forbidden health wording present: ${forbidden}`);
  }

  // Ensure 扩展数据 section is present
  const ext = page.getByText("扩展数据（可选依赖 · 按需加载）");
  if (!(await ext.isVisible().catch(() => false))) {
    errors.push(`${label}: 扩展数据 section not visible after query`);
  }

  // 技术指标接口必须已请求（独立 fetch，不阻塞主数据渲染）
  await sleep(500);
  const tiHeading = page.getByText("技术指标").first();
  if (!(await tiHeading.isVisible().catch(() => false))) {
    errors.push(`${label}: 技术指标 card heading not visible after query`);
  }
  if (!(await page.getByText("KDJ (9,3,3)").first().isVisible().catch(() => false))) {
    errors.push(`${label}: KDJ (9,3,3) label not visible`);
  }
  for (const kdjLabel of ["K", "D", "J"]) {
    const count = await page.getByText(kdjLabel, { exact: true }).count();
    if (count < 1) errors.push(`${label}: KDJ label ${kdjLabel} not visible`);
  }
  for (const val of ["65.25", "58.50", "78.75"]) {
    if (!(await page.getByText(val, { exact: true }).first().isVisible().catch(() => false))) {
      errors.push(`${label}: KDJ value ${val} not visible`);
    }
  }
  const bodyTextForKdj = await page.locator("body").innerText();
  for (const forbidden of ["KDJ 买入", "KDJ 卖出", "KDJ 金叉", "KDJ 死叉"]) {
    if (bodyTextForKdj.includes(forbidden)) {
      errors.push(`${label}: forbidden wording present: ${forbidden}`);
    }
  }
  // 主页面标题不受技术指标影响
  if (!(await page.getByRole("heading", { name: "平安银行" }).isVisible().catch(() => false))) {
    errors.push(`${label}: 平安银行 header hidden (TI fetch broke main page)`);
  }

  // 2) Change input to 000002 without clicking query
  await fillCode(page, "000002");
  // Header must still show 000001
  if (!(await page.getByRole("heading", { name: "平安银行" }).isVisible().catch(() => false))) {
    errors.push(`${label}: changing input to 000002 without query should keep 平安银行`);
  }

  // 3) Expand K-line → request still uses 000001
  mock.resetKlineCalls();
  mock.setKlineDelay(800);
  mock.setKlineError(false);
  await expandKline(page);

  // 4) loading state visible
  const loadingVisible = await page.getByText("加载中…").first().isVisible().catch(() => false);
  if (!loadingVisible) {
    // status label on the row also says 加载中…
    const statusLoading = await page.getByText("加载中…").count();
    if (statusLoading < 1) {
      errors.push(`${label}: expected loading state after expand K-line`);
    }
  }

  // Wait until kline call recorded with code=000001
  let deadline = Date.now() + 5000;
  while (Date.now() < deadline && mock.state.klineCalls.length === 0) {
    await sleep(50);
  }
  if (mock.state.klineCalls.length === 0) {
    errors.push(`${label}: expand K-line did not issue /api/kline request`);
  } else {
    const first = mock.state.klineCalls[0];
    if (first.code !== "000001") {
      errors.push(`${label}: kline request expected code=000001, got ${first.code}`);
    }
  }

  // 5) success content after delay
  try {
    await page.getByText(/最近 \d+ 个交易日 OHLC/).waitFor({ state: "visible", timeout: 10000 });
  } catch (e) {
    errors.push(`${label}: kline success content not visible: ${e.message}`);
  }

  // 5b) indicator overlays visible with aligned fixture
  const svg = page.locator('[data-testid="kline-chart-svg"]').first();
  if (!(await svg.isVisible().catch(() => false))) {
    errors.push(`${label}: kline svg not visible`);
  } else {
    const aria = await svg.getAttribute("aria-label");
    if (aria !== "K 线及技术指标图") {
      errors.push(`${label}: expected aria-label "K 线及技术指标图", got ${aria}`);
    }
  }
  for (const id of [
    "kline-overlay-sma20",
    "kline-overlay-sma60",
    "kline-overlay-bollinger-upper",
    "kline-overlay-bollinger-lower",
  ]) {
    const n = await page.locator(`[data-testid="${id}"]`).count();
    if (n < 1) errors.push(`${label}: missing overlay layer ${id}`);
  }
  if (!(await page.getByTestId("kline-overlay-legend").isVisible().catch(() => false))) {
    errors.push(`${label}: overlay legend not visible`);
  }
  // path/polyline attributes must not contain NaN/Infinity
  const overlayNodes = page.locator(
    '[data-testid="kline-overlay-sma20"],[data-testid="kline-overlay-sma60"],[data-testid="kline-overlay-bollinger-upper"],[data-testid="kline-overlay-bollinger-lower"]',
  );
  const overlayCount = await overlayNodes.count();
  for (let i = 0; i < overlayCount; i++) {
    const pts = await overlayNodes.nth(i).getAttribute("points");
    const cx = await overlayNodes.nth(i).getAttribute("cx");
    const cy = await overlayNodes.nth(i).getAttribute("cy");
    const blob = `${pts || ""} ${cx || ""} ${cy || ""}`;
    if (/NaN|Infinity|-Infinity/i.test(blob)) {
      errors.push(`${label}: overlay geometry contains non-finite value: ${blob}`);
    }
  }
  // candle tooltip includes OHLC + metrics
  const candle = page.locator('[data-testid="kline-candle"]').first();
  if (await candle.count()) {
    const tip = (await candle.locator("title").textContent().catch(() => "")) || "";
    for (const key of ["开盘", "最高", "最低", "收盘", "SMA20", "SMA60", "BOLL 上轨", "BOLL 下轨"]) {
      if (!tip.includes(key)) errors.push(`${label}: candle title missing ${key}: ${JSON.stringify(tip)}`);
    }
  } else {
    errors.push(`${label}: no candle nodes for tooltip assertion`);
  }

  const afterFirst = mock.state.klineCalls.length;

  // 6) collapse and re-expand without duplicate request
  await collapseKline(page);
  await sleep(200);
  await expandKline(page);
  await sleep(400);
  if (mock.state.klineCalls.length !== afterFirst) {
    errors.push(
      `${label}: re-expand issued duplicate kline request (before=${afterFirst}, after=${mock.state.klineCalls.length})`,
    );
  }

  // 7) simulate error then retry
  // Force error by resetting panel via re-query is heavy; use retry path:
  // Collapse, re-query same stock to reset panels, then error mode.
  await fillCode(page, "000001");
  await clickQuery(page);
  try {
    await waitForStockHeader(page, "000001", "平安银行");
  } catch (e) {
    errors.push(`${label}: re-query 000001 failed before error scenario: ${e.message}`);
  }

  mock.resetKlineCalls();
  mock.setKlineDelay(0);
  mock.setKlineError(true);
  await expandKline(page);
  try {
    await page.getByText(/加载失败|模拟 K 线失败/).first().waitFor({ state: "visible", timeout: 8000 });
  } catch (e) {
    errors.push(`${label}: expected kline error UI: ${e.message}`);
  }

  mock.setKlineError(false);
  const retryBtn = page.locator('button[title="重试"]').first();
  if (await retryBtn.isVisible().catch(() => false)) {
    const beforeRetry = mock.state.klineCalls.length;
    await retryBtn.click();
    try {
      await page.getByText(/最近 \d+ 个交易日 OHLC/).waitFor({ state: "visible", timeout: 8000 });
    } catch (e) {
      errors.push(`${label}: retry did not show success: ${e.message}`);
    }
    if (mock.state.klineCalls.length <= beforeRetry) {
      errors.push(`${label}: retry did not issue new kline request`);
    }
  } else {
    errors.push(`${label}: retry button not visible after kline error`);
  }

  // 8) formal query 000002 resets panel state
  await fillCode(page, "000002");
  await clickQuery(page);
  try {
    await waitForStockHeader(page, "000002", "万科A");
  } catch (e) {
    errors.push(`${label}: query 000002 failed: ${e.message}`);
  }
  // K-line panel should be collapsed/idle (no success body from 000001)
  if (await page.getByText(/最近 \d+ 个交易日 OHLC/).isVisible().catch(() => false)) {
    errors.push(`${label}: kline success body should reset after formal query 000002`);
  }
  // Status hint back to mootdx / not 已加载
  const klineRow = page.getByRole("button", { name: /历史 K 线/ }).first();
  const klineText = (await klineRow.innerText().catch(() => "")) || "";
  if (klineText.includes("已加载") || klineText.includes("加载失败")) {
    errors.push(`${label}: kline panel status not reset after query 000002 (text=${klineText})`);
  }

  // 9) Race: start kline for 000001, switch query to 000002 before fulfill
  await fillCode(page, "000001");
  await clickQuery(page);
  try {
    await waitForStockHeader(page, "000001", "平安银行");
  } catch (e) {
    errors.push(`${label}: re-query 000001 for race failed: ${e.message}`);
  }

  mock.resetKlineCalls();
  mock.setKlineError(false);
  mock.setKlineDelay(0);
  mock.armManualHold();

  await expandKline(page);
  // Wait until request is held
  deadline = Date.now() + 5000;
  while (Date.now() < deadline && !mock.state.klineHold) {
    await sleep(30);
  }
  if (!mock.state.klineHold || mock.state.klineHold === "armed") {
    // If still armed, wait a bit more for first request
    deadline = Date.now() + 3000;
    while (Date.now() < deadline && (mock.state.klineHold === "armed" || !mock.state.klineHold)) {
      await sleep(30);
    }
  }
  if (!mock.state.klineHold || mock.state.klineHold === "armed") {
    errors.push(`${label}: race setup failed — kline request was not held`);
  } else {
    // Switch to 000002 before fulfilling held 000001 kline
    await fillCode(page, "000002");
    await clickQuery(page);
    try {
      await waitForStockHeader(page, "000002", "万科A");
    } catch (e) {
      errors.push(`${label}: race query 000002 failed: ${e.message}`);
    }

    // Release delayed 000001 kline
    await mock.releaseHeldKline();
    await sleep(600);

    // Must NOT show 000001 kline success on 000002 page
    if (await page.getByText(/最近 \d+ 个交易日 OHLC/).isVisible().catch(() => false)) {
      errors.push(`${label}: delayed 000001 kline wrote into 000002 page (race)`);
    }
    // Header still 万科A
    if (!(await page.getByRole("heading", { name: "万科A" }).isVisible().catch(() => false))) {
      errors.push(`${label}: race left page without 万科A header`);
    }
  }

  // 10) Technical indicators unavailable must not break kline panel
  await fillCode(page, "000001");
  mock.setTechnicalIndicatorsStatus("unavailable");
  await clickQuery(page);
  try {
    await waitForStockHeader(page, "000001", "平安银行");
  } catch (e) {
    errors.push(`${label}: re-query 000001 for TI unavailable failed: ${e.message}`);
  }
  mock.resetKlineCalls();
  mock.setKlineError(false);
  mock.setKlineDelay(0);
  await expandKline(page);
  try {
    await page.getByText(/最近 \d+ 个交易日 OHLC/).waitFor({ state: "visible", timeout: 10000 });
  } catch (e) {
    errors.push(`${label}: kline missing when technical indicators unavailable: ${e.message}`);
  }
  const candlesWhenTiDown = await page.locator('[data-testid="kline-candle"]').count();
  if (candlesWhenTiDown < 1) {
    errors.push(`${label}: expected candles when technical indicators unavailable`);
  }
  for (const id of [
    "kline-overlay-sma20",
    "kline-overlay-sma60",
    "kline-overlay-bollinger-upper",
    "kline-overlay-bollinger-lower",
  ]) {
    if ((await page.locator(`[data-testid="${id}"]`).count()) > 0) {
      errors.push(`${label}: overlay ${id} should not render when TI unavailable`);
    }
  }
  if (await page.getByText("加载失败").first().isVisible().catch(() => false)) {
    // only fail if kline panel specifically failed; check OHLC still present
    if (!(await page.getByText(/最近 \d+ 个交易日 OHLC/).isVisible().catch(() => false))) {
      errors.push(`${label}: kline panel degraded to failure because TI unavailable`);
    }
  }
  // restore normal TI for cleanliness
  mock.setTechnicalIndicatorsStatus("normal");
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
    frontendPort = await getFreePort();
    server = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);

    browser = await launchBrowser();
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    const mock = createApiMockController();
    await page.route("**/api/**", (route) => mock.handle(route));

    page.on("pageerror", (err) => {
      errors.push(`pageerror: ${err.message}`);
    });

    await runSmoke(page, mock, errors);
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
    console.error(`FAIL stock-data-panel smoke (${browserLabel})`);
    for (const e of errors) console.error(` - ${e}`);
    process.exit(1);
  }
  console.log(`PASS stock-data-panel smoke (${browserLabel}) port=${frontendPort}`);
}

main();
