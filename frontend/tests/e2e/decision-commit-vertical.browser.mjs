/**
 * P0-DC1 Decision Commit vertical — isolated real FastAPI + Chromium E2E.
 *
 * Campaign → frozen Current Thesis → same-as-of Preview → explicit checkbox
 * → existing Frozen Decision service/store → backend GET re-read → Decision
 * Inbox.  The only persistence location is a temporary VR_DATA_DIR.
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
const backendDir = path.join(root, "backend");
const frontendDist = path.join(root, "frontend", "dist");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitHttp(url, attempts = 120) {
  for (let i = 0; i < attempts; i += 1) {
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

async function createFrozenCurrentThesis(base) {
  const campaign = await jsonRequest(base, "/api/campaigns", "POST", {
    security_code: "600519",
    strategy: "SWING",
  }, 201);
  const created = await jsonRequest(base, "/api/thesis", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    title: "DC1 Chromium Formal Thesis",
    summary: "isolated current thesis",
    core_claims: ["claim one", "claim two", "claim three"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    change_summary: "DC1 browser fixture",
  }, 200);
  const thesisId = created.thesis.id;
  const begun = await jsonRequest(base, `/api/thesis/${thesisId}/begin-formalization`, "POST", {}, 200);
  const updated = await jsonRequest(base, `/api/thesis/${thesisId}`, "PUT", {
    title: begun.thesis.title,
    summary: begun.thesis.summary,
    status: "active",
    core_claims: begun.thesis.core_claims,
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    strategy: "SWING",
    expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
    free_notes: null,
    expected_revision: begun.thesis.current_revision,
    change_summary: "DC1 browser formal content",
  }, 200);
  const confirmed = await jsonRequest(base, `/api/thesis/${thesisId}/confirm`, "POST", {
    expected_revision: updated.thesis.current_revision,
  }, 200);
  const frozen = await jsonRequest(base, `/api/thesis/${thesisId}/freeze`, "POST", {
    expected_revision: confirmed.thesis.current_revision,
  }, 200);
  assert.equal(frozen.thesis.formal_state, "frozen");
  await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/thesis-binding`, "POST", {
    thesis_id: thesisId,
  }, 201);
  for (const [from, to] of [["DRAFT", "RESEARCHING"], ["RESEARCHING", "PRE-ENTRY"], ["PRE-ENTRY", "ACTIVE"]]) {
    await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/transitions`, "POST", {
      expected_status: from,
      to_status: to,
    }, 200);
  }
  return campaign;
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before Chromium E2E");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-dc1-decision-commit-e2e-"));
  let backendProc;
  let backendLog = "";
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
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
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
    await jsonRequest(backend, "/api/position/bootstrap-commit", "POST", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      positions: [{ code: "600519", name: "贵州茅台", shares: 100, cost_basis: 150000 }],
    }, 200);
    const campaign = await createFrozenCurrentThesis(backend);
    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const consoleErrors = [];
    const failedRequests = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("requestfailed", (request) => failedRequests.push({ url: request.url(), error: request.failure()?.errorText }));
    await page.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      return route.continue({ url: `${backend}${url.pathname}${url.search}` });
    });
    await page.goto(`${frontend}/campaigns/${campaign.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Formal Decision Review" }).waitFor();
    await page.getByLabel("Review by").fill("2026-08-30T10:00:00Z");
    await page.getByLabel("Strategy horizon").fill("10 至 30 交易日");
    await page.getByLabel("Key assumptions").fill("流动性保持稳定");
    await page.getByLabel("Event invalidation conditions").fill("业绩发生重大反转");
    await page.getByRole("button", { name: "Preview Proposal" }).click();
    await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
    assert.equal(existsSync(join(tempDataDir, "frozen_decisions.sqlite3")), false, "Preview must not create Frozen DB");
    const freeze = page.getByRole("button", { name: "Freeze Formal Decision" });
    assert.equal(await freeze.isEnabled(), false, "Freeze must be closed before checkbox");
    await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
    assert.equal(await freeze.isEnabled(), true);
    await freeze.click();
    await page.locator('[data-formal-decision-evaluation="EVALUATED"]').waitFor();
    const committedLine = await page.locator("[data-formal-decision-evaluation] p.font-mono").innerText();
    const committedId = committedLine.replace(/^decision_id：/, "").trim();
    assert.match(committedId, /^decision_[0-9a-f]{32}$/);
    const reread = await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}/decision-proposal/committed/${committedId}`);
    assert.equal(reread.formal_decision.evaluation, "EVALUATED");
    const inbox = await jsonRequest(backend, "/api/decision-inbox");
    const item = inbox.campaign_items.find((entry) => entry.campaign_id === campaign.campaign_id);
    assert.ok(item, "Decision Inbox must contain the active Campaign");
    assert.equal(item.last_frozen_decision.decision_id, committedId);
    assert.equal(item.formal_decision_evaluation, "EVALUATED");
    const expectedFontBlock = "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap";
    const unexpectedConsoleErrors = consoleErrors.filter((message) => !message.includes("ERR_NETWORK_ACCESS_DENIED"));
    const unexpectedFailedRequests = failedRequests.filter((request) => request.url !== expectedFontBlock);
    assert.equal(unexpectedConsoleErrors.length, 0, `unexpected browser console errors: ${JSON.stringify(unexpectedConsoleErrors)}`);
    assert.equal(unexpectedFailedRequests.length, 0, `unexpected failed requests: ${JSON.stringify(unexpectedFailedRequests)}`);
    if (failedRequests.length > 0) console.log(`[E2E] environment-only blocked asset: ${expectedFontBlock}`);
    console.log("[E2E] P0-DC1 Decision Commit vertical passed");
  } catch (error) {
    if (backendProc && !backendProc.killed) console.error(backendLog || "backend log unavailable");
    throw error;
  } finally {
    if (browser) await browser.close();
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (backendProc && !backendProc.killed) backendProc.kill();
    rmSync(tempDataDir, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
