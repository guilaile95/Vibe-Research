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
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
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
    };
    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    await waitHttp(`${backend}/api/health`);

    // 隔离环境：bootstrap 一只持仓（canonical），让 Portfolio 页可发起建议
    await jsonRequest(backend, "/api/position/bootstrap-commit", "POST", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      note: "advice error vertical",
      positions: [{ code: "600519", shares: 100, cost_basis: 10 }],
    });

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

    console.log("[E2E] Portfolio Advice error observability vertical passed");
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
