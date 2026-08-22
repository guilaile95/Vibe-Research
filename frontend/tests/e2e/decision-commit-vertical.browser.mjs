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
import { request as httpRequest } from "node:http";
import { spawn, spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = path.join(root, "backend");
const frontendDist = path.join(root, "frontend", "dist");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** 每次新建 TCP 连接的代理请求（Connection: close，规避 stale keep-alive ECONNRESET）。 */
function proxyRequest(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const forwardHeaders = { ...headers, connection: "close" };
    delete forwardHeaders.host;
    const req = httpRequest(
      {
        hostname: target.hostname,
        port: target.port,
        path: `${target.pathname}${target.search}`,
        method,
        headers: forwardHeaders,
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () =>
          resolve({
            status: res.statusCode ?? 599,
            headers: Object.fromEntries(
              Object.entries(res.headers)
                .filter(([, value]) => value !== undefined)
                .map(([key, value]) => [key, Array.isArray(value) ? value.join(", ") : String(value)]),
            ),
            body: Buffer.concat(chunks),
          }),
        );
      },
    );
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

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
      // P1-SB1 Origin gate：page.route 转发保留 frontend Origin，
      // 与 decision-challenge.browser.mjs 相同，显式加入白名单。
      VR_ALLOW_ORIGINS: frontend,
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
    const notFoundResponses = [];
    let authorityFailure = false;
    let committedDecisionId = null;
    const readbackVariant = process.env.DCR1_READBACK_VARIANT || "valid";
    assert.ok(
      ["valid", "malformed", "decision-mismatch", "campaign-mismatch"].includes(readbackVariant),
      `unsupported DCR1_READBACK_VARIANT: ${readbackVariant}`,
    );
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("requestfailed", (request) => failedRequests.push({ url: request.url(), error: request.failure()?.errorText }));
    page.on("response", (response) => {
      if (response.status() === 404) notFoundResponses.push(new URL(response.url()).pathname);
    });
    // 与 decision-challenge.browser.mjs 相同方向的 node 侧代理：
    // route.continue({url}) 在当前 Chromium/Playwright 组合下会挂起；
    // undici fetch 连接池会复用已被 uvicorn keep-alive 超时关闭的连接
    // （表单交互跨越 5s 窗口后必现 ECONNRESET），因此用 node:http 每次
    // 新建连接并强制 Connection: close。
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      const contextPath = `/api/campaigns/${campaign.campaign_id}`;
      const committedPathPrefix = `${contextPath}/decision-proposal/committed/`;
      if (method === "GET" && url.pathname.startsWith(committedPathPrefix)) {
        committedDecisionId = url.pathname.slice(committedPathPrefix.length);
      }
      if (process.env.DF2_FORCE_CONTEXT_FALLBACK === "1" && method === "GET" && url.pathname === `${contextPath}/current-thesis`) {
        authorityFailure = true;
        const fallbackBody = { data: { campaign_id: campaign.campaign_id, thesis_id: "0123456789abcdef0123456789abcdef", binding: { thesis_revision_at_bind: 2, campaign_strategy_at_bind: "SWING", bound_at: "2026-08-22T00:00:00.000Z" }, formal_state: "confirmed", frozen_revision: null, ready: false, formal_status: "NOT_READY", reason: "NOT_FROZEN" } };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fallbackBody) });
        return;
      }
      try {
        const response = await proxyRequest(
          `${backend}${url.pathname}${url.search}`,
          method,
          request.headers(),
          method === "GET" || method === "HEAD" ? undefined : request.postDataBuffer(),
        );
        let responseBody = response.body;
        if (
          method === "GET"
          && url.pathname.startsWith(committedPathPrefix)
          && readbackVariant !== "valid"
          && response.status === 200
        ) {
          const payload = JSON.parse(response.body.toString("utf8"));
          if (readbackVariant === "malformed") {
            delete payload.data.formal_decision;
          } else if (readbackVariant === "decision-mismatch") {
            payload.data.committed.decision_id = `decision_${"e".repeat(32)}`;
          } else if (readbackVariant === "campaign-mismatch") {
            payload.data.committed.campaign_id = `campaign_${"f".repeat(32)}`;
          }
          responseBody = Buffer.from(JSON.stringify(payload));
        }
        const responseHeaders = { ...response.headers };
        if (responseBody !== response.body) {
          delete responseHeaders["content-length"];
          delete responseHeaders["Content-Length"];
        }
        await route.fulfill({
          status: response.status,
          headers: responseHeaders,
          body: responseBody,
        });
      } catch (error) {
        console.error(`[proxy] ${method} ${url.pathname} failed:`, error instanceof Error ? `${error.message} ${error.code ?? ""}` : error);
        await route.fulfill({
          status: 599,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "E2E backend proxy failed",
            error: error instanceof Error ? error.message : String(error),
          }),
        });
      }
    });
    await page.goto(`${frontend}/campaigns/${campaign.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Formal Decision Review" }).waitFor();
    if (process.env.DF2_FORCE_CONTEXT_FALLBACK === "1") {
      await page.locator('[data-horizon-source="MANUAL_FALLBACK"]').waitFor({ timeout: 30000 });
      assert.equal(authorityFailure, true, "fallback mode must intercept an authority request");
      assert.equal(await page.getByLabel("Strategy horizon").inputValue(), "", "fallback must not guess horizon");
      await page.getByLabel("Strategy horizon").fill("10 至 30 交易日");
    } else {
      await page.locator('[data-horizon-source="CURRENT_THESIS"]').waitFor({ timeout: 30000 });
      assert.equal(await page.getByLabel("Strategy horizon").inputValue(), "10–30 个交易日");
    }
    // P1-DF3：结构化 review boundary——用户显式选择本地时间，页面展示
    // 解析时区与最终 canonical ISO；断言 canonical 确实等于所选时刻。
    await page.getByLabel("Review by").fill("2026-08-30T10:00");
    const expectedCanonicalIso = await page.evaluate(() => new Date("2026-08-30T10:00").toISOString());
    const displayedCanonical = (await page.locator("[data-review-by-canonical]").innerText()).trim();
    assert.equal(displayedCanonical, expectedCanonicalIso, "displayed canonical ISO must equal the user-selected local time");
    assert.match(displayedCanonical, /Z$/);
    const tzText = await page.locator("[data-review-by-tz]").innerText();
    assert.match(tzText, /解析时区/);
    await page.getByLabel("Key assumptions").fill("流动性保持稳定");
    await page.getByLabel("Event invalidation conditions").fill("业绩发生重大反转");
    // P1-DF1：三视图结构化表单——普通用户零 JSON 完成输入
    await page.getByLabel("Asset stance").selectOption("SUPPORT");
    await page.getByLabel("Asset note").fill("高端白酒需求稳定");
    await page.getByLabel("Trade stance").selectOption("WAIT");
    await page.getByLabel("Trade note").fill("等待缩量回调再入场");
    await page.getByLabel("Portfolio constraint").fill("单笔风险不超过组合 2%");
    const previewResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes(
        `/api/campaigns/${campaign.campaign_id}/decision-proposal/preview`,
      )
    ), { timeout: 180000 });
    await page.getByRole("button", { name: "Preview Proposal" }).click();
    const previewResponse = await previewResponsePromise;
    assert.equal(previewResponse.ok(), true, `Preview failed: ${await previewResponse.text()}`);
    await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
    for (const viewName of ["asset_view", "trade_view", "portfolio_view"]) {
      await page.locator(`[data-view-form="${viewName}"]`).waitFor();
    }
    const criticalDataCard = page.locator("[data-critical-data-state]").first();
    await criticalDataCard.waitFor();
    const previewCriticalData = {
      state: await criticalDataCard.getAttribute("data-critical-data-state"),
      evaluation: await criticalDataCard.getAttribute("data-critical-data-evaluation"),
    };
    assert.ok(previewCriticalData.state, "Preview must expose Critical Data state");
    assert.ok(previewCriticalData.evaluation, "Preview must expose Critical Data evaluation");
    assert.notEqual(previewCriticalData.evaluation, "HEALTHY", "Critical Data must use authority evaluation vocabulary");
    assert.equal(existsSync(join(tempDataDir, "frozen_decisions.sqlite3")), false, "Preview must not create Frozen DB");
    const freeze = page.getByRole("button", { name: "Freeze Formal Decision" });
    assert.equal(await freeze.isEnabled(), false, "Freeze must be closed before checkbox");
    await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
    assert.equal(await freeze.isEnabled(), true);
    await freeze.click();
    await page.waitForFunction(() => document.querySelector('[data-formal-decision-evaluation]') !== null || document.querySelector('[role="alert"]') !== null, null, { timeout: 180000 });
    assert.ok(committedDecisionId, "durable committed GET must be observed");
    assert.match(committedDecisionId, /^decision_[0-9a-f]{32}$/);
    const committedSuccess = page.locator('[data-formal-decision-evaluation="EVALUATED"]');
    if (readbackVariant === "valid") {
      await committedSuccess.waitFor({ timeout: 30000 });
      const committedLine = await page.locator("[data-formal-decision-evaluation] p.font-mono").innerText();
      const committedId = committedLine.replace(/^decision_id：/, "").trim();
      assert.equal(committedId, committedDecisionId);
    } else {
      assert.equal(await committedSuccess.count(), 0, `${readbackVariant} must not render committed success UI`);
      const readbackError = await page.locator('[role="alert"]').innerText();
      assert.match(readbackError, /COMMITTED_DECISION_READ_ERROR/);
    }
    const reread = await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}/decision-proposal/committed/${committedDecisionId}`);
    assert.equal(reread.formal_decision.evaluation, "EVALUATED");
    assert.equal(reread.committed.decision_id, committedDecisionId);
    assert.equal(reread.committed.campaign_id, campaign.campaign_id);
    assert.equal(reread.critical_data.critical_data_state, previewCriticalData.state);
    assert.equal(reread.critical_data.critical_data_evaluation, previewCriticalData.evaluation);
    assert.equal(reread.critical_data.campaign_id, campaign.campaign_id);
    assert.equal(reread.critical_data.security_code, "600519");
    assert.equal(reread.critical_data.strategy, "SWING");
    const inbox = await jsonRequest(backend, "/api/decision-inbox");
    const item = inbox.campaign_items.find((entry) => entry.campaign_id === campaign.campaign_id);
    assert.ok(item, "Decision Inbox must contain the active Campaign");
    assert.equal(item.last_frozen_decision.decision_id, committedDecisionId);
    assert.equal(item.formal_decision_evaluation, "EVALUATED");
    assert.equal(item.critical_data.critical_data_state, reread.critical_data.critical_data_state);
    assert.equal(item.critical_data.critical_data_evaluation, reread.critical_data.critical_data_evaluation);
    assert.equal(item.critical_data.campaign_id, reread.critical_data.campaign_id);
    assert.equal(item.critical_data.security_code, reread.critical_data.security_code);
    assert.equal(item.critical_data.strategy, reread.critical_data.strategy);
    const expectedFontBlock = "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap";
    const expectedChallenge404 = `/api/campaigns/${campaign.campaign_id}/decision-challenge`;
    assert.deepEqual(notFoundResponses, [expectedChallenge404], "only the optional challenge lookup may be 404");
    const unexpectedConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("ERR_NETWORK_ACCESS_DENIED")
        && !message.includes("Failed to load resource: the server responded with a status of 404 (Not Found)"),
    );
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
    if (backendProc && !backendProc.killed) {
      if (process.platform === "win32") {
        spawnSync("taskkill", ["/PID", String(backendProc.pid), "/T", "/F"], {
          stdio: "ignore",
          windowsHide: true,
        });
      } else {
        backendProc.kill();
      }
      await new Promise((resolve) => backendProc.once("close", resolve));
    }
    rmSync(tempDataDir, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
