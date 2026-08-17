/**
 * P0-TAR1 real browser vertical.
 *
 * The browser performs the resolution actions.  The fixture creates a real
 * Frozen Decision through the existing service/store so the candidate shown
 * by Trades is not a mocked identity or an inferred match.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { spawn, spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = join(root, "backend");
const frontendDist = join(root, "frontend", "dist");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function removeTempDir(dir) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      rmSync(dir, { recursive: true, force: true });
      return;
    } catch (error) {
      if (attempt === 19) throw error;
      await sleep(100);
    }
  }
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
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8" };
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

function pythonConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: ["-m", "uvicorn"] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3", "-m", "uvicorn"] };
  return { cmd: "python3", args: ["-m", "uvicorn"] };
}

function chromiumPath() {
  const bases = [process.env.PLAYWRIGHT_CHROMIUM_PATH, join(process.env.LOCALAPPDATA || "", "ms-playwright"), join(process.env.HOME || "", ".cache", "ms-playwright")];
  for (const base of bases) {
    if (!base || !existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const candidates = [join(base, entry, "chrome-win64", "chrome.exe"), join(base, entry, "chrome-linux", "chrome"), join(base, entry, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium")];
      const found = candidates.find((candidate) => existsSync(candidate));
      if (found) return found;
    }
  }
  return undefined;
}

async function jsonRequest(base, pathname, method = "GET", body, expected = 200) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expected, `${method} ${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

function createRealFrozenDecision(env, campaignId) {
  const payload = {
    security_code: "600519", strategy: "SWING", campaign_id: campaignId,
    thesis_id: "b".repeat(32), thesis_revision: 1,
    asset_view: {}, trade_view: {}, portfolio_view: {},
    next_best_action: "BUY SMALL", action_envelope: {},
    maintain_conditions: [], upgrade_conditions: [], downgrade_conditions: [], invalidation_conditions: [],
    strategy_horizon: "2w", review_by: "2099-01-01T00:00:00Z",
    key_assumptions: [], event_invalidation_conditions: [],
    risk_policy_version: "tar1-risk", opportunity_policy_version: "tar1-opportunity",
    decision_policy_version: "tar1-decision", behavior_model_version: "tar1-behavior",
    data_quality: {}, evidence_confidence: null, inference_confidence: null, decision_confidence: null,
    evidence_refs: [], risk_refs: [], source_refs: [], user_confirmed: true,
  };
  const script = "import json, os; import frozen_decision_service as s; print(json.dumps(s.freeze_decision(json.loads(os.environ['TAR1_DECISION_PAYLOAD']))))";
  const result = spawnSync(env.PYTHON || "python3", ["-c", script], {
    cwd: backendDir,
    env: { ...env, TAR1_DECISION_PAYLOAD: JSON.stringify(payload) },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout.trim());
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before TAR1 browser E2E");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-tar1-trade-resolution-e2e-"));
  let backendProc;
  let staticServer;
  let browser;
  let backendLog = "";
  try {
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const backend = `http://127.0.0.1:${backendPort}`;
    const frontend = `http://127.0.0.1:${frontendPort}`;
    const py = pythonConfig();
    const env = {
      ...process.env, VR_DATA_DIR: tempDataDir, VR_REPORTS_DIR: tempDataDir,
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      VIBE_RESEARCH_TRADE_ATTRIBUTION_DB: join(tempDataDir, "formal_trade_attributions.sqlite3"),
      VIBE_RESEARCH_TRADE_ORIGIN_DB: join(tempDataDir, "trade_origins.sqlite3"),
      PYTHONUNBUFFERED: "1",
    };
    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"] });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);

    const campaign = await jsonRequest(backend, "/api/campaigns", "POST", { security_code: "600519", strategy: "SWING" }, 201);
    const decision = createRealFrozenDecision(env, campaign.campaign_id);
    const trade = await jsonRequest(backend, "/api/trades", "POST", {
      code: "600519", name: "贵州茅台", operation: "buy", execution_status: "full",
      actual_price: 100, actual_quantity: 1, executed_at: "2098-01-01T01:00:00Z",
    });

    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("response", async (response) => {
      if (response.request().method() === "POST" && /\/attribution|\/unplanned/.test(response.url())) {
        console.log(`[E2E] ${response.status()} ${response.url()} ${await response.text()}`);
      }
    });
    await page.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      return route.continue({ url: `${backend}${url.pathname}${url.search}` });
    });

    await page.goto(`${frontend}/trades`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "详情" }).first().click();
    await page.getByText("交易归属与 Campaign 对账").waitFor();
    await page.getByText("UNALLOCATED", { exact: true }).waitFor();
    await page.getByText("RECONCILIATION REQUIRED", { exact: false }).waitFor();
    await page.getByText(decision.decision_id, { exact: true }).waitFor();
    await page.getByRole("button", { name: "明确归属" }).click();
    await page.getByText("ALLOCATED", { exact: true }).waitFor();
    await page.getByText(campaign.campaign_id, { exact: true }).waitFor();
    await page.getByText(decision.decision_id, { exact: true }).waitFor();
    assert.equal((await jsonRequest(backend, `/api/trades/${trade.trade_id}/reconciliation`)).allocation_state, "ALLOCATED");

    const secondTrade = await jsonRequest(backend, "/api/trades", "POST", {
      code: "600519", name: "贵州茅台", operation: "add", execution_status: "full",
      actual_price: 101, actual_quantity: 1, executed_at: "2098-01-01T01:01:00Z",
    });

    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "详情" }).last().click();
    await page.getByText("ALLOCATED", { exact: true }).waitFor();

    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "详情" }).first().click();
    await page.getByText("UNALLOCATED", { exact: true }).waitFor();
    await page.getByRole("button", { name: "标记为 UNPLANNED" }).click();
    await page.getByText("UNPLANNED", { exact: true }).waitFor();
    await page.getByText(/pre_trade_decision=NONE/).waitFor();
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "详情" }).first().click();
    await page.getByText("UNPLANNED", { exact: true }).waitFor();
    const secondState = await jsonRequest(backend, `/api/trades/${secondTrade.trade_id}/reconciliation`);
    assert.equal(secondState.pre_trade_decision, "NONE");
    assert.equal(secondState.pre_trade_thesis, "NONE");
    assert.equal(secondState.reconciliation_requirement, "NOT_REQUIRED");
    assert.equal(existsSync(join(tempDataDir, "formal_trade_attributions.sqlite3")), true);
    assert.equal(existsSync(join(tempDataDir, "trade_origins.sqlite3")), true);
    assert.equal(consoleErrors.filter((message) => !message.includes("ERR_NETWORK_ACCESS_DENIED")).length, 0, JSON.stringify(consoleErrors));
    console.log("[E2E] P0-TAR1 trade attribution and reconciliation passed");
  } catch (error) {
    if (backendProc && !backendProc.killed) console.error(backendLog || "backend log unavailable");
    throw error;
  } finally {
    if (browser) await browser.close();
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (backendProc && !backendProc.killed) backendProc.kill();
    await removeTempDir(tempDataDir);
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
