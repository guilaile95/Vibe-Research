/**
 * PLANNING-PARITY-PORTFOLIO-RISK1-R2 browser acceptance.
 *
 * Real production frontend + real FastAPI app.  Only the existing astock
 * adapter boundary receives deterministic synthetic facts; all data stores
 * are temporary and no Owner account/portfolio is touched.
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");
const fixtureDir = path.join(__dirname, "portfolio_risk_context_fixture");
const screenshotDir = process.env.PORTFOLIO_RISK_CONTEXT_SCREENSHOT_DIR || path.join(tmpdir(), "vibe-research-portfolio-risk1-r2");

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function resolvePython() {
  if (process.env.PYTHON?.trim()) return process.env.PYTHON.trim();
  if (process.env.VR_PYTHON?.trim()) return process.env.VR_PYTHON.trim();
  const local = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  if (existsSync(local)) return local;
  return process.platform === "win32" ? "py" : "python3";
}

function chromiumExecutable() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH && existsSync(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH)) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  }
  const roots = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "ms-playwright"),
    process.env.HOME && path.join(process.env.HOME, ".cache", "ms-playwright"),
  ].filter(Boolean);
  for (const base of roots) {
    if (!existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const candidates = [
        path.join(base, entry, "chrome-win64", "chrome.exe"),
        path.join(base, entry, "chrome-linux", "chrome"),
        path.join(base, entry, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
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
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitHttp(url, attempts = 120) {
  for (let index = 0; index < attempts; index += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return response;
    } catch { /* uvicorn is still starting */ }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
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

function startStaticServer(dir, port, backendPort) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    const rawUrl = request.url || "/";
    if (rawUrl.startsWith("/api/")) {
      const proxy = fetch(`http://127.0.0.1:${backendPort}${rawUrl}`, {
        method: request.method,
        headers: { ...request.headers, host: `127.0.0.1:${backendPort}` },
        body: ["GET", "HEAD"].includes(request.method || "GET") ? undefined : request,
        duplex: "half",
      });
      proxy.then(async (upstream) => {
        response.writeHead(upstream.status, Object.fromEntries(upstream.headers.entries()));
        response.end(Buffer.from(await upstream.arrayBuffer()));
      }).catch((error) => {
        response.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
        response.end(`proxy failure: ${error.message}`);
      });
      return;
    }
    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(`${resolvedDir}${path.sep}`) && resolvedTarget !== resolvedDir) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }
    if (!existsSync(target) || path.extname(target) === "") target = path.join(dir, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function stopBackend(processHandle) {
  if (!processHandle?.pid) return;
  if (process.platform !== "win32") {
    processHandle.kill("SIGKILL");
    return;
  }
  await new Promise((resolve) => {
    const killer = spawn("taskkill", ["/pid", String(processHandle.pid), "/t", "/f"], { stdio: "ignore" });
    killer.once("close", resolve);
    killer.once("error", resolve);
  });
}

async function main() {
  assert.ok(existsSync(frontendDist), "frontend/dist missing; run npm run build first");
  await mkdir(screenshotDir, { recursive: true });
  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-portfolio-risk1-data-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-portfolio-risk1-reports-"));
  const factLakeDir = await mkdtemp(path.join(tmpdir(), "vr-portfolio-risk1-fact-lake-"));
  const modeFile = path.join(dataDir, "fixture-mode.txt");
  await writeFile(modeFile, "normal", "utf8");
  await writeFile(path.join(dataDir, "portfolio.json"), JSON.stringify({
    holdings: [
      { code: "600001", name: "Alpha电子", shares: 100, cost: 80 },
      { code: "600002", name: "Beta医药", shares: 100, cost: 40 },
      { code: "600003", name: "Gamma未分类", shares: 100, cost: 15 },
      { code: "600004", name: "Delta银行", shares: 100, cost: 8 },
    ],
    closed: [],
    last_refresh: null,
  }), "utf8");
  const backendPort = await freePort();
  const frontendPort = await freePort();
  const python = resolvePython();
  const pythonArgs = python === "py" ? ["-3"] : [];
  const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
  const env = {
    ...process.env,
    PYTHONPATH: [fixtureDir, backendDir, __dirname, process.env.PYTHONPATH || ""].filter(Boolean).join(process.platform === "win32" ? ";" : ":"),
    VR_ALLOW_ORIGINS: frontendOrigin,
    VR_DATA_DIR: dataDir,
    VR_REPORTS_DIR: reportsDir,
    VR_FACT_LAKE_ROOT: factLakeDir,
    VIBE_RESEARCH_TRADE_LEDGER_DB: path.join(dataDir, "trade_ledger.sqlite3"),
    VIBE_RESEARCH_REVIEW_DB: path.join(dataDir, "review_history.db"),
    VIBE_RESEARCH_EVIDENCE_THESIS_DB: path.join(dataDir, "evidence_thesis.db"),
    VIBE_RESEARCH_CAMPAIGN_DB: path.join(dataDir, "campaigns.sqlite3"),
    VIBE_RESEARCH_FROZEN_DECISION_DB: path.join(dataDir, "frozen_decisions.sqlite3"),
    VIBE_RESEARCH_DECISION_CHALLENGE_DB: path.join(dataDir, "decision_challenges.sqlite3"),
    VIBE_RESEARCH_TRADE_ATTRIBUTION_DB: path.join(dataDir, "formal_trade_attributions.sqlite3"),
    VIBE_RESEARCH_TRADE_ORIGIN_DB: path.join(dataDir, "trade_origins.sqlite3"),
    PORTFOLIO_RISK_CONTEXT_FIXTURE_MODE_FILE: modeFile,
    PYTHONUNBUFFERED: "1",
  };
  const backend = spawn(python, [...pythonArgs, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
    cwd: backendDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let backendLog = "";
  backend.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
  backend.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
  let staticServer;
  let browser;
  const errors = [];
  const mutations = [];
  const riskResponses = [];
  try {
    const backendBase = `http://127.0.0.1:${backendPort}`;
    await waitHttp(`${backendBase}/api/health`).catch((error) => {
      throw new Error(`${error.message}; backend log: ${backendLog || "<empty>"}`);
    });

    await jsonRequest(backendBase, "/api/account-profile", "PUT", {
      total_assets: 50000,
      available_cash: 25000,
      confirm_current: true,
    });
    const legacyDirect = await jsonRequest(backendBase, "/api/portfolio/risk-context");
    assert.equal(legacyDirect.schema_version, "portfolio_risk_context.v0.1");
    assert.equal(legacyDirect.holding_count, 4);
    assert.equal(legacyDirect.position_authority_state, "LEGACY");
    assert.equal(legacyDirect.status, "PARTIAL");
    assert.equal(legacyDirect.position_context.status, "LEGACY");
    assert.equal(legacyDirect.position_context.reason_code, "LEGACY_POSITION_AUTHORITY");
    assert.ok(legacyDirect.position_context.limitations.includes("LEGACY_HOLDINGS_VISIBILITY_ONLY"));
    assert.equal(legacyDirect.quote_coverage.status, "COMPLETE");
    assert.equal(legacyDirect.security_concentration.top1_pct, 55.56);
    assert.equal(legacyDirect.security_concentration.top3_pct, 94.44);
    assert.equal(legacyDirect.cash_buffer.ratio_pct, 50);
    assert.deepEqual(legacyDirect.writes, { formal_state: 0, account: 0, position: 0, trade: 0, portfolio: 0 });

    staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
    await waitHttp(`${frontendOrigin}/`);
    const launchOptions = { headless: true };
    const executablePath = chromiumExecutable();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const viewports = [
      { name: "desktop-1440", width: 1440, height: 900 },
      { name: "narrow-390", width: 390, height: 844 },
    ];
    const scenarios = ["legacy", "normal", "partial", "industry-failure"];
    for (const scenario of scenarios) {
      if (scenario === "normal") {
        await jsonRequest(backendBase, "/api/position/bootstrap-commit", "POST", {
          ledger_start_at: "2026-09-01",
          opening_cash: 25000,
          note: "portfolio risk context isolated browser fixture",
          positions: [
            { code: "600001", shares: 100, cost_basis: 80 },
            { code: "600002", shares: 100, cost_basis: 40 },
            { code: "600003", shares: 100, cost_basis: 15 },
            { code: "600004", shares: 100, cost_basis: 8 },
          ],
        });
        await jsonRequest(backendBase, "/api/account-profile", "PUT", {
          total_assets: 50000,
          available_cash: 25000,
          confirm_current: true,
        });
        const canonicalDirect = await jsonRequest(backendBase, "/api/portfolio/risk-context");
        assert.equal(canonicalDirect.position_authority_state, "CANONICAL");
        assert.equal(canonicalDirect.status, "NORMAL");
        assert.equal(canonicalDirect.position_context.status, "NORMAL");
        assert.equal(canonicalDirect.quote_coverage.status, "COMPLETE");
        assert.equal(canonicalDirect.security_concentration.top1_pct, 55.56);
        assert.equal(canonicalDirect.security_concentration.top3_pct, 94.44);
        assert.equal(canonicalDirect.cash_buffer.ratio_pct, 50);
        assert.equal(canonicalDirect.industry_coverage.unknown_industry_holdings, 1);
        assert.equal(canonicalDirect.industry_exposure.items.find((item) => item.industry === "UNKNOWN_INDUSTRY").weight_in_tracked_stock_pct, 11.11);
        assert.equal(canonicalDirect.drawdown.status, "UNAVAILABLE_NO_OFFICIAL_NAV_HISTORY");
        assert.equal(canonicalDirect.stress_test.status, "DEFERRED_NO_ACCEPTED_SCENARIO_CONTRACT");
        assert.deepEqual(canonicalDirect.writes, { formal_state: 0, account: 0, position: 0, trade: 0, portfolio: 0 });
      } else if (scenario !== "legacy") {
        await writeFile(modeFile, scenario, "utf8");
      }
      for (const viewport of viewports) {
        const browserContext = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
        const page = await browserContext.newPage();
        const evidenceName = `${scenario}-${viewport.name}`;
        await page.route("https://fonts.googleapis.com/**", (route) => route.fulfill({ contentType: "text/css", body: "" }));
        page.on("pageerror", (error) => errors.push(`${evidenceName} pageerror: ${error.message}`));
        page.on("console", (message) => { if (message.type() === "error") errors.push(`${evidenceName} console: ${message.text()}`); });
        page.on("requestfailed", (request) => errors.push(`${evidenceName} requestfailed: ${request.method()} ${request.url()} ${request.failure()?.errorText || "unknown"}`));
        page.on("response", (response) => { if (response.status() >= 400) errors.push(`${evidenceName} HTTP ${response.status()} ${response.url()}`); });
        page.on("response", async (response) => {
          if (response.url().includes("/api/portfolio/risk-context")) riskResponses.push({ scenario, status: response.status(), body: await response.json().catch(() => null) });
        });
        page.on("request", (request) => {
          if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method()) && new URL(request.url()).pathname.startsWith("/api/")) {
            mutations.push(`${evidenceName} ${request.method()} ${request.url()}`);
          }
        });
        await page.goto(`${frontendOrigin}/portfolio`, { waitUntil: "networkidle" });
        const card = page.getByTestId("portfolio-risk-context-card");
        await card.waitFor();
        await page.getByTestId("portfolio-risk-context-cash-buffer").waitFor();
        assert.equal(await page.getByTestId("portfolio-risk-context-cash-buffer").innerText(), "50.00%");
        await page.getByTestId("security-exposure-card").waitFor();
        await page.getByRole("heading", { name: "持仓操作建议" }).waitFor();
        const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
        assert.ok(dimensions.scroll <= dimensions.client + 2, `${evidenceName} document overflow: ${JSON.stringify(dimensions)}`);
        if (scenario === "legacy") {
          assert.equal(await page.getByTestId("portfolio-risk-context-status").innerText(), "部分可读");
          assert.match(await page.getByTestId("portfolio-risk-context-position-authority").innerText(), /Legacy fallback/);
          const legacyNotice = page.getByTestId("portfolio-risk-context-legacy-authority");
          await legacyNotice.waitFor();
          assert.match(await legacyNotice.innerText(), /尚未完成 canonical Position Reality/);
          assert.equal(await page.getByTestId("portfolio-risk-context-top1").innerText(), "Top 1 55.56%");
          assert.equal(await page.getByTestId("portfolio-risk-context-top3").innerText(), "Top 3 94.44%");
          assert.equal(await page.getByTestId("portfolio-risk-context-limitations").evaluate((element) => element.open), false);
        } else if (scenario === "normal") {
          assert.equal(await page.getByTestId("portfolio-risk-context-status").innerText(), "当前事实可读");
          assert.match(await page.getByTestId("portfolio-risk-context-position-authority").innerText(), /Canonical Position Reality/);
          assert.equal(await page.getByTestId("portfolio-risk-context-legacy-authority").count(), 0);
          await page.getByTestId("portfolio-risk-context-top1").waitFor();
          await page.getByTestId("portfolio-risk-context-top3").waitFor();
          assert.equal(await page.getByTestId("portfolio-risk-context-top1").innerText(), "Top 1 55.56%");
          assert.equal(await page.getByTestId("portfolio-risk-context-top3").innerText(), "Top 3 94.44%");
          await page.getByTestId("portfolio-risk-context-industry-UNKNOWN_INDUSTRY").waitFor();
          await page.getByTestId("portfolio-risk-context-drawdown").getByText("正式 NAV 历史").waitFor();
          await page.getByTestId("portfolio-risk-context-stress").getByText("压力情景").waitFor();
          assert.equal(await card.getByTestId("portfolio-risk-context-no-score").count(), 1);
          assert.equal(await card.getByTestId("portfolio-risk-context-no-recommendation").count(), 1);
        } else if (scenario === "partial") {
          await page.getByTestId("portfolio-risk-context-concentration-gap").waitFor();
          assert.equal(await page.getByTestId("portfolio-risk-context-top1").count(), 0);
          assert.match(await page.getByTestId("portfolio-risk-context-concentration-gap").innerText(), /部分可读/);
          await page.getByTestId("portfolio-risk-context-industry-UNKNOWN_INDUSTRY").waitFor();
        } else {
          await page.getByTestId("portfolio-risk-context-concentration").getByText("Top 1 55.56%", { exact: false }).waitFor();
          await page.getByTestId("portfolio-risk-context-industry-empty").waitFor();
          assert.match(await page.getByTestId("portfolio-risk-context-industry-empty").innerText(), /行业分类暂不可用/);
        }
        await page.screenshot({ path: path.join(screenshotDir, `${evidenceName}.png`), fullPage: true });
        await browserContext.close();
      }
    }
    assert.deepEqual(mutations, [], `portfolio risk context issued mutations after setup: ${mutations.join(" | ")}`);
    assert.ok(riskResponses.some((item) => item.status === 200 && item.body?.data?.schema_version === "portfolio_risk_context.v0.1"), "browser did not read the real risk-context route");
    const readme = [
      "# PLANNING-PARITY-PORTFOLIO-RISK1-R2 browser evidence",
      "",
      `Generated: ${new Date().toISOString()}`,
      "Backend: real FastAPI app, isolated Position Ledger/account profile, deterministic astock adapter fixture.",
      "Frontend: production build served as static dist; no page.route API mocks.",
      "",
      "## Checks",
      "- Canonical and pre-bootstrap LEGACY fallback holdings use the same isolated fixture",
      "- LEGACY is visibility-only, explicitly labeled, and overall PARTIAL (never NORMAL)",
      "- Four synthetic active holdings / complete deterministic quote coverage",
      "- Top 1 = 55.56%, Top 3 = 94.44%, cash buffer = 50.00%",
      "- Multiple current Eastmoney industries plus UNKNOWN_INDUSTRY",
      "- Partial quote scenario keeps cash/account facts and marks concentration not fully evaluable",
      "- Industry provider failure keeps concentration and cash while isolating industry block",
      "- Drawdown unavailable and stress test deferred wording",
      "- Existing Security Exposure and Portfolio Advice still visible",
      "- Desktop 1440x900 and narrow 390x844",
      "- No document overflow, pageerror, console error, or post-setup API mutation",
      "",
      `Risk API responses: ${JSON.stringify(riskResponses)}`,
      `Errors: ${errors.length ? errors.join(" | ") : "none"}`,
      "",
      `Screenshots: ${scenarios.flatMap((scenario) => viewports.map((viewport) => path.join(screenshotDir, `${scenario}-${viewport.name}.png`))).join(", ")}`,
      "",
    ].join("\n");
    await writeFile(path.join(screenshotDir, "README.md"), readme, "utf8");
    assert.deepEqual(errors, [], errors.join("\n"));
    console.log(`Portfolio risk context browser vertical OK; screenshots=${screenshotDir}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve)).catch(() => {});
    await stopBackend(backend);
    await Promise.all([
      rm(dataDir, { recursive: true, force: true }),
      rm(reportsDir, { recursive: true, force: true }),
      rm(factLakeDir, { recursive: true, force: true }),
    ]);
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
