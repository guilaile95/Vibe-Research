/** Campaign AI Draft → editable Proposal → deterministic Preview → Freeze. */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
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
      // still starting
    }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function proxyRequest(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const forwardHeaders = { ...headers, connection: "close" };
    delete forwardHeaders.host;
    const request = httpRequest({
      hostname: target.hostname,
      port: target.port,
      path: `${target.pathname}${target.search}`,
      method,
      headers: forwardHeaders,
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolve({
        status: response.statusCode ?? 599,
        headers: Object.fromEntries(Object.entries(response.headers)
          .filter(([, value]) => value !== undefined)
          .map(([key, value]) => [key, Array.isArray(value) ? value.join(", ") : String(value)])),
        body: Buffer.concat(chunks),
      }));
    });
    request.on("error", reject);
    if (body) request.write(body);
    request.end();
  });
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
    let target = join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      response.writeHead(403).end("forbidden");
      return;
    }
    if (!existsSync(target)) target = join(dir, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function startFakeLlm(port) {
  const payload = {
    asset_view: { view: "ASSET", stance: "SUPPORT", note: "Current Thesis 支持继续观察资产质量" },
    trade_view: { view: "TRADE", stance: "SUPPORT", note: "模型倾向支持，但必须服从 deterministic envelope" },
    portfolio_view: { view: "PORTFOLIO", constraint: "不扩大当前单一持仓风险暴露" },
    key_assumptions: ["Current Thesis 的核心假设继续成立"],
    event_invalidation_conditions: ["核心经营事实出现反向变化"],
    limitations: ["Critical Data 中的 UNKNOWN 不代表安全"],
  };
  const server = createServer((request, response) => {
    if (request.method !== "POST" || request.url !== "/v1/chat/completions") {
      response.writeHead(404).end("not found");
      return;
    }
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      assert.equal(body.stream, true);
      assert.equal(body.model, "fake-decision-model");
      const text = JSON.stringify(payload);
      response.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "close",
      });
      response.write(`data: ${JSON.stringify({ choices: [{ delta: { content: text } }] })}\n\n`);
      response.end("data: [DONE]\n\n");
    });
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
  for (const base of [process.env.PLAYWRIGHT_CHROMIUM_PATH, join(process.env.LOCALAPPDATA || "", "ms-playwright"), join(process.env.HOME || "", ".cache", "ms-playwright")]) {
    if (!base || !existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const found = [join(base, entry, "chrome-win64", "chrome.exe"), join(base, entry, "chrome-linux", "chrome")]
        .find((candidate) => existsSync(candidate));
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

async function createCampaignAndCurrentThesis(base) {
  const campaign = await jsonRequest(base, "/api/campaigns", "POST", { security_code: "600519", strategy: "SWING" }, 201);
  const evidence = await jsonRequest(base, "/api/evidence", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    evidence_type: "financial_filing",
    claim: "经营现金流仍覆盖投入",
    source_title: "经营现金流证据",
    source_url: "https://example.com/evidence",
    source_date: "2026-08-20",
    accessed_at: "2026-08-24T00:00:00.000Z",
    classification: "fact",
    confidence: "high",
  });
  let thesis = await jsonRequest(base, "/api/thesis", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    title: "AI Draft Chromium Thesis",
    summary: "同一 Campaign 的 Current Thesis",
    core_claims: ["claim one", "claim two", "claim three"],
    catalysts: [], risks: [], invalidation_conditions: [], change_summary: "browser fixture",
  });
  thesis = await jsonRequest(base, `/api/thesis/${thesis.thesis.id}/evidence`, "POST", {
    evidence_id: evidence.id,
    stance: "support",
    expected_revision: thesis.thesis.current_revision,
    change_summary: "link browser evidence",
  });
  thesis = await jsonRequest(base, `/api/thesis/${thesis.thesis.id}/begin-formalization`, "POST", { expected_revision: thesis.thesis.current_revision });
  thesis = await jsonRequest(base, `/api/thesis/${thesis.thesis.id}`, "PUT", {
    title: thesis.thesis.title,
    summary: thesis.thesis.summary,
    status: "active",
    core_claims: thesis.thesis.core_claims,
    catalysts: [], risks: [], invalidation_conditions: [],
    strategy: "SWING",
    expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
    free_notes: null,
    expected_revision: thesis.thesis.current_revision,
    change_summary: "formal browser content",
  });
  thesis = await jsonRequest(base, `/api/thesis/${thesis.thesis.id}/confirm`, "POST", { expected_revision: thesis.thesis.current_revision });
  thesis = await jsonRequest(base, `/api/thesis/${thesis.thesis.id}/freeze`, "POST", { expected_revision: thesis.thesis.current_revision });
  await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/thesis-binding`, "POST", { thesis_id: thesis.thesis.id }, 201);
  for (const [from, to] of [["DRAFT", "RESEARCHING"], ["RESEARCHING", "PRE-ENTRY"], ["PRE-ENTRY", "ACTIVE"]]) {
    await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/transitions`, "POST", { expected_status: from, to_status: to });
  }
  return campaign;
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before Chromium E2E");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-decision-ai-draft-e2e-"));
  let backendProc;
  let backendLog = "";
  let frontendServer;
  let llmServer;
  let browser;
  try {
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const llmPort = await freePort();
    const backend = `http://127.0.0.1:${backendPort}`;
    const frontend = `http://127.0.0.1:${frontendPort}`;
    const py = pythonConfig();
    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env: {
        ...process.env,
        VR_DATA_DIR: tempDataDir,
        VR_REPORTS_DIR: tempDataDir,
        VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
        VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
        VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
        VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
        VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
        VIBE_RESEARCH_DECISION_DRAFT_DB: join(tempDataDir, "decision_drafts.sqlite3"),
        VR_ALLOW_ORIGINS: frontend,
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);
    llmServer = await startFakeLlm(llmPort);
    await jsonRequest(backend, "/api/position/bootstrap-commit", "POST", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      positions: [{ code: "600519", name: "贵州茅台", shares: 100, cost_basis: 150000 }],
    });
    const campaign = await createCampaignAndCurrentThesis(backend);
    frontendServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const consoleErrors = [];
    const failedRequests = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("requestfailed", (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText || ""}`));
    await page.addInitScript(({ llmPort: port }) => {
      localStorage.setItem("vr-llm", JSON.stringify({
        provider: "fake-provider",
        baseURL: `http://127.0.0.1:${port}/v1`,
        apiKey: "fake-api-key",
        model: "fake-decision-model",
      }));
    }, { llmPort });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const response = await proxyRequest(
        `${backend}${url.pathname}${url.search}`,
        request.method(),
        request.headers(),
        request.method() === "GET" || request.method() === "HEAD" ? undefined : request.postDataBuffer(),
      );
      await route.fulfill({ status: response.status, headers: response.headers, body: response.body });
    });

    await page.goto(`${frontend}/campaigns/${campaign.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await page.locator('[data-horizon-source="CURRENT_THESIS"]').waitFor({ timeout: 30000 });
    assert.equal(await page.getByLabel("Asset note").inputValue(), "");

    const generatedResponse = page.waitForResponse((response) => response.url().includes(`/api/campaigns/${campaign.campaign_id}/decision-draft`) && response.request().method() === "POST", { timeout: 180000 });
    await page.locator('[data-action="generate-ai-decision-draft"]').click();
    assert.equal((await generatedResponse).ok(), true);
    await page.locator('[data-ai-draft-state="READY"]').waitFor();
    assert.equal(await page.getByLabel("Asset note").inputValue(), "", "generation must not mutate the user form");
    assert.equal(existsSync(join(tempDataDir, "frozen_decisions.sqlite3")), false, "draft generation must not write Formal Decision");

    await page.locator('[data-action="apply-ai-decision-draft"]').click();
    await page.locator('[data-ai-draft-state="APPLIED"]').waitFor();
    assert.equal(await page.getByLabel("Asset note").inputValue(), "Current Thesis 支持继续观察资产质量");
    await page.getByLabel("Trade note").fill("用户编辑：继续等待确定性条件");
    await page.getByLabel("Review by").fill("2026-08-30T10:00");

    const previewResponse = page.waitForResponse((response) => response.url().includes("/decision-proposal/preview") && response.request().method() === "POST", { timeout: 180000 });
    await page.getByRole("button", { name: "Preview Proposal" }).click();
    const previewHttp = await previewResponse;
    assert.equal(previewHttp.ok(), true, await previewHttp.text());
    const preview = (await previewHttp.json()).data;
    assert.equal(preview.proposal.view_provenance.asset_view.view_origin, "MODEL_PROPOSAL");
    assert.equal(preview.proposal.view_provenance.trade_view.view_origin, "USER_DRAFT");
    assert.equal(preview.proposal.view_provenance.portfolio_view.view_origin, "MODEL_PROPOSAL");
    assert.ok(["WAIT", "HOLD", "RESEARCH MORE"].includes(preview.proposal.next_best_action));
    assert.equal(preview.proposal.action_envelope.allowed_actions.includes("BUY NOW"), false, "AI SUPPORT must not widen deterministic envelope");
    assert.equal(await page.locator('[data-view-origin="MODEL_PROPOSAL"]').count(), 2);
    assert.equal(await page.locator('[data-view-origin="USER_DRAFT"]').count(), 1);

    const freeze = page.getByRole("button", { name: "Freeze Formal Decision" });
    assert.equal(await freeze.isEnabled(), false);
    await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
    await freeze.click();
    await page.locator('[data-formal-decision-evaluation="EVALUATED"]').waitFor({ timeout: 180000 });
    const decisionLine = await page.locator('[data-formal-decision-evaluation="EVALUATED"] p.font-mono').innerText();
    const decisionId = decisionLine.replace(/^decision_id：/, "").trim();
    assert.match(decisionId, /^decision_[0-9a-f]{32}$/);
    const reread = await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}/decision-proposal/committed/${decisionId}`);
    assert.ok(reread.committed.source_refs.some((ref) => ref.startsWith("decision_ai_draft:")));
    assert.ok(reread.committed.source_refs.includes("decision_ai_model:fake-provider/fake-decision-model"));
    const trades = await jsonRequest(backend, "/api/trades");
    assert.equal(trades.items.length, 0, "Formal Decision Freeze must not create a Trade");
    assert.deepEqual(consoleErrors, []);
    assert.deepEqual(failedRequests, []);
    console.log("decision-ai-draft.browser: PASS");
  } catch (error) {
    console.error(backendLog);
    throw error;
  } finally {
    if (browser) await browser.close();
    if (frontendServer) await new Promise((resolve) => frontendServer.close(resolve));
    if (llmServer) await new Promise((resolve) => llmServer.close(resolve));
    if (backendProc) {
      backendProc.kill();
      await Promise.race([new Promise((resolve) => backendProc.once("exit", resolve)), sleep(3000)]);
    }
    rmSync(tempDataDir, { recursive: true, force: true });
  }
}

await run();
