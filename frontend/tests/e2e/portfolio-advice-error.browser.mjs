/**
 * Product Reality vertical: Portfolio Advice error observability on the real frontend.
 *
 * Proves on the built frontend + real backend (isolated data dir):
 * A  clicking 生成持仓操作建议 with a valid model response renders the Advice;
 * B  a 502 structured output-invalid detail renders the exact safe rule reason
 *    (stage/reason from validator), not just「持仓建议模型输出无效」;
 * C  no internal details (api key / baseURL) ever appear in the UI error box.
 *
 * Model responses are injected at the /api/portfolio/advice route boundary
 * (the only non-deterministic layer); backend-side structure is proven by
 * test_portfolio_advice_error_mapping.py against the real FastAPI app.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = join(root, "backend");
const frontendDist = join(root, "frontend", "dist");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function pythonConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: ["-m", "uvicorn"] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3", "-m", "uvicorn"] };
  return { cmd: "python3", args: ["-m", "uvicorn"] };
}

function chromiumPath() {
  const bases = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of bases) {
    if (!base || !existsSync(base)) continue;
    if (path.extname(base).toLowerCase() === ".exe") return base;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const candidates = [
        join(base, entry, "chrome-win64", "chrome.exe"),
        join(base, entry, "chrome-linux", "chrome"),
        join(base, entry, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
      ];
      const found = candidates.find((candidate) => existsSync(candidate));
      if (found) return found;
    }
  }
  return undefined;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

async function waitHttp(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      // Backend is still starting.
    }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let pathname = (request.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }
    if (!existsSync(target)) target = path.join(dir, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function jsonRequest(base, pathname, method = "GET", body, expected = 200) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  assert.equal(response.status, expected, `${method} ${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

const VALID_ADVICE = {
  schema_version: "portfolio-advice-v0.1",
  generated_at: "2026-08-23 15:30:00",
  trade_date: "2026-08-23",
  market_status: "normal",
  portfolio_summary: { holding_count: 1, market_value: 1200, cost: 1000, pnl: 200, pnl_pct: 20 },
  account_action: { action: "hold", reason: "结构完整", confidence: "medium" },
  holdings: [{
    code: "600519", name: "贵州茅台", shares: 100, cost_price: 10, current_price: 12,
    market_value: 1200, pnl_amount: 200, pnl_pct: 20, holding_weight_pct: 100,
    action: "hold", execution_size_pct_of_holding: null, execution_quantity: null,
    trigger_conditions: ["市场广度修复后可继续持有"], price_conditions: [],
    execution_plan: ["按计划持有"], risk_conditions: ["个股相对板块明显转弱"],
    invalidation_conditions: ["原风险证据消失"], confidence: "medium", data_limitations: [],
  }],
  warnings: [], data_limitations: [],
};

const STRUCTURED_502 = {
  detail: {
    message: "持仓建议模型输出无效",
    error_code: "PORTFOLIO_ADVICE_OUTPUT_INVALID",
    stage: "policy_audit",
    reason: "reduce 比例仅允许 [10, 20, 30]，收到 25.0（code=002031）",
  },
};

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before advice error vertical");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-advice-error-e2e-"));
  let backendProc;
  let staticServer;
  let browser;
  try {
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const backend = `http://127.0.0.1:${backendPort}`;
    const frontend = `http://127.0.0.1:${frontendPort}`;
    const py = pythonConfig();
    const env = {
      ...process.env,
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
      VR_FACT_LAKE_ROOT: join(tempDataDir, "fact-lake"),
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      VIBE_RESEARCH_DECISION_CHALLENGE_DB: join(tempDataDir, "decision_challenges.sqlite3"),
      VIBE_RESEARCH_TRADE_ATTRIBUTION_DB: join(tempDataDir, "formal_trade_attributions.sqlite3"),
      VIBE_RESEARCH_TRADE_ORIGIN_DB: join(tempDataDir, "trade_origins.sqlite3"),
      VR_ALLOW_ORIGINS: frontend,
      PYTHONUNBUFFERED: "1",
      PYTHONPATH: [__dirname, backendDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    };
    backendProc = spawn(py.cmd, [...py.args, "portfolio_advice_account_gate_harness:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    await waitHttp(`${backend}/api/health`);

    // 隔离环境：两只 canonical Position；Account 因正式 coverage limitation 保持 partial。
    await jsonRequest(backend, "/api/position/bootstrap-commit", "POST", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      note: "advice error vertical",
      positions: [
        { code: "600519", shares: 1000, cost_basis: 10 },
        { code: "000001", shares: 1000, cost_basis: 8 },
      ],
    });
    await jsonRequest(backend, "/api/account-profile", "PUT", {
      total_assets: 122000,
      available_cash: 100000,
      confirm_current: true,
    });
    const reality = await jsonRequest(backend, "/api/account/reality");
    assert.equal(reality.cash.reconciliation, "MATCH");
    assert.equal(reality.canonical, false);
    assert.ok(reality.canonical_reason_codes.includes("ACCOUNT_COVERAGE_INCOMPLETE"));
    const livePortfolio = await jsonRequest(backend, "/api/portfolio");

    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const context = await browser.newContext();
    const page = await context.newPage();
    // 注入本地 LLM 配置（fake 值；POST 被 route 拦截，不会真实外呼）
    await page.addInitScript(() => {
      localStorage.setItem(
        "vr-llm",
        JSON.stringify({ provider: "api-compatible", baseURL: "http://10.255.255.1/v1", apiKey: "sk-not-a-real-key", model: "test-model" }),
      );
    });

    // 默认代理到真实 backend
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      try {
        const response = await fetch(`${backend}${url.pathname}${url.search}`, {
          method: request.method(),
          headers: request.headers(),
          body: request.method() === "GET" || request.method() === "HEAD" ? undefined : request.postDataBuffer(),
        });
        await route.fulfill({
          status: response.status,
          headers: Object.fromEntries(response.headers.entries()),
          body: Buffer.from(await response.arrayBuffer()),
        });
      } catch (error) {
        await route.fulfill({ status: 599, contentType: "application/json", body: JSON.stringify({ detail: "proxy failed" }) });
      }
    });

    await page.goto(`${frontend}/portfolio`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /生成持仓操作建议/ }).waitFor({ timeout: 30000 });

    // ---- PEX1. 不生成 AI 建议也能读取 Security Exposure ------------------
    await page.getByTestId("security-exposure-card").waitFor();
    await page.getByTestId("security-exposure-account-basis").getByText("MANUAL_CONFIRMED_TOTAL_ASSETS").waitFor();
    assert.equal((await page.getByTestId("security-exposure-quote-basis").innerText()).trim(), "QUOTE_COVERAGE_COMPLETE");
    assert.equal((await page.getByTestId("security-exposure-account-basis").innerText()).trim(), "MANUAL_CONFIRMED_TOTAL_ASSETS");
    assert.equal((await page.getByTestId("security-exposure-stock-account-pct").innerText()).trim(), "18.03%");
    assert.equal((await page.getByTestId("security-exposure-cash-account-pct").innerText()).trim(), "81.97%");
    assert.equal((await page.getByTestId("security-exposure-stock-600519").innerText()).trim(), "54.55%");
    assert.equal((await page.getByTestId("security-exposure-account-600519").innerText()).trim(), "9.84%");

    // ---- A. 成功路径：点击生成 → 渲染 Advice -----------------------------
    await page.route("**/api/portfolio/advice", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { ...VALID_ADVICE, trade_date: "2026-08-23" } }),
      });
    });
    await page.route("**/api/ai-results/portfolio_advice*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            result_type: "portfolio_advice", trade_date: "2026-08-23",
            schema_version: "portfolio_advice.v1", payload: VALID_ADVICE,
            generated_at: VALID_ADVICE.generated_at,
            model_provider: "test", model_name: "test-model", stale: false,
          },
        }),
      });
    });
    await page.getByRole("button", { name: /生成持仓操作建议/ }).click();
    await page.getByText("持仓决策依据追溯").waitFor({ timeout: 15000 });
    assert.ok(await page.getByText("600519").first().isVisible(), "valid advice must render holding");
    await page.unroute("**/api/portfolio/advice");
    await page.unroute("**/api/ai-results/portfolio_advice*");

    // ---- B/C. 结构化 502：具体规则原因可见、无内部细节 -------------------
    await page.route("**/api/portfolio/advice", async (route) => {
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify(STRUCTURED_502),
      });
    });
    await page.getByRole("button", { name: /生成持仓操作建议|重新生成/ }).click();
    const errorBox = page.locator("div.rounded-lg.border.border-destructive\\/30").first();
    await errorBox.waitFor({ timeout: 15000 });
    const errorText = await errorBox.innerText();
    assert.ok(
      errorText.includes("reduce 比例仅允许 [10, 20, 30]，收到 25.0（code=002031）"),
      `exact rule reason must be visible, got: ${errorText}`,
    );
    assert.ok(errorText.includes("持仓建议模型输出无效"), "classified headline stays");
    assert.ok(!errorText.includes("sk-not-a-real-key"), "C: api key must never render");
    assert.ok(!errorText.includes("10.255.255.1"), "C: baseURL must never render");

    // ---- D. 真实 Account Gate：partial 只阻断新增风险，不阻断减仓 ----------
    await page.unroute("**/api/portfolio/advice");
    await page.getByRole("button", { name: /生成持仓操作建议|重新生成/ }).click();
    const authority = page.getByTestId("account-funding-authority-status");
    await authority.waitFor({ timeout: 15000 });
    assert.ok((await authority.innerText()).includes("ACCOUNT_COVERAGE_INCOMPLETE"));

    const addCard = page.getByTestId("portfolio-advice-holding-600519");
    await addCard.waitFor();
    const addText = await addCard.innerText();
    assert.ok(addText.includes("加仓"));
    assert.ok(addText.includes("暂无具体买入数量与预计金额"));
    assert.ok(!addText.includes("建议买入数量"));
    assert.ok(!addText.includes("预计所需金额"));

    const reduceCard = page.getByTestId("portfolio-advice-holding-000001");
    await reduceCard.waitFor();
    const reduceText = await reduceCard.innerText();
    assert.ok(reduceText.includes("减仓"));
    assert.ok(reduceText.includes("建议操作数量"));
    assert.ok(reduceText.includes("200"));

    // ---- E. 已保存建议绑定 Account confirmation：identity 变化后旧买入数量失效 ----
    const accountRealityPath = join(tempDataDir, "account_reality_harness.json");
    const canonicalReality = (confirmationId) => ({
      canonical: true,
      canonical_reason_codes: [],
      account_authority: { state: "CANONICAL", confirmation_id: confirmationId },
      cash: {
        current_fact: {
          value: 100000,
          status: "CONFIRMED",
          confirmation_id: confirmationId,
          effective_at: "2026-08-28T15:00:00+08:00",
          recorded_at: "2026-08-28T15:01:00+08:00",
          updated_at: "2026-08-28T15:01:00+08:00",
        },
      },
      account_total_assets: {
        current_fact: {
          value: 122000,
          status: "CONFIRMED",
          confirmation_id: confirmationId,
          effective_at: "2026-08-28T15:00:00+08:00",
          recorded_at: "2026-08-28T15:01:00+08:00",
          updated_at: "2026-08-28T15:01:00+08:00",
        },
      },
    });
    writeFileSync(accountRealityPath, JSON.stringify(canonicalReality("confirmation-a")), "utf8");
    await page.getByRole("button", { name: /生成持仓操作建议|重新生成/ }).click();
    await page.getByTestId("portfolio-advice-holding-600519").getByText("建议买入数量").waitFor({ timeout: 15000 });

    writeFileSync(accountRealityPath, JSON.stringify(canonicalReality("confirmation-b")), "utf8");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("账户事实或确认身份已发生变化，旧建议的加仓数量与金额已失效，请重新生成。").waitFor({ timeout: 15000 });
    const staleAddText = await page.getByTestId("portfolio-advice-holding-600519").innerText();
    assert.ok(staleAddText.includes("暂无具体买入数量与预计金额"));
    assert.ok(!staleAddText.includes("建议买入数量"));
    assert.ok(!staleAddText.includes("预计所需金额"));

    // ---- PEX1 fail closed：行情覆盖不完整 + Account fact stale ------------
    await page.route("**/api/portfolio", async (route) => {
      const holdings = livePortfolio.holdings.map((holding) =>
        holding.code === "000001"
          ? { ...holding, price: null, market_value: null, pnl: null, pnl_pct: null, data_status: "unavailable" }
          : holding,
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            ...livePortfolio,
            holdings,
            totals: { ...livePortfolio.totals, market_value: null, pnl: null, pnl_pct: null },
            data_status: "partial",
            quote_coverage: { valid_holdings: 1, total_holdings: 2, complete: false },
          },
        }),
      });
    });
    const mismatchedReality = canonicalReality("confirmation-b");
    mismatchedReality.canonical = false;
    mismatchedReality.canonical_reason_codes = ["ACCOUNT_CONFIRMATION_IDENTITY_MISMATCH"];
    mismatchedReality.cash.current_fact.authority_state = "CANONICAL";
    mismatchedReality.account_total_assets.current_fact.authority_state = "CANONICAL";
    mismatchedReality.account_total_assets.current_fact.confirmation_id = "confirmation-c";
    let accountRealityOverride = mismatchedReality;
    await page.route("**/api/account/reality", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: accountRealityOverride }),
      });
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("security-exposure-account-basis").getByText("MANUAL_CONFIRMED_TOTAL_ASSETS").waitFor();
    assert.equal((await page.getByTestId("security-exposure-quote-basis").innerText()).trim(), "QUOTE_COVERAGE_PARTIAL");
    assert.equal((await page.getByTestId("security-exposure-account-600519").innerText()).trim(), "9.84%");
    assert.equal((await page.getByTestId("security-exposure-cash-account-pct").innerText()).trim(), "—");

    const staleReality = canonicalReality("confirmation-b");
    staleReality.canonical = false;
    staleReality.canonical_reason_codes = ["ACCOUNT_FACT_STALE"];
    staleReality.cash.current_fact.authority_state = "STALE";
    staleReality.account_total_assets.current_fact.authority_state = "STALE";
    accountRealityOverride = staleReality;
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="account-authority-status"][data-authority-state="STALE"]').waitFor();
    assert.equal((await page.getByTestId("security-exposure-account-basis").innerText()).trim(), "ACCOUNT_BASIS_UNKNOWN");
    assert.equal((await page.getByTestId("security-exposure-stock-account-pct").innerText()).trim(), "—");
    assert.equal((await page.getByTestId("security-exposure-cash-account-pct").innerText()).trim(), "—");
    assert.equal((await page.getByTestId("security-exposure-stock-600519").innerText()).trim(), "—");
    assert.equal((await page.getByTestId("security-exposure-account-600519").innerText()).trim(), "—");

    console.log("[E2E] Portfolio Advice + Account/confirmation gate + read-only Security Exposure vertical passed");
  } catch (error) {
    console.error(error);
    throw error;
  } finally {
    try { if (browser) await browser.close(); } catch {}
    try { if (staticServer) staticServer.close(); } catch {}
    try { if (backendProc) backendProc.kill(); } catch {}
    try { rmSync(tempDataDir, { recursive: true, force: true }); } catch {}
  }
}

run().then(() => process.exit(0)).catch((error) => {
  console.error(error);
  process.exit(1);
});
