/**
 * P0-CT1 Current Thesis Product Activation — Real FastAPI + Playwright E2E.
 *
 * 使用独立临时数据目录与真实前后端，证明每一步都由用户显式触发：
 * Campaign → Formal DRAFT → Confirm → Freeze → immutable binding → Current Thesis。
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitHttp(url, attempts = 100) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      // Backend is still starting.
    }
    await sleep(300);
  }
  throw new Error(`timeout waiting ${url}`);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
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

function getPythonConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, extraArgs: ["-m", "uvicorn"] };
  return process.platform === "win32"
    ? { cmd: "py", extraArgs: ["-3", "-m", "uvicorn"] }
    : { cmd: "python3", extraArgs: ["-m", "uvicorn"] };
}

function findChromium() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of candidates) {
    if (!base || !existsSync(base)) continue;
    try {
      for (const dir of readdirSync(base)) {
        if (!dir.startsWith("chromium-") || dir.includes("headless")) continue;
        for (const executable of [
          join(base, dir, "chrome-win64", "chrome.exe"),
          join(base, dir, "chrome-linux", "chrome"),
          join(base, dir, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
        ]) {
          if (existsSync(executable)) return executable;
        }
      }
    } catch {
      // Try the next Playwright cache.
    }
  }
  return undefined;
}

async function postJson(baseUrl, pathname, body, expectedStatus) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expectedStatus, `${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

async function postEmpty(baseUrl, pathname, expectedStatus) {
  const response = await fetch(`${baseUrl}${pathname}`, { method: "POST" });
  const payload = await response.json();
  assert.equal(response.status, expectedStatus, `${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

async function putJson(baseUrl, pathname, body, expectedStatus) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expectedStatus, `${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

async function getJson(baseUrl, pathname, expectedStatus = 200) {
  const response = await fetch(`${baseUrl}${pathname}`);
  const payload = await response.json();
  assert.equal(response.status, expectedStatus, `${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

async function runE2E() {
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-current-thesis-e2e-"));
  let backendProc;
  let staticServer;
  let browser;

  try {
    const backendPort = await getFreePort();
    const frontendPort = await getFreePort();
    const backendUrl = `http://127.0.0.1:${backendPort}`;
    const frontendUrl = `http://127.0.0.1:${frontendPort}`;
    const py = getPythonConfig();
    const env = {
      ...process.env,
      VR_ALLOW_ORIGINS: frontendUrl,
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
      VIBE_RESEARCH_TRADE_LEDGER_DB: path.join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: path.join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: path.join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: path.join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: path.join(tempDataDir, "frozen_decisions.sqlite3"),
      PYTHONUNBUFFERED: "1",
    };

    backendProc = spawn(
      py.cmd,
      [...py.extraArgs, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
      { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"] },
    );
    backendProc.stdout.on("data", (chunk) => process.stdout.write(`[backend] ${chunk}`));
    backendProc.stderr.on("data", (chunk) => process.stderr.write(`[backend] ${chunk}`));
    await waitHttp(`${backendUrl}/api/health`);

    await postJson(backendUrl, "/api/position/bootstrap-commit", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      positions: [{ code: "600519", name: "贵州茅台", shares: 100, cost_basis: 150000 }],
    }, 200);
    const campaign = await postJson(
      backendUrl,
      "/api/campaigns",
      { security_code: "600519", strategy: "SWING" },
      201,
    );
    // Fixture only: an existing, matching Thesis must remain a visible
    // candidate and must never become the Campaign binding implicitly.
    const candidate = await postJson(backendUrl, "/api/thesis", {
      subject_type: "stock",
      subject_id: "600519",
      title: "已有唯一候选 Formal Thesis",
      summary: "只用于验证候选不会自动绑定。",
      core_claims: [],
      catalysts: [],
      risks: [],
      invalidation_conditions: [],
      change_summary: "创建唯一候选测试夹具",
    }, 200);

    staticServer = await startStaticServer(frontendDist, frontendPort);
    browser = await chromium.launch({ executablePath: findChromium(), headless: true });
    const page = await browser.newPage();
    const consoleErrors = [];
    const notFoundResponses = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("response", (response) => {
      if (response.status() !== 404) return;
      const request = response.request();
      const url = new URL(response.url());
      notFoundResponses.push({ method: request.method(), pathname: url.pathname });
    });

    const calls = { begin: 0, confirm: 0, freeze: 0, bind: 0 };
    let projectionMode = "normal";
    const decisionProposalMutations = [];
    page.on("request", (request) => {
      if (request.method() !== "POST") return;
      const pathname = new URL(request.url()).pathname;
      if (/\/api\/campaigns\/[^/]+\/decision-proposal\/(preview|commit)$/.test(pathname)) {
        decisionProposalMutations.push(pathname);
      }
    });
    const proxyToBackend = (route) => {
      const url = new URL(route.request().url());
      return route.continue({ url: `${backendUrl}${url.pathname}${url.search}` });
    };
    await page.route("**/api/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (projectionMode === "binding-mismatch" && pathname.endsWith("/thesis-binding") && route.request().method() === "GET") {
        const binding = await getJson(backendUrl, `/api/campaigns/${campaign.campaign_id}/thesis-binding`);
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: { ...binding, campaign_id: "other-campaign" } }),
        });
        return;
      }
      if (projectionMode === "unknown" && pathname.endsWith("/current-thesis") && route.request().method() === "GET") {
        const current = await getJson(backendUrl, `/api/campaigns/${campaign.campaign_id}/current-thesis`);
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: { ...current, effective_state: "UNKNOWN" } }),
        });
        return;
      }
      if (projectionMode === "error" && pathname.endsWith("/current-thesis") && route.request().method() === "GET") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "projection mismatch" }),
        });
        return;
      }
      await proxyToBackend(route);
    });
    await page.route("**/api/thesis/*/begin-formalization", async (route) => {
      calls.begin += 1;
      await proxyToBackend(route);
    });
    await page.route("**/api/thesis/*/confirm", async (route) => {
      calls.confirm += 1;
      await proxyToBackend(route);
    });
    await page.route("**/api/thesis/*/freeze", async (route) => {
      calls.freeze += 1;
      await proxyToBackend(route);
    });
    await page.route("**/api/campaigns/*/thesis-binding", async (route) => {
      if (route.request().method() === "POST") calls.bind += 1;
      await proxyToBackend(route);
    });

    await page.goto(`${frontendUrl}/decision-inbox`, { waitUntil: "networkidle" });
    const thesisCard = page.locator(`[data-campaign-thesis="${campaign.campaign_id}"]`);
    await thesisCard.getByText("尚未绑定", { exact: true }).waitFor();
    await thesisCard.getByText(candidate.thesis.title, { exact: true }).waitFor();
    assert.equal(await thesisCard.getByRole("link", { name: "继续设置" }).count(), 1);
    assert.deepEqual(calls, { begin: 0, confirm: 0, freeze: 0, bind: 0 });

    // Negative gate 1: campaign_id only locates the real Campaign; a Thesis
    // for another security must not be allowed to start Formal lifecycle.
    const campaignQuery = new URLSearchParams({
      campaign_id: campaign.campaign_id,
      security_code: campaign.security_code,
      strategy: campaign.strategy,
      return_to: "/decision-inbox",
    }).toString();
    const wrongSecurity = await postJson(backendUrl, "/api/thesis", {
      subject_type: "stock",
      subject_id: "000001",
      title: "错误证券 Thesis",
      summary: "用于验证 Campaign/Thesis subject fail-closed。",
      core_claims: [],
      catalysts: [],
      risks: [],
      invalidation_conditions: [],
      change_summary: "创建错误证券测试夹具",
    }, 200);
    await page.goto(`${frontendUrl}/thesis/${wrongSecurity.thesis.id}?${campaignQuery}`, { waitUntil: "networkidle" });
    await page.getByRole("alert").filter({ hasText: "当前 Thesis 与真实 Campaign 的证券或策略不一致" }).waitFor();
    const wrongSecurityBegin = page.getByRole("button", { name: "开始 Formal 化" });
    await wrongSecurityBegin.waitFor();
    assert.equal(await wrongSecurityBegin.isDisabled(), true);
    const wrongSecurityAfter = await getJson(backendUrl, `/api/thesis/${wrongSecurity.thesis.id}`);
    assert.equal(wrongSecurityAfter.thesis.formal_state, null);
    assert.deepEqual(calls, { begin: 0, confirm: 0, freeze: 0, bind: 0 });

    // Negative gate 2: same security but conflicting non-null strategy must
    // fail closed at Confirm, Freeze and Bind. Backend-only fixture mutation is
    // intentional here so each browser gate can be exercised independently.
    const strategySeed = await postJson(backendUrl, "/api/thesis", {
      subject_type: "stock",
      subject_id: "600519",
      title: "策略错配 Thesis",
      summary: "用于验证 SWING Campaign 不接受 SHORT Formal Thesis。",
      core_claims: [],
      catalysts: [],
      risks: [],
      invalidation_conditions: [],
      change_summary: "创建策略错配测试夹具",
    }, 200);
    const strategyDraft = await postEmpty(
      backendUrl,
      `/api/thesis/${strategySeed.thesis.id}/begin-formalization`,
      200,
    );
    const strategyMismatch = await putJson(backendUrl, `/api/thesis/${strategySeed.thesis.id}`, {
      title: strategyDraft.thesis.title,
      summary: strategyDraft.thesis.summary,
      status: "active",
      core_claims: ["策略错配论点一", "策略错配论点二", "策略错配论点三"],
      catalysts: [],
      risks: [],
      invalidation_conditions: [],
      strategy: "SHORT",
      expected_horizon: { unit: "TRADING_DAY", min: 1, max: 10, anchor: "FREEZE_AT" },
      free_notes: null,
      expected_revision: strategyDraft.thesis.current_revision,
      change_summary: "构造 SHORT 与 SWING 的策略错配",
    }, 200);

    await page.goto(`${frontendUrl}/thesis/${strategyMismatch.thesis.id}?${campaignQuery}`, { waitUntil: "networkidle" });
    await page.getByRole("alert").filter({ hasText: "当前 Thesis 与真实 Campaign 的证券或策略不一致" }).waitFor();
    const mismatchConfirm = page.getByRole("button", { name: "确认 Formal Thesis" });
    await mismatchConfirm.waitFor();
    assert.equal(await mismatchConfirm.isDisabled(), true);
    assert.deepEqual(calls, { begin: 0, confirm: 0, freeze: 0, bind: 0 });

    const mismatchConfirmed = await postJson(
      backendUrl,
      `/api/thesis/${strategyMismatch.thesis.id}/confirm`,
      { expected_revision: strategyMismatch.thesis.current_revision },
      200,
    );
    await page.reload({ waitUntil: "networkidle" });
    const mismatchFreeze = page.getByRole("button", { name: "冻结 Formal Original" });
    await mismatchFreeze.waitFor();
    assert.equal(await mismatchFreeze.isDisabled(), true);
    assert.deepEqual(calls, { begin: 0, confirm: 0, freeze: 0, bind: 0 });

    const mismatchFrozen = await postJson(
      backendUrl,
      `/api/thesis/${strategyMismatch.thesis.id}/freeze`,
      { expected_revision: mismatchConfirmed.thesis.current_revision },
      200,
    );
    assert.equal(mismatchFrozen.thesis.formal_state, "frozen");
    await page.reload({ waitUntil: "networkidle" });
    const mismatchBind = page.getByRole("button", { name: "绑定到当前 Campaign" });
    await mismatchBind.waitFor();
    assert.equal(await mismatchBind.isDisabled(), true);
    assert.deepEqual(calls, { begin: 0, confirm: 0, freeze: 0, bind: 0 });

    await page.goto(`${frontendUrl}/decision-inbox`, { waitUntil: "networkidle" });
    await thesisCard.getByRole("link", { name: "新建 Formal Thesis 草稿" }).click();
    await page.getByRole("heading", { name: "新建投资逻辑" }).waitFor();
    assert.equal(await page.getByLabel("主体代码/标识 *").inputValue(), "600519");
    assert.equal(await page.getByLabel("策略").inputValue(), "SWING");
    assert.equal(await page.getByLabel("主体代码/标识 *").isDisabled(), true);
    assert.equal(await page.getByLabel("策略").isDisabled(), true);
    assert.deepEqual(calls, { begin: 0, confirm: 0, freeze: 0, bind: 0 });

    await page.getByLabel("标题 *").fill("贵州茅台波段 Formal Thesis");
    await page.getByLabel("摘要").fill("CT1 真实纵向验收");
    const claims = page.getByPlaceholder("回车添加一条核心论点");
    for (const claim of ["核心论点一", "核心论点二", "核心论点三"]) {
      await claims.fill(claim);
      await claims.press("Enter");
    }
    await page.getByRole("button", { name: "创建 Formal Thesis 草稿" }).click();
    await page.getByRole("button", { name: "确认 Formal Thesis" }).waitFor();
    assert.deepEqual(calls, { begin: 1, confirm: 0, freeze: 0, bind: 0 });
    await page.getByText("状态：draft", { exact: false }).waitFor();

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "确认 Formal Thesis" }).click();
    await page.getByRole("button", { name: "冻结 Formal Original" }).waitFor();
    assert.deepEqual(calls, { begin: 1, confirm: 1, freeze: 0, bind: 0 });

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "冻结 Formal Original" }).click();
    await page.getByRole("button", { name: "绑定到当前 Campaign" }).waitFor();
    assert.deepEqual(calls, { begin: 1, confirm: 1, freeze: 1, bind: 0 });
    await page.getByText("状态：frozen", { exact: false }).waitFor();

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "绑定到当前 Campaign" }).click();
    await page.getByText("绑定：当前 Thesis（不可变）", { exact: false }).waitFor();
    assert.deepEqual(calls, { begin: 1, confirm: 1, freeze: 1, bind: 1 });

    await page.getByRole("link", { name: "返回 Decision Inbox" }).click();
    await thesisCard.getByText("已绑定", { exact: true }).waitFor();
    await thesisCard.getByText("已冻结", { exact: false }).waitFor();
    await thesisCard.getByText("Current 状态：STABLE", { exact: true }).waitFor();
    const reviewCta = thesisCard.getByTestId("formal-decision-review-cta");
    await reviewCta.waitFor();
    assert.equal(
      await reviewCta.getAttribute("href"),
      `/campaigns/${encodeURIComponent(campaign.campaign_id)}/decision-proposal`,
    );
    assert.deepEqual(calls, { begin: 1, confirm: 1, freeze: 1, bind: 1 });
    assert.deepEqual(decisionProposalMutations, []);

    await page.reload({ waitUntil: "networkidle" });
    const reloadedThesisCard = page.locator(`[data-campaign-thesis="${campaign.campaign_id}"]`);
    await reloadedThesisCard.getByText("已绑定", { exact: true }).waitFor();
    await reloadedThesisCard.getByTestId("formal-decision-review-cta").waitFor();
    assert.deepEqual(calls, { begin: 1, confirm: 1, freeze: 1, bind: 1 });
    assert.deepEqual(decisionProposalMutations, []);

    await reloadedThesisCard.getByTestId("formal-decision-review-cta").click();
    await page.locator(`[data-decision-proposal-page="${campaign.campaign_id}"]`).waitFor();
    await page.getByTestId("decision-inbox-secondary-entry").waitFor();
    assert.deepEqual(calls, { begin: 1, confirm: 1, freeze: 1, bind: 1 });
    assert.deepEqual(decisionProposalMutations, []);

    const binding = await getJson(
      backendUrl,
      `/api/campaigns/${campaign.campaign_id}/thesis-binding`,
    );
    const current = await getJson(
      backendUrl,
      `/api/campaigns/${campaign.campaign_id}/current-thesis`,
    );
    assert.equal(binding.campaign_id, campaign.campaign_id);
    assert.equal(typeof binding.thesis_id, "string");
    assert.notEqual(binding.thesis_id, candidate.thesis.id);
    assert.equal(Number.isInteger(binding.thesis_revision_at_bind), true);
    assert.equal(binding.campaign_strategy_at_bind, campaign.strategy);
    assert.equal(current.campaign_id, campaign.campaign_id);
    assert.equal(current.thesis_id, binding.thesis_id);
    assert.deepEqual(current.binding, {
      thesis_revision_at_bind: binding.thesis_revision_at_bind,
      campaign_strategy_at_bind: binding.campaign_strategy_at_bind,
      bound_at: binding.bound_at,
    });
    assert.equal(current.frozen_revision, binding.thesis_revision_at_bind);
    assert.equal(current.ready, true);
    assert.equal(current.formal_status, "READY");
    assert.ok(current.original_snapshot && typeof current.original_snapshot === "object");
    assert.equal(current.original_snapshot.thesis?.id, binding.thesis_id);
    assert.equal(current.original_snapshot.thesis?.formal_state, "frozen");
    assert.equal(current.original_snapshot.thesis?.current_revision, current.frozen_revision);
    assert.deepEqual(current.deltas, []);
    assert.equal(current.effective_state, "STABLE");

    await page.goto(`${frontendUrl}/decision-inbox`, { waitUntil: "networkidle" });
    const gatedThesisCard = page.locator(`[data-campaign-thesis="${campaign.campaign_id}"]`);

    projectionMode = "binding-mismatch";
    await page.reload({ waitUntil: "networkidle" });
    await gatedThesisCard.getByText("已绑定", { exact: true }).waitFor();
    assert.equal(await gatedThesisCard.getByTestId("formal-decision-review-cta").count(), 0);

    projectionMode = "unknown";
    await page.reload({ waitUntil: "networkidle" });
    await gatedThesisCard.getByText("Current 状态：UNKNOWN", { exact: true }).waitFor();
    assert.equal(await gatedThesisCard.getByTestId("formal-decision-review-cta").count(), 0);

    projectionMode = "error";
    await page.reload({ waitUntil: "networkidle" });
    await gatedThesisCard.getByRole("alert").waitFor();
    assert.equal(await gatedThesisCard.getByTestId("formal-decision-review-cta").count(), 0);
    assert.deepEqual(calls, { begin: 1, confirm: 1, freeze: 1, bind: 1 });
    assert.deepEqual(decisionProposalMutations, []);

    projectionMode = "normal";
    const expectedUnboundBindingPath = `/api/campaigns/${campaign.campaign_id}/thesis-binding`;
    const unexpected404Responses = notFoundResponses.filter(
      ({ method, pathname }) => method !== "GET" || pathname !== expectedUnboundBindingPath,
    );
    assert.deepEqual(unexpected404Responses, [], `unexpected browser 404 responses: ${JSON.stringify(notFoundResponses)}`);
    assert.ok(
      notFoundResponses.length > 0,
      "expected at least one unbound thesis-binding GET to return 404",
    );
    // Chromium may log the expected unbound binding response as a console
    // resource error.  The response allowlist above ensures this exception is
    // limited to that exact GET; every other 404 fails before this check.
    const unexpectedConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("server responded with a status of 404"),
    );
    assert.equal(
      unexpectedConsoleErrors.length,
      0,
      `browser console errors: ${unexpectedConsoleErrors.join("\n")}`,
    );

    console.log("[E2E] Current Thesis activation passed.");
  } finally {
    if (browser) await browser.close();
    if (backendProc) backendProc.kill();
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    try {
      rmSync(tempDataDir, { recursive: true, force: true });
    } catch {
      // Best-effort cleanup of test-only temp data.
    }
  }
}

runE2E().catch((error) => {
  console.error("[E2E] FAILED:", error);
  process.exit(1);
});
