/**
 * Candidate Research source-to-sink browser vertical.
 *
 * This harness intentionally does not use page.route mocks. It starts the real
 * FastAPI app, serves the built dist, proxies /api to Uvicorn, and uses only a
 * temporary sitecustomize.py to make StockData's public data providers
 * deterministic. Campaign create/list/transition/read APIs remain real.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer, request as httpRequest } from "node:http";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolvePython() {
  if (process.env.VR_E2E_PYTHON?.trim()) {
    return { command: process.env.VR_E2E_PYTHON.trim(), prefix: [] };
  }
  if (process.env.VR_PYTHON?.trim()) {
    return { command: process.env.VR_PYTHON.trim(), prefix: [] };
  }
  const win = path.join(backendDir, ".venv", "Scripts", "python.exe");
  if (existsSync(win)) return { command: win, prefix: [] };
  const lin = path.join(backendDir, ".venv", "bin", "python");
  if (existsSync(lin)) return { command: lin, prefix: [] };
  return process.platform === "win32"
    ? { command: "py", prefix: ["-3"] }
    : { command: "python3", prefix: [] };
}

function findChromium() {
  const explicit = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
  ].filter(Boolean);
  for (const candidate of explicit) {
    if (existsSync(candidate)) return candidate;
  }

  const roots = [
    path.join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    path.join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    let entries = [];
    try {
      entries = readdirSync(base);
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.startsWith("chromium-")) continue;
      for (const candidate of [
        path.join(base, entry, "chrome-win64", "chrome.exe"),
        path.join(base, entry, "chrome-win", "chrome.exe"),
        path.join(base, entry, "chrome-linux", "chrome"),
        path.join(base, entry, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
      ]) {
        if (existsSync(candidate)) return candidate;
      }
    }
  }
  return undefined;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitHttp(url, attempts = 150) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return response;
    } catch {
      // Uvicorn is still starting.
    }
    await sleep(300);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function createProxyRequest(req, res, backendPort) {
  const headers = { ...req.headers, host: `127.0.0.1:${backendPort}` };
  const proxy = httpRequest(
    {
      hostname: "127.0.0.1",
      port: backendPort,
      path: req.url,
      method: req.method,
      headers,
    },
    (upstream) => {
      res.writeHead(upstream.statusCode || 502, upstream.headers);
      upstream.pipe(res, { end: true });
    },
  );
  proxy.on("error", (error) => {
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    }
    res.end(`proxy error: ${error.message}`);
  });
  return proxy;
}

function startStaticServer(directory, port, backendPort) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  };
  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    if (rawUrl === "/api" || rawUrl.startsWith("/api/")) {
      const proxy = createProxyRequest(req, res, backendPort);
      req.pipe(proxy, { end: true });
      return;
    }

    let pathname;
    try {
      pathname = decodeURIComponent(rawUrl.split("?")[0] || "/");
    } catch {
      res.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
      res.end("bad path");
      return;
    }
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(directory, pathname);
    const resolvedDir = path.resolve(directory);
    let resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || path.extname(target) === "") target = path.join(directory, "index.html");
    resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep)) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    res.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function runProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(" ")} exited ${code}: ${stderr || stdout}`));
    });
  });
}

async function stopProcess(child) {
  if (!child || child.exitCode != null) return;
  if (process.platform === "win32") {
    await runProcess("taskkill", ["/pid", String(child.pid), "/t", "/f"]).catch(() => {});
  } else {
    child.kill("SIGTERM");
  }
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 8000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function startBackend(tempDir, fixtureDir, allowOrigin) {
  const port = await freePort();
  const python = resolvePython();
  const campaignDb = path.join(tempDir, "campaigns.sqlite3");
  const env = {
    ...process.env,
    PYTHONPATH: [fixtureDir, backendDir].join(path.delimiter),
    VR_ALLOW_ORIGINS: allowOrigin,
    PYTHONUNBUFFERED: "1",
    VR_DATA_DIR: tempDir,
    VR_REPORTS_DIR: path.join(tempDir, "reports"),
    VIBE_RESEARCH_CAMPAIGN_DB: campaignDb,
    VIBE_RESEARCH_DECISION_TRACE_DB: path.join(tempDir, "decision_trace.sqlite3"),
  };
  const child = spawn(
    python.command,
    [...python.prefix, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"], shell: false },
  );
  let logs = "";
  child.stdout.on("data", (chunk) => { logs += chunk.toString(); });
  child.stderr.on("data", (chunk) => { logs += chunk.toString(); });
  try {
    await waitHttp(`http://127.0.0.1:${port}/api/health`);
  } catch (error) {
    await stopProcess(child);
    throw new Error(`${error.message}\n${logs}`);
  }
  return { child, port, campaignDb, logs: () => logs };
}

async function launchBrowser() {
  const executablePath = findChromium();
  const base = { headless: true };
  try {
    const browser = await chromium.launch(executablePath ? { ...base, executablePath } : { ...base, channel: "chrome" });
    return { browser, label: `${executablePath ? "executable" : "chrome-channel"}-${browser.version()}` };
  } catch (firstError) {
    if (executablePath) throw firstError;
    const browser = await chromium.launch(base);
    return { browser, label: `playwright-${browser.version()}` };
  }
}

async function writeSitecustomize(fixtureDir) {
  const source = String.raw`# Temporary deterministic StockData provider fixture for Candidate Research E2E.
import astock

CODE = "600519"


def tencent_quote(codes):
    return {
        code: {
            "name": "贵州茅台",
            "price": 1688.0,
            "last_close": 1670.0,
            "open": 1675.0,
            "change_amt": 18.0,
            "change_pct": 1.08,
            "high": 1695.0,
            "low": 1668.0,
            "amount_wan": 100000.0,
            "turnover_pct": 0.3,
            "pe_ttm": 28.0,
            "mcap_yi": 21000.0,
            "float_mcap_yi": 20500.0,
            "pb": 9.0,
            "limit_up": 1837.0,
            "limit_down": 1503.0,
            "vol_ratio": 1.2,
            "pe_static": 29.0,
        }
        for code in codes
        if code == CODE
    }


def full_valuation(code):
    if code != CODE:
        raise ValueError("fixture only supports 600519")
    return {
        "name": "贵州茅台", "code": CODE, "price": 1688.0,
        "mcap_yi": 21000.0, "pe_ttm": 28.0, "pb": 9.0,
        "eps_26e": 65.0, "eps_27e": 72.0, "pe_26e": 26.0,
        "cagr_pct": 12.0, "peg": 2.17, "digest_years": 0.0,
        "analyst_count": 18,
    }


def financials(code, include_health=False):
    row = {
        "period": "2026-06-30", "period_end": "2026-06-30", "report_date": None,
        "revenue": "893.0 亿", "revenue_yoy": "8.2%",
        "net_profit": "420.0 亿", "net_profit_yoy": "11.4%",
        "deduct_net_profit": "418.0 亿", "deduct_net_profit_yoy": "11.1%",
        "eps": "33.45", "bvps": "240.0", "roe": "18.2%",
        "gross_margin": "91.5%", "net_margin": "47.0%", "op_cf_ps": "35.1",
        "current_ratio": "1.8", "quick_ratio": "1.6",
        "debt_to_equity_ratio": "0.22", "debt_ratio": "18.0%",
        "revenue_amount": 89300000000, "net_profit_amount": 42000000000,
        "parent_holder_net_profit_amount": 41800000000,
        "operating_cash_flow": 44100000000, "capital_expenditure": 3100000000,
        "free_cash_flow": 41000000000, "assets_total": 310000000000,
        "cash": 120000000000, "accounts_receivable": 12000000000,
        "total_debt": 56000000000, "holder_equity_total": 254000000000,
        "cash_conversion_ratio": 1.05, "free_cash_flow_margin": 0.459,
        "accrual_ratio": -0.0068, "receivables_pressure": 0.134,
        "net_cash_ratio": 0.206,
    }
    if not include_health:
        return row
    return {
        **row,
        "history": [row, {**row, "period": "2026-03-31", "period_end": "2026-03-31"}],
        "data_quality": {
            "status": "normal", "source": "temporary_sitecustomize_fixture",
            "fetch_mode": "snapshot", "report_basis": "cumulative_report_period",
            "point_in_time_supported": False, "publication_date_known": False,
            "missing_fields": [], "warnings": [],
        },
    }


def valuation_percentile(code, period="近五年"):
    return {"period": "近5年", "metrics": {
        "pe_ttm": {"current": 28.0, "percentile": 72.0, "min": 12.0, "max": 40.0, "p20": 18.0, "p50": 25.0, "p80": 31.0, "n": 120},
        "pb": {"current": 9.0, "percentile": 68.0, "min": 4.0, "max": 13.0, "p20": 6.0, "p50": 8.0, "p80": 10.0, "n": 120},
    }}


def announcements(code, limit=15):
    return [{"date": "2026-08-20", "notice_at": "2026-08-20", "title": "贵州茅台：半年度报告公告", "type": "定期报告", "url": ""}]


def eastmoney_reports(code, max_pages=3):
    return [{"title": "贵州茅台 2026 年中期研究报告", "publishDate": "2026-08-21", "orgSName": "Fixture 证券", "emRatingName": "增持"}]


def stock_news(code, limit=20):
    return [{"新闻标题": "贵州茅台渠道与动销保持稳定", "发布时间": "2026-08-22 09:30", "文章来源": "Fixture News", "新闻链接": ""}]


def individual_info(code):
    return {"行业": "白酒", "总股本": "12.56 亿", "上市时间": "2001-08-27"}


def disclosure(code):
    return [{"公告日期": "2026-08-20", "公告标题": "半年度报告"}]


def _bars(code, offset=120):
    bars = []
    for index in range(max(65, min(offset, 120))):
        day = index + 1
        close = 1660.0 + index * 0.8
        bars.append({
            "date": "2026-06-%02d" % (day if day <= 30 else ((day - 1) % 30) + 1),
            "open": close - 2.0, "close": close, "high": close + 5.0,
            "low": close - 5.0, "volume": 1000000 + index * 1000,
            "amount": 1688000000 + index * 1000000,
        })
    return bars


def kline(code, category=4, offset=60):
    return _bars(code, offset)


def finance(code):
    return {"净利润": 42000000000, "营业收入": 89300000000, "报告期": "2026Q2"}


def concept_blocks(code):
    return {"total": 2, "boards": [
        {"name": "白酒", "code": "BK0001", "change_pct": 1.2, "lead_stock": "600519"},
        {"name": "消费", "code": "BK0002", "change_pct": 0.8, "lead_stock": "600519"},
    ], "concept_tags": ["白酒", "消费"]}


def hot_concepts(code):
    return [{"concept": "高端白酒", "bk": "BK0001", "hit": 12}]


def margin_trading(code, page_size=30):
    return []


def block_trade(code, page_size=20):
    return []


def holder_num_change(code, page_size=10):
    return []


def dividend_history(code, page_size=20):
    return []


def stock_fund_flow_120d(code):
    return []


def dragon_tiger_board(code, trade_date=None, look_back=30):
    return {"records": [], "seats": {"buy": [], "sell": []}, "institution": {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}}


def lockup_expiry(code, trade_date=None, forward_days=90):
    return {"history": [], "upcoming": []}


def investor_qa(code, page_size=30):
    return []


astock.tencent_quote = tencent_quote
astock.full_valuation = full_valuation
astock.financials = financials
astock.valuation_percentile = valuation_percentile
astock.announcements = announcements
astock.eastmoney_reports = eastmoney_reports
astock.stock_news = stock_news
astock.individual_info = individual_info
astock.disclosure = disclosure
astock.kline = kline
astock.finance = finance
astock.concept_blocks = concept_blocks
astock.hot_concepts = hot_concepts
astock.margin_trading = margin_trading
astock.block_trade = block_trade
astock.holder_num_change = holder_num_change
astock.dividend_history = dividend_history
astock.stock_fund_flow_120d = stock_fund_flow_120d
astock.dragon_tiger_board = dragon_tiger_board
astock.lockup_expiry = lockup_expiry
astock.investor_qa = investor_qa

# Top Risk is a StockData dependency, but its real Campaign-independent provider
# may consult several remote feeds. Replace only this temporary service entrypoint.
try:
    import top_risk_service
    from top_risk_schema import TopRiskData, TopRiskEnvelope, TopRiskStepTrace

    def fixture_top_risk(code, days=120):
        return TopRiskEnvelope(
            code=code,
            name="贵州茅台",
            trade_date="2026-08-22",
            fetched_at="2026-08-22T09:30:00.000000Z",
            status="normal",
            is_stale=False,
            risk_score=35,
            confidence=82,
            coverage={"completed": 1, "total": 1, "ratio": 1.0},
            signal="unknown",
            signal_eligible=False,
            config_hash="fixture_config",
            input_fingerprint="fixture_input",
            decision_run_id=None,
            trace_archive_status="skipped",
            warnings=[],
            limitations=[],
            data=TopRiskData(
                name="贵州茅台",
                completed_steps=1,
                total_steps=1,
                risk_drivers=["估值水平"],
                safety_signals=["经营现金流稳定"],
                narrative="贵州茅台（600519）顶部风险强度中（35/100）；主要风险：估值水平；缓解信号：经营现金流稳定。",
            ),
            trace=[TopRiskStepTrace(
                step_id="valuation", label="估值水平", direction="RISK",
                weight=1.0, step_risk=0.35, confidence=82, skipped=False,
                reasons=["估值处于历史中高位"], details={},
            )],
        )

    top_risk_service.analyze_top_risk = fixture_top_risk
except Exception:
    pass
`;
  await writeFile(path.join(fixtureDir, "sitecustomize.py"), source, "utf8");
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`${options.method || "GET"} ${url} returned non-JSON HTTP ${response.status}: ${text.slice(0, 300)}`);
  }
  return { response, body };
}

async function expectVisible(locator, label, timeout = 15000) {
  await locator.waitFor({ state: "visible", timeout });
  assert.equal(await locator.isVisible(), true, `${label} must be visible`);
}

async function main() {
  assert.ok(existsSync(path.join(frontendDist, "index.html")), `built frontend missing: ${frontendDist}`);

  const tempDir = await mkdtemp(path.join(tmpdir(), "vr-candidate-real-e2e-"));
  const fixtureDir = path.join(tempDir, "python-fixture");
  await mkdir(fixtureDir, { recursive: true });
  await mkdir(path.join(tempDir, "reports"), { recursive: true });
  await writeSitecustomize(fixtureDir);

  let backend;
  let staticServer;
  let browser;
  let page;
  const apiRequests = [];
  const createdPayloads = [];
  const transitionPayloads = [];
  const pageErrors = [];
  const consoleErrors = [];
  let campaignId = null;
  let pageSpanMs = null;

  try {
    const frontendPort = await freePort();
    const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
    backend = await startBackend(tempDir, fixtureDir, frontendOrigin);
    staticServer = await startStaticServer(frontendDist, frontendPort, backend.port);
    const baseUrl = frontendOrigin;
    const apiUrl = `http://127.0.0.1:${backend.port}/api`;

    const launched = await launchBrowser();
    browser = launched.browser;
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    page = await context.newPage();
    page.on("request", (request) => {
      const url = request.url();
      if (!url.includes("/api/")) return;
      const parsed = new URL(url);
      const item = { method: request.method(), path: parsed.pathname, url };
      apiRequests.push(item);
      if (item.path === "/api/campaigns" && item.method === "POST") {
        const payload = request.postDataJSON();
        createdPayloads.push(payload);
      }
      if (item.path.match(/^\/api\/campaigns\/[^/]+\/transitions$/) && item.method === "POST") {
        transitionPayloads.push(request.postDataJSON());
      }
    });
    page.on("response", async (response) => {
      const url = new URL(response.url());
      if (url.pathname === "/api/campaigns" || /\/api\/campaigns\/[^/]+\/(?:next-actions|transitions)?$/.test(url.pathname)) {
        console.log(`[E2E] response ${response.status()} ${response.request().method()} ${url.pathname} ${await response.text().catch(() => "")}`);
      }
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    const pageStartedAt = Date.now();
    await page.goto(`${baseUrl}/stock-data?code=600519`, { waitUntil: "domcontentloaded" });
    await page.locator('[data-active-code="600519"]').waitFor({ state: "visible", timeout: 20000 });
    await expectVisible(page.getByRole("heading", { name: "贵州茅台", exact: true }), "valuation stock heading");
    await expectVisible(page.getByTestId("fundamental-health"), "Fundamental Health");
    await expectVisible(page.getByTestId("fundamental-health").getByText("Growth · 增长", { exact: true }), "fundamental growth");
    await expectVisible(page.getByTestId("fundamental-health").getByText("Profitability · 盈利能力", { exact: true }), "fundamental profitability");
    await expectVisible(page.getByTestId("fundamental-health").getByText("Cash Flow Quality · 现金流质量", { exact: true }), "fundamental cash flow");
    await expectVisible(page.getByText("近期研报（1）", { exact: true }), "reports");
    await expectVisible(page.getByText("近期公告（1）", { exact: true }), "announcements");
    await expectVisible(page.getByText("个股新闻", { exact: true }), "news");
    await expectVisible(page.getByText("技术指标", { exact: true }).first(), "technical indicators");
    await expectVisible(page.getByText("板块归属 · 概念", { exact: true }), "sector/concept panel");
    await expectVisible(page.getByText("白酒", { exact: true }).first(), "sector concept tag");
    await expectVisible(page.getByRole("heading", { name: /顶部风险分析/ }), "top risk");
    await expectVisible(page.getByText("贵州茅台（600519）顶部风险强度中（35/100）；主要风险：估值水平；缓解信号：经营现金流稳定。", { exact: true }), "top risk narrative");

    const panel = page.getByTestId("candidate-campaign-panel");
    await expectVisible(panel, "Candidate Research panel");
    await expectVisible(panel.getByText("暂无候选 Campaign", { exact: true }), "empty candidate state");
    const createButton = panel.getByTestId("create-candidate-campaign");
    assert.equal(await createButton.isDisabled(), true, "create must be disabled before strategy selection");

    const shortRadio = panel.getByRole("radio", { name: "SHORT · 短线", exact: true });
    await shortRadio.evaluate((element) => element.click());
    assert.equal(await shortRadio.isChecked(), true, "SHORT strategy must be selected");
    assert.equal(await createButton.isDisabled(), false, "create must enable after SHORT selection");
    await createButton.click();
    await panel.locator('[data-campaign-status="DRAFT"]').waitFor({ state: "visible", timeout: 15000 });
    assert.deepEqual(createdPayloads, [{ security_code: "600519", strategy: "SHORT" }], "real create payload must be minimal");
    assert.equal(transitionPayloads.length, 0, "campaign creation must not auto-transition");

    const draft = panel.locator('[data-campaign-status="DRAFT"]');
    campaignId = await draft.getAttribute("data-campaign-id");
    assert.match(campaignId || "", /^campaign_[0-9a-f]{32}$/, "server must generate campaign_id");

    await panel.getByRole("button", { name: "继续研究", exact: true }).click();
    await panel.locator('[data-campaign-status="RESEARCHING"]').waitFor({ state: "visible", timeout: 15000 });
    assert.deepEqual(transitionPayloads, [{ expected_status: "DRAFT", to_status: "RESEARCHING" }]);

    await panel.getByRole("button", { name: "继续研究", exact: true }).click();
    await panel.locator('[data-campaign-status="PRE-ENTRY"]').waitFor({ state: "visible", timeout: 15000 });
    assert.deepEqual(transitionPayloads, [
      { expected_status: "DRAFT", to_status: "RESEARCHING" },
      { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
    ]);

    const reject = panel.getByRole("button", { name: "停止研究（已拒绝）", exact: true });
    await expectVisible(reject, "explicit PRE-ENTRY rejected action");
    await reject.click();
    await expectVisible(panel.getByRole("alertdialog"), "rejection confirmation dialog");
    assert.equal(transitionPayloads.length, 2, "clicking reject must not POST before confirmation");
    await expectVisible(panel.getByRole("button", { name: "确认停止研究（已拒绝）", exact: true }), "rejection confirmation");
    await panel.getByRole("button", { name: "确认停止研究（已拒绝）", exact: true }).click();
    await panel.getByText("暂无候选 Campaign", { exact: true }).waitFor({ state: "visible", timeout: 15000 });
    assert.deepEqual(transitionPayloads, [
      { expected_status: "DRAFT", to_status: "RESEARCHING" },
      { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
      { expected_status: "PRE-ENTRY", to_status: "REJECTED" },
    ]);

    const durable = await jsonFetch(`${apiUrl}/campaigns/${campaignId}`);
    assert.equal(durable.response.status, 200, "durable Campaign GET must succeed");
    assert.equal(durable.body.data.status, "REJECTED", "durable status must be REJECTED");
    assert.equal(durable.body.data.strategy, "SHORT");

    const history = await jsonFetch(`${apiUrl}/campaigns/${campaignId}/transitions`);
    assert.equal(history.response.status, 200, "durable Campaign transition history GET must succeed");
    assert.deepEqual(
      history.body.data.map((item) => [item.from_status, item.to_status]),
      [["DRAFT", "RESEARCHING"], ["RESEARCHING", "PRE-ENTRY"], ["PRE-ENTRY", "REJECTED"]],
      "durable history must preserve the three explicit transitions",
    );

    const nextActions = await jsonFetch(`${apiUrl}/campaigns/${campaignId}/next-actions`);
    assert.equal(nextActions.response.status, 200, "durable next-actions GET must succeed");
    assert.equal(nextActions.body.data.status, "REJECTED");
    assert.deepEqual(nextActions.body.data.next_actions, [], "terminal REJECTED must have no next actions");

    const forbidden = /\/api\/(?:thesis|evidence|decision|trades?|trade|freeze|frozen-decisions?|orders?|broker|position|buy|commit)(?:\/|$)/i;
    const forbiddenRequests = apiRequests.filter((item) => forbidden.test(item.path));
    assert.deepEqual(forbiddenRequests, [], "Candidate Research must not call Thesis/Decision/Trade/freeze/order/broker authorities");
    assert.deepEqual(pageErrors, [], `pageerror must stay empty: ${pageErrors.join(" | ")}`);

    const requiredPaths = [
      "/api/valuation",
      "/api/financials",
      "/api/announcements",
      "/api/reports",
      "/api/news",
      "/api/market/technical-indicators",
      "/api/market/top-risk",
      "/api/blocks",
      "/api/hot-concepts",
      "/api/campaigns",
    ];
    for (const required of requiredPaths) {
      assert.ok(apiRequests.some((item) => item.path === required), `missing real proxied dependency ${required}`);
    }

    pageSpanMs = Date.now() - pageStartedAt;
    const screenshot = path.join(tempDir, "candidate-campaign-real.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    console.log(`[E2E] browser=${launched.label}`);
    console.log(`[E2E] page span=${pageSpanMs}ms url=${page.url()}`);
    console.log(`[E2E] visible=valuation,financials,announcements,reports,news,technical,sector/concept,top-risk`);
    console.log(`[E2E] campaign=${campaignId} strategy=SHORT final_status=${durable.body.data.status}`);
    console.log(`[E2E] transitions=${history.body.data.length} next_actions=${JSON.stringify(nextActions.body.data.next_actions)} transition_posts_before_confirm=0`);
    console.log(`[E2E] forbidden_api_requests=${forbiddenRequests.length} pageerrors=${pageErrors.length} console_errors=${consoleErrors.length}`);
    console.log(`[E2E] screenshot=${screenshot}`);
    console.log("candidate campaign real browser vertical: PASS");

    await context.close();
  } finally {
    if (page && !page.isClosed()) await page.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (backend) await stopProcess(backend.child);
    await rm(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error("[E2E] FAILED", error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
