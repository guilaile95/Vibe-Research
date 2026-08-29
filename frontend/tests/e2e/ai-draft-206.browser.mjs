import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { seedActiveCampaign } from "./campaign-active-fixture.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = path.join(root, "backend");
const frontendDist = path.join(root, "frontend", "dist");
const evidenceDir = path.join(root, "gui-test-screenshots");
mkdirSync(evidenceDir, { recursive: true });
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

async function waitHttp(url, attempts = 160) {
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

function systemChromePath() {
  const candidates = [
    process.env.SYSTEM_CHROME,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ];
  return candidates.find((candidate) => candidate && existsSync(candidate));
}

async function jsonRequest(base, pathname, method = "GET", body, expected = 200) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload;
  try { payload = JSON.parse(text); } catch { payload = { raw: text }; }
  assert.equal(response.status, expected, `${method} ${pathname}: ${text}`);
  return payload.data;
}

async function createFrozenCurrentThesis(base, title, env) {
  const campaign = await jsonRequest(base, "/api/campaigns", "POST", {
    security_code: "600519",
    strategy: "SWING",
  }, 201);
  const created = await jsonRequest(base, "/api/thesis", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    title,
    summary: "isolated AI Draft browser fixture",
    core_claims: ["claim one", "claim two", "claim three"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    change_summary: "#206 browser fixture",
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
    change_summary: "#206 browser formal content",
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
  for (const [from, to] of [["DRAFT", "RESEARCHING"], ["RESEARCHING", "PRE-ENTRY"]]) {
    await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/transitions`, "POST", {
      expected_status: from,
      to_status: to,
    }, 200);
  }
  seedActiveCampaign(backendDir, env, campaign.campaign_id);
  return campaign;
}

function startMockLlm(port) {
  const generated = {
    asset_view: { view: "ASSET", stance: "SUPPORT", note: "AI asset support" },
    trade_view: { view: "TRADE", stance: "WAIT", note: "AI trade wait" },
    portfolio_view: { view: "PORTFOLIO", constraint: "AI portfolio constraint" },
    review_by: "2026-09-15T12:00:00.000000Z",
    key_assumptions: ["AI assumption one", "AI assumption two"],
    event_invalidation_conditions: ["AI invalidation"],
    strategy_horizon: "AI horizon 2-4 weeks",
  };
  const server = createServer((request, response) => {
    if (request.method !== "POST" || !request.url?.endsWith("/chat/completions")) {
      response.writeHead(404);
      response.end();
      return;
    }
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      const content = JSON.stringify(generated);
      const stream = [
        `data: ${JSON.stringify({ choices: [{ delta: { role: "assistant", content } }] })}`,
        "data: [DONE]",
        "",
      ].join("\n");
      response.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "close",
      });
      response.end(stream);
    });
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve({ server, generated }));
  });
}

function bodyHasProvenance(body, view, origin) {
  return new RegExp(`${view}\\s+${origin}`).test(body);
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before browser E2E");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-206-ai-draft-e2e-"));
  let backendProc;
  let backendLog = "";
  let staticServer;
  let mockLlmServer;
  let browser;
  try {
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const mockPort = await freePort();
    const backend = `http://127.0.0.1:${backendPort}`;
    const frontend = `http://127.0.0.1:${frontendPort}`;
    const mockLlm = `http://127.0.0.1:${mockPort}/v1`;
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
    const campaign = await createFrozenCurrentThesis(backend, "#206 AI Draft browser fixture", env);
    await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}`);
    const baselineCampaigns = await jsonRequest(backend, "/api/campaigns");
    const baselineTransitions = await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}/transitions`);
    const baselineTrades = await jsonRequest(backend, "/api/trades");
    const frozenDb = join(tempDataDir, "frozen_decisions.sqlite3");
    const challengeDb = join(tempDataDir, "decision_challenges.sqlite3");
    const frozenDbBefore = existsSync(frozenDb);
    const challengeDbBefore = existsSync(challengeDb);

    ({ server: mockLlmServer } = await startMockLlm(mockPort));
    staticServer = await startStaticServer(frontendDist, frontendPort);
    const executablePath = systemChromePath();
    assert.ok(executablePath, "system Chrome executable not found");
    browser = await chromium.launch({ headless: true, executablePath });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, timezoneId: "UTC" });
    // Environment preparation only: configure a dummy local model endpoint in isolated browser storage.
    await context.addInitScript(({ mockLlm }) => {
      localStorage.setItem("vr-llm", JSON.stringify({
        provider: "api-compatible",
        baseURL: mockLlm,
        apiKey: "local-test-key",
        model: "local-test-model",
      }));
    }, { mockLlm });
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const failedRequests = [];
    const apiTrace = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    page.on("requestfailed", (request) => failedRequests.push({ url: request.url(), error: request.failure()?.errorText }));
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      apiTrace.push(`${method} ${url.pathname}${url.search}`);
      try {
        const response = await fetch(`${backend}${url.pathname}${url.search}`, {
          method,
          headers: request.headers(),
          body: method === "GET" || method === "HEAD" ? undefined : request.postDataBuffer(),
        });
        await route.fulfill({
          status: response.status,
          headers: Object.fromEntries(response.headers.entries()),
          body: Buffer.from(await response.arrayBuffer()),
        });
      } catch (error) {
        await route.fulfill({ status: 599, contentType: "application/json", body: JSON.stringify({ detail: "E2E proxy failed" }) });
      }
    });

    console.log("Environment preparation is complete; formal testing is beginning.");
    await page.goto(`${frontend}/campaigns/${campaign.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Formal Decision Review" }).waitFor();
    await page.locator(`[data-decision-proposal-page="${campaign.campaign_id}"]`).waitFor();
    await page.locator('[data-decision-context="ready"]').waitFor();
    await page.screenshot({ path: join(evidenceDir, "t0-context.png"), fullPage: true });
    assert.equal(await page.locator("[data-context-security]").innerText(), "600519");
    assert.equal(await page.locator("[data-context-strategy]").innerText(), "SWING");
    const contextThesisStatus = await page.locator("[data-context-thesis-status]").innerText();
    assert.notEqual(contextThesisStatus, "UNKNOWN");
    assert.notEqual(contextThesisStatus, "UNAVAILABLE");

    const generationResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes(`/api/campaigns/${campaign.campaign_id}/ai-draft/generate`)
    ), { timeout: 180000 });
    await page.getByRole("button", { name: "Generate AI Draft" }).click();
    const generationResponse = await generationResponsePromise;
    assert.equal(generationResponse.status(), 200, await generationResponse.text());
    const generationBody = await generationResponse.json();
    const generation = generationBody.data;
    assert.equal(generation.draft_status, "AI_DRAFT");
    assert.equal(generation.proposal_status, "UNCOMMITTED");
    assert.match(generation.draft_id, /^campaign_ai_draft_[0-9a-f]{32}$/);
    await page.locator('[data-ai-draft-status="UNCOMMITTED"]').waitFor();
    await page.screenshot({ path: join(evidenceDir, "t1-ai-draft.png"), fullPage: true });
    assert.equal(await page.getByLabel("Asset stance").inputValue(), "SUPPORT");
    assert.equal(await page.getByLabel("Trade stance").inputValue(), "WAIT");
    assert.equal(await page.getByLabel("Strategy horizon").inputValue(), "AI horizon 2-4 weeks");
    assert.equal(await page.getByLabel("Key assumptions").inputValue(), "AI assumption one\nAI assumption two");
    assert.equal(await page.getByLabel("Event invalidation conditions").inputValue(), "AI invalidation");
    assert.match(await page.locator('[data-ai-draft-status="UNCOMMITTED"]').innerText(), /AI DRAFT \/ UNCOMMITTED/);

    await page.getByRole("button", { name: "Apply again" }).click();
    await page.screenshot({ path: join(evidenceDir, "t1b-applied.png"), fullPage: true });
    assert.equal(await page.getByLabel("Asset stance").inputValue(), "SUPPORT");
    assert.equal(await page.getByLabel("Trade stance").inputValue(), "WAIT");
    assert.match(await page.getByLabel("Key assumptions").inputValue(), /\n/);

    const previewResponsePromise = () => page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes(`/api/campaigns/${campaign.campaign_id}/decision-proposal/preview`)
    ), { timeout: 180000 });
    let previewResponse = previewResponsePromise();
    await page.getByRole("button", { name: "Preview Proposal" }).click();
    let preview = await previewResponse;
    assert.equal(preview.status(), 200, await preview.text());
    await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
    await page.locator('[data-challenge-state="ABSENT"]').waitFor();
    await page.screenshot({ path: join(evidenceDir, "t2-model-proposal.png"), fullPage: true });
    let proposalBody = await page.locator('[data-proposal-status="UNCOMMITTED"]').innerText();
    assert.ok(bodyHasProvenance(proposalBody, "asset_view", "MODEL_PROPOSAL"), proposalBody);
    assert.ok(bodyHasProvenance(proposalBody, "trade_view", "MODEL_PROPOSAL"), proposalBody);
    assert.ok(bodyHasProvenance(proposalBody, "portfolio_view", "MODEL_PROPOSAL"), proposalBody);
    assert.match(proposalBody, /UNCOMMITTED/);

    await page.getByLabel("Trade stance").selectOption("OPPOSE");
    await page.screenshot({ path: join(evidenceDir, "t3-edited-user-view.png"), fullPage: true });
    assert.equal(await page.getByLabel("Trade stance").inputValue(), "OPPOSE");
    previewResponse = previewResponsePromise();
    await page.getByRole("button", { name: "Preview Proposal" }).click();
    preview = await previewResponse;
    assert.equal(preview.status(), 200, await preview.text());
    await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
    await page.locator('[data-challenge-state="ABSENT"]').waitFor();
    await page.screenshot({ path: join(evidenceDir, "t4-user-draft-preview.png"), fullPage: true });
    proposalBody = await page.locator('[data-proposal-status="UNCOMMITTED"]').innerText();
    assert.ok(bodyHasProvenance(proposalBody, "asset_view", "MODEL_PROPOSAL"), proposalBody);
    assert.ok(bodyHasProvenance(proposalBody, "trade_view", "USER_DRAFT"), proposalBody);
    assert.ok(bodyHasProvenance(proposalBody, "portfolio_view", "MODEL_PROPOSAL"), proposalBody);
    assert.equal(await page.locator('[data-proposal-status="UNCOMMITTED"]').count(), 1);
    assert.equal(await page.locator('[data-formal-decision-evaluation]').count(), 0);
    assert.equal(await page.locator('[data-challenge-id]').getAttribute("data-challenge-id"), "");

    // Low-cost fail-closed witness check: mutate only the client-supplied witness fingerprint.
    const stalePayload = {
      ...generation.generated_fields,
      draft_witness: { ...generation.draft_witness, context_fingerprint: "f".repeat(64) },
    };
    const staleResponse = await fetch(`${backend}/api/campaigns/${campaign.campaign_id}/decision-proposal/preview`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(stalePayload),
    });
    const staleText = await staleResponse.text();
    assert.equal(staleResponse.status, 409, staleText);

    const afterCampaign = await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}`);
    const afterCampaigns = await jsonRequest(backend, "/api/campaigns");
    const afterTransitions = await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}/transitions`);
    const afterTrades = await jsonRequest(backend, "/api/trades");
    assert.deepEqual(afterCampaign, await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}`));
    assert.deepEqual(afterCampaign, baselineCampaigns.find((item) => item.campaign_id === campaign.campaign_id));
    assert.deepEqual(afterCampaigns, baselineCampaigns);
    assert.deepEqual(afterTransitions, baselineTransitions);
    assert.deepEqual(afterTrades, baselineTrades);
    assert.equal(existsSync(frozenDb), frozenDbBefore, "AI Draft/Preview must not create Frozen Decision DB");
    assert.equal(existsSync(challengeDb), challengeDbBefore, "AI Draft/Preview must not create Challenge DB");
    const mutatingAfterBaseline = apiTrace.filter((entry) => entry.startsWith("POST ") && (
      entry.includes("/decision-proposal/commit")
      || entry.includes("/trades")
      || entry === "POST /api/campaigns"
      || entry.includes("/transitions")
      || entry.includes("/decision-challenge/finalize")
    ));
    assert.deepEqual(mutatingAfterBaseline, []);

    console.log(JSON.stringify({
      campaignId: campaign.campaign_id,
      draftId: generation.draft_id,
      proposalStatus: generation.proposal_status,
      modelUntouched: true,
      editedTradeUserDraft: true,
      previewUncommitted: true,
      staleWitnessStatus: staleResponse.status,
      campaignSideEffect: false,
      formalDecisionSideEffect: false,
      frozenDecisionSideEffect: false,
      tradeSideEffect: false,
      apiTrace,
      consoleErrors,
      pageErrors,
      failedRequests,
      evidenceDir,
    }, null, 2));
    await context.close();
  } catch (error) {
    console.error(backendLog || "backend log unavailable");
    throw error;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (mockLlmServer) await new Promise((resolve) => mockLlmServer.close(resolve));
    if (backendProc && !backendProc.killed) backendProc.kill();
    try { rmSync(tempDataDir, { recursive: true, force: true }); } catch (cleanupError) {
      console.error(`temporary data cleanup warning: ${cleanupError?.message || cleanupError}`);
    }
  }
}

run().catch((error) => {
  console.error(error?.stack || error);
  process.exitCode = 1;
});
