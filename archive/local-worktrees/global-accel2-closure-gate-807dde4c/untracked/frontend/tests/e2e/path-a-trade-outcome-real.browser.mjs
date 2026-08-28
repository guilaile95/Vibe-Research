/**
 * Path A real browser vertical: UI-created executed Trades -> TAR1 -> OL1.
 *
 * A real Frozen Decision is prepared through the existing service/store helper;
 * the browser creates both executed Trades and performs both resolution clicks.
 * The Formal Outcome API and the Decision Performance readback are then checked
 * against the exact browser-created trade identity.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync, rmSync } from "node:fs";
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
const EVALUATION_AS_OF = "2099-01-01T00:00:00.000000Z";
const EXECUTION_TIME_1 = "2098-01-02T10:00";
const EXECUTION_TIME_2 = "2098-01-03T10:00";

function pythonConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: ["-m", "uvicorn"] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3", "-m", "uvicorn"] };
  return { cmd: "python3", args: ["-m", "uvicorn"] };
}

function pythonScriptConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: [] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3"] };
  return { cmd: "python3", args: [] };
}

function chromiumPath() {
  const configured = process.env.PLAYWRIGHT_CHROMIUM_PATH;
  if (configured && existsSync(configured)) return configured;
  const bases = [
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
      // FastAPI is still starting.
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
    ".ico": "image/x-icon",
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
  const payload = await response.json();
  assert.equal(response.status, expected, `${method} ${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

function createFrozenDecision(env, campaignId) {
  const payload = {
    security_code: "600519",
    strategy: "SWING",
    campaign_id: campaignId,
    thesis_id: "b".repeat(32),
    thesis_revision: 1,
    asset_view: {},
    trade_view: {},
    portfolio_view: {},
    next_best_action: "BUY SMALL",
    action_envelope: {},
    maintain_conditions: [],
    upgrade_conditions: [],
    downgrade_conditions: [],
    invalidation_conditions: [],
    strategy_horizon: "2w",
    review_by: "2098-12-31T00:00:00Z",
    key_assumptions: [],
    event_invalidation_conditions: [],
    risk_policy_version: "path-a-risk",
    opportunity_policy_version: "path-a-opportunity",
    decision_policy_version: "path-a-decision",
    behavior_model_version: "path-a-behavior",
    data_quality: {},
    evidence_confidence: null,
    inference_confidence: null,
    decision_confidence: null,
    evidence_refs: [],
    risk_refs: [],
    source_refs: [],
    user_confirmed: true,
  };
  const script = "import json, os; import frozen_decision_service as s; print(json.dumps(s.freeze_decision(json.loads(os.environ['PATH_A_DECISION_PAYLOAD']))))";
  const py = pythonScriptConfig();
  const result = spawnSync(py.cmd, [...py.args, "-c", script], {
    cwd: backendDir,
    env: { ...env, PATH_A_DECISION_PAYLOAD: JSON.stringify(payload) },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout.trim());
}

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

async function fillExecutedFullTrade(modal, executionTime, operation = "buy") {
  await modal.getByLabel("股票代码").fill("600519");
  await modal.getByLabel("股票名称").fill("贵州茅台");
  await modal.locator("select").nth(0).selectOption(operation);
  await modal.locator("select").nth(1).selectOption("full");
  await modal.getByPlaceholder("大于0", { exact: true }).fill("100");
  await modal.getByPlaceholder("正整数", { exact: true }).fill("1");
  await modal.locator('input[type="datetime-local"]').fill(executionTime);
  const costs = modal.getByPlaceholder("请输入实际费用，0 表示确认费用为 0");
  await costs.nth(0).fill("0");
  await costs.nth(1).fill("0");
  await modal.getByText(/Canonical UTC ISO：/).waitFor();
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before Path A browser E2E");
  const tempDataDir = await import("node:fs").then(({ mkdtempSync }) => mkdtempSync(join(tmpdir(), "vr-path-a-trade-outcome-e2e-")));
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
      ...process.env,
      VR_ALLOW_ORIGINS: frontend,
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      VIBE_RESEARCH_DECISION_CHALLENGE_DB: join(tempDataDir, "decision_challenges.sqlite3"),
      VIBE_RESEARCH_TRADE_ATTRIBUTION_DB: join(tempDataDir, "formal_trade_attributions.sqlite3"),
      VIBE_RESEARCH_TRADE_ORIGIN_DB: join(tempDataDir, "trade_origins.sqlite3"),
      VIBE_RESEARCH_FACT_LAKE_ROOT: join(tempDataDir, "fact-lake"),
      PYTHONUNBUFFERED: "1",
    };

    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);

    // Existing durable-authority helper pattern: only the Frozen Decision identity
    // is prepared; all Trade and resolution writes below are real browser actions.
    const campaign = await jsonRequest(backend, "/api/campaigns", "POST", {
      security_code: "600519",
      strategy: "SWING",
    }, 201);
    const decision = createFrozenDecision(env, campaign.campaign_id);
    assert.match(decision.decision_id, /^decision_[0-9a-f]{32}$/);

    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const consoleErrors = [];
    let attributionPosts = 0;
    let unplannedPosts = 0;
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("request", (request) => {
      if (request.method() !== "POST") return;
      const pathname = new URL(request.url()).pathname;
      if (pathname.endsWith("/attribution")) attributionPosts += 1;
      if (pathname.endsWith("/unplanned")) unplannedPosts += 1;
    });
    await page.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      return route.continue({ url: `${backend}${url.pathname}${url.search}` });
    });

    const waitForCreatedTrade = () => page.waitForResponse((response) => (
      response.request().method() === "POST"
      && new URL(response.url()).pathname === "/api/trades"
    ), { timeout: 60000 });
    const continuationUrl = `${frontend}/trades?create=1&code=600519&campaign_id=${campaign.campaign_id}&decision_id=${decision.decision_id}&next_best_action=BUY%20SMALL`;
    const openContinuationModal = async () => {
      await page.goto(continuationUrl, { waitUntil: "networkidle" });
      const modal = page.locator("div.fixed.inset-0").filter({ hasText: "新建交易流水" });
      await modal.getByText("从 Frozen Decision 续接实际执行", { exact: true }).waitFor();
      return modal;
    };
    const openCreateModal = async () => {
      await page.reload({ waitUntil: "networkidle" });
      await page.getByRole("button", { name: "新建交易" }).click();
      const modal = page.locator("div.fixed.inset-0").filter({ hasText: "新建交易流水" });
      await modal.waitFor();
      return modal;
    };

    // Path A1: browser creates an executed full Trade, then explicitly chooses
    // Formal Attribution; no resolution write is allowed before that click.
    const firstModal = await openContinuationModal();
    await fillExecutedFullTrade(firstModal, EXECUTION_TIME_1, "buy");
    assert.equal(attributionPosts, 0);
    assert.equal(unplannedPosts, 0);
    const [firstResponse] = await Promise.all([
      waitForCreatedTrade(),
      firstModal.getByRole("button", { name: "提交创建" }).click(),
    ]);
    assert.equal(firstResponse.ok(), true, await firstResponse.text());
    const firstTrade = (await firstResponse.json()).data;
    assert.match(firstTrade.trade_id, /^[0-9a-f]{32}$/);
    await firstModal.waitFor({ state: "detached" });
    await page.getByText(`ID: ${firstTrade.trade_id}`, { exact: true }).waitFor();
    await page.getByText("UNALLOCATED", { exact: true }).waitFor();
    await page.getByText(decision.decision_id, { exact: true }).waitFor();
    await page.locator('[data-continuation-candidate="preferred"]').waitFor();
    await page.getByText("来自 Frozen Decision 续接；仍需你明确归属", { exact: true }).waitFor();
    assert.equal(attributionPosts, 0, "Trade creation must not implicitly create Formal Attribution");
    await page.getByRole("button", { name: "明确归属" }).click();
    await page.getByText("ALLOCATED", { exact: true }).waitFor();
    assert.equal(attributionPosts, 1, "Formal Attribution must be the explicit browser action");
    const firstReconciliation = await jsonRequest(backend, `/api/trades/${firstTrade.trade_id}/reconciliation`);
    assert.equal(firstReconciliation.allocation_state, "ALLOCATED");
    assert.equal(firstReconciliation.reconciliation_requirement, "NOT_REQUIRED");
    assert.equal(firstReconciliation.decision_id, decision.decision_id);
    assert.equal(firstReconciliation.origin, null);

    const firstOutcome = await jsonRequest(
      backend,
      `/api/formal-decisions/${decision.decision_id}/outcome?evaluation_as_of=${encodeURIComponent(EVALUATION_AS_OF)}`,
    );
    assert.equal(firstOutcome.outcome_status, "EVALUATED");
    assert.deepEqual(firstOutcome.actual_capital_outcome.trade_ids, [firstTrade.trade_id]);
    assert.equal(firstOutcome.actual_capital_outcome.trade_count, 1);
    assert.equal(firstOutcome.actual_capital_outcome.state, "EVALUATED");

    // Path A2: browser creates another executed full Trade and explicitly marks
    // it UNPLANNED. It must not enter the decision's Formal Attribution set.
    const secondModal = await openCreateModal();
    await fillExecutedFullTrade(secondModal, EXECUTION_TIME_2, "add");
    const [secondResponse] = await Promise.all([
      waitForCreatedTrade(),
      secondModal.getByRole("button", { name: "提交创建" }).click(),
    ]);
    assert.equal(secondResponse.ok(), true, await secondResponse.text());
    const secondTrade = (await secondResponse.json()).data;
    assert.match(secondTrade.trade_id, /^[0-9a-f]{32}$/);
    assert.notEqual(secondTrade.trade_id, firstTrade.trade_id);
    await secondModal.waitFor({ state: "detached" });
    await page.getByText(`ID: ${secondTrade.trade_id}`, { exact: true }).waitFor();
    await page.getByText("UNALLOCATED", { exact: true }).waitFor();
    await page.getByRole("button", { name: "标记为 UNPLANNED" }).click();
    await page.getByText("UNPLANNED", { exact: true }).waitFor();
    await page.getByText("来源：明确 UNPLANNED（pre_trade_decision=NONE，pre_trade_thesis=NONE）", { exact: true }).waitFor();
    assert.equal(attributionPosts, 1, "UNPLANNED resolution must not create Formal Attribution");
    assert.equal(unplannedPosts, 1);
    const secondReconciliation = await jsonRequest(backend, `/api/trades/${secondTrade.trade_id}/reconciliation`);
    assert.equal(secondReconciliation.allocation_state, "UNPLANNED");
    assert.equal(secondReconciliation.reconciliation_requirement, "NOT_REQUIRED");
    assert.equal(secondReconciliation.origin, "UNPLANNED");
    assert.equal(secondReconciliation.pre_trade_decision, "NONE");
    assert.equal(secondReconciliation.pre_trade_thesis, "NONE");
    assert.equal(secondReconciliation.decision_id, null);

    const finalOutcome = await jsonRequest(
      backend,
      `/api/formal-decisions/${decision.decision_id}/outcome?evaluation_as_of=${encodeURIComponent(EVALUATION_AS_OF)}`,
    );
    assert.deepEqual(finalOutcome.actual_capital_outcome.trade_ids, [firstTrade.trade_id]);
    assert.equal(finalOutcome.actual_capital_outcome.trade_ids.includes(secondTrade.trade_id), false);
    assert.equal(finalOutcome.actual_capital_outcome.trade_count, 1);

    // Path A3: the actual browser readback uses the same exact Outcome endpoint;
    // inspect its response and the rendered review row, not a mocked fixture.
    const outcomeResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "GET"
      && new URL(response.url()).pathname === "/api/formal-decision-outcomes"
    ), { timeout: 60000 });
    await page.goto(`${frontend}/decision-performance?evaluation_as_of=${encodeURIComponent(EVALUATION_AS_OF)}`, { waitUntil: "networkidle" });
    const outcomeResponse = await outcomeResponsePromise;
    assert.equal(outcomeResponse.ok(), true, await outcomeResponse.text());
    const outcomeEnvelope = await outcomeResponse.json();
    const renderedOutcome = outcomeEnvelope.data.find((item) => item.decision_id === decision.decision_id);
    assert.ok(renderedOutcome, "Decision Performance must read back the prepared Frozen Decision");
    assert.deepEqual(renderedOutcome.actual_capital_outcome.trade_ids, [firstTrade.trade_id]);
    assert.equal(renderedOutcome.actual_capital_outcome.trade_ids.includes(secondTrade.trade_id), false);
    await page.getByRole("heading", { name: "决策复盘", exact: true }).waitFor();
    await page.getByRole("heading", { name: "Formal Decision Outcome", exact: true }).waitFor();
    const outcomeRow = page.getByTestId(`formal-outcome-${decision.decision_id}`);
    await outcomeRow.waitFor();
    await outcomeRow.getByText("Frozen Decision Context", { exact: true }).waitFor();
    await outcomeRow.getByText("EVALUATED · 1 exact attributed executed trade(s)", { exact: true }).waitFor();
    await page.getByTestId("review-worklist-group-upcoming").waitFor();
    await page.getByTestId(`review-worklist-upcoming-${decision.decision_id}`).waitFor();
    await page.getByTestId(`review-worklist-nba-${decision.decision_id}`).getByText("Frozen NBA at decision time: SWING · BUY SMALL", { exact: true }).waitFor();

    const actionableConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("ERR_NETWORK_ACCESS_DENIED")
        && !message.includes("Failed to load resource: the server responded with a status of 404"),
    );
    assert.equal(actionableConsoleErrors.length, 0, actionableConsoleErrors.join("\n"));
    console.log("[E2E] Path A real Trade -> Formal Outcome -> Decision Performance passed");
  } catch (error) {
    const detail = backendLog ? `\nBackend log:\n${backendLog}` : "";
    throw new Error(`${error.message}${detail}`, { cause: error });
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (backendProc && !backendProc.killed) backendProc.kill();
    await removeTempDir(tempDataDir);
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
