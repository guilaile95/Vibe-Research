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
  // 与 pythonConfig() 同构：PYTHON 显式指定时直接执行，Windows 用 py -3。
  const py = env.PYTHON
    ? { cmd: env.PYTHON, prefixArgs: [] }
    : process.platform === "win32"
      ? { cmd: "py", prefixArgs: ["-3"] }
      : { cmd: "python3", prefixArgs: [] };
  const result = spawnSync(py.cmd, [...py.prefixArgs, "-c", script], {
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
      ...process.env,
      VR_ALLOW_ORIGINS: frontend,
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
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

    const mixedCandidate = {
      decision_id: decision.decision_id,
      campaign_id: campaign.campaign_id,
      security_code: decision.security_code,
      strategy: decision.strategy,
      thesis_id: decision.thesis_id,
      thesis_revision: decision.thesis_revision,
      committed_at: decision.committed_at,
      review_by: decision.review_by,
      next_best_action: decision.next_best_action,
      snapshot_hash: decision.snapshot_hash,
    };
    await page.route(`**/trades/${secondTrade.trade_id}/attribution-candidates`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            candidates: [mixedCandidate],
            scan_state: "INVALID_WITNESS",
            reason_codes: ["FROZEN_DECISION_WITNESS_INVALID"],
          },
        }),
      });
    });
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "详情" }).first().click();
    await page.getByText("UNALLOCATED", { exact: true }).waitFor();
    await page.getByText("Frozen Decision，但见证校验失败", { exact: false }).waitFor();
    assert.equal(await page.getByRole("button", { name: "明确归属" }).count(), 0);
    assert.equal(await page.getByText("若该交易确实非计划内", { exact: false }).count(), 0);
    await page.unroute(`**/trades/${secondTrade.trade_id}/attribution-candidates`);
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

    // ===== P1-TRUX1：UI 创建 → 自动续接详情（零自动归属） =====
    let truxWritePosts = 0;
    let tradeCreatePosts = 0;
    page.on("request", (request) => {
      if (request.method() !== "POST") return;
      const pathname = new URL(request.url()).pathname;
      if (/\/attribution|\/unplanned/.test(pathname)) {
        truxWritePosts += 1;
      }
      if (pathname === "/api/trades") {
        tradeCreatePosts += 1;
      }
    });
    const waitForCreatedTrade = () => page.waitForResponse((response) => (
      response.request().method() === "POST"
      && new URL(response.url()).pathname === "/api/trades"
    ), { timeout: 60000 });
    // 创建表单与详情面板都是 fixed 遮罩；用标题精确锁定创建弹窗。
    const openCreateModal = async () => {
      await page.reload({ waitUntil: "networkidle" });
      await page.getByRole("button", { name: "新建交易" }).click();
      return page.locator("div.fixed.inset-0").filter({ hasText: "新建交易流水" });
    };
    const fillCreateForm = async (
      modal,
      {
        status = "full",
        executionTime = "2098-01-02T10:00",
        fee = status === "partial" ? "0" : "12.50",
        otherCost = status === "partial" ? "0" : "3.25",
      } = {},
    ) => {
      await modal.getByPlaceholder("6位数字，如 600519").fill("600519");
      await modal.getByPlaceholder("如 贵州茅台").fill("贵州茅台");
      if (status === "not_executed") {
        await modal.locator("select").nth(1).selectOption("not_executed");
        await modal.getByPlaceholder("请输入未执行或部分执行的原因").fill("触发价未到达，放弃追高");
        return;
      }
      if (status === "partial") {
        await modal.locator("select").nth(1).selectOption("partial");
        await modal.getByPlaceholder("可选，正整数", { exact: true }).fill("2");
        await modal.getByPlaceholder("请输入未执行或部分执行的原因").fill("仅成交一半");
      }
      await modal.getByPlaceholder("大于0", { exact: true }).fill("102");
      await modal.getByPlaceholder("正整数", { exact: true }).fill(status === "partial" ? "1" : "1");
      await modal.locator('input[type="datetime-local"]').fill(executionTime);
      const costInputs = modal.getByPlaceholder("请输入实际费用，0 表示确认费用为 0");
      await costInputs.nth(0).fill(fee);
      await costInputs.nth(1).fill(otherCost);
    };

    // --- TRT1：executed Trade 未显式选择成交时间时，浏览器阻断提交且不产生 POST ---
    const missingTimeModal = await openCreateModal();
    await missingTimeModal.getByPlaceholder("6位数字，如 600519").fill("600519");
    await missingTimeModal.getByPlaceholder("如 贵州茅台").fill("贵州茅台");
    await missingTimeModal.getByPlaceholder("大于0", { exact: true }).fill("102");
    await missingTimeModal.getByPlaceholder("正整数", { exact: true }).fill("1");
    const missingTimeInput = missingTimeModal.locator('input[type="datetime-local"]');
    const missingTimeCosts = missingTimeModal.getByPlaceholder("请输入实际费用，0 表示确认费用为 0");
    assert.equal(await missingTimeInput.inputValue(), "");
    assert.equal(await missingTimeInput.evaluate((input) => input.required && !input.checkValidity()), true);
    assert.equal(await missingTimeCosts.nth(0).inputValue(), "");
    assert.equal(await missingTimeCosts.nth(1).inputValue(), "");
    assert.equal(await missingTimeCosts.nth(0).evaluate((input) => input.required && !input.checkValidity()), true);
    assert.equal(await missingTimeCosts.nth(1).evaluate((input) => input.required && !input.checkValidity()), true);
    await missingTimeModal.getByRole("button", { name: "提交创建" }).click();
    assert.equal(tradeCreatePosts, 0, "missing execution time/cost must not issue trade POST");
    assert.equal(await missingTimeModal.count(), 1, "missing execution time/cost must keep the form open");

    // --- TRT1 + TRT2 + TRUX1：显式时间与费用预览 → 创建成功 → 自动详情 ---
    const executedModal = missingTimeModal;
    await executedModal.locator('input[type="datetime-local"]').fill("2098-01-02T10:00");
    await executedModal.getByPlaceholder("请输入实际费用，0 表示确认费用为 0").nth(0).fill("12.50");
    await executedModal.getByPlaceholder("请输入实际费用，0 表示确认费用为 0").nth(1).fill("3.25");
    const expectedExecutedIso = await page.evaluate(() => new Date("2098-01-02T10:00").toISOString());
    await executedModal.getByText("本地时间：2098-01-02T10:00", { exact: true }).waitFor();
    await executedModal.getByText(/浏览器解析时区：/).waitFor();
    await executedModal.getByText(/UTC offset：UTC[+-]\d{2}:\d{2}/).waitFor();
    await executedModal.getByText(`Canonical UTC ISO：${expectedExecutedIso}`, { exact: true }).waitFor();
    const [createdResponse] = await Promise.all([
      waitForCreatedTrade(),
      executedModal.getByRole("button", { name: "提交创建" }).click(),
    ]);
    assert.equal(createdResponse.ok(), true, await createdResponse.text());
    const createdRecord = (await createdResponse.json()).data;
    assert.match(createdRecord.trade_id, /^[0-9a-f]{32}$/);
    await executedModal.waitFor({ state: "detached" });
    await page.getByText(`ID: ${createdRecord.trade_id}`).waitFor();
    await page.getByText("交易归属与 Campaign 对账").waitFor();
    await page.getByText("UNALLOCATED", { exact: true }).waitFor();
    await page.getByText(decision.decision_id, { exact: true }).waitFor();
    assert.equal(truxWritePosts, 0, "attribution/unplanned POST must stay 0 before explicit user click");
    await page.getByRole("button", { name: "明确归属" }).click();
    await page.getByText("ALLOCATED", { exact: true }).waitFor();
    assert.equal(truxWritePosts, 1, "explicit attribution must be the only write");
    const createdReadback = await jsonRequest(backend, `/api/trades/${createdRecord.trade_id}`);
    assert.equal(new Date(createdReadback.executed_at).toISOString(), expectedExecutedIso);
    assert.equal(createdReadback.fee, 12.5);
    assert.equal(createdReadback.other_cost, 3.25);

    // --- TRT1 + TRT2：partial 使用显式 0 费用并保持同一 readback 语义 ---
    const partialModal = await openCreateModal();
    await fillCreateForm(partialModal, { status: "partial", executionTime: "2098-01-03T11:15", fee: "0", otherCost: "0" });
    const expectedPartialIso = await page.evaluate(() => new Date("2098-01-03T11:15").toISOString());
    await partialModal.getByText(`Canonical UTC ISO：${expectedPartialIso}`, { exact: true }).waitFor();
    const [partialResponse] = await Promise.all([
      waitForCreatedTrade(),
      partialModal.getByRole("button", { name: "提交创建" }).click(),
    ]);
    assert.equal(partialResponse.ok(), true, await partialResponse.text());
    const partialRecord = (await partialResponse.json()).data;
    await partialModal.waitFor({ state: "detached" });
    const partialDetailModal = page.locator("div.fixed.inset-0").filter({ hasText: `ID: ${partialRecord.trade_id}` });
    await partialDetailModal.getByText(`ID: ${partialRecord.trade_id}`, { exact: true }).waitFor();
    await partialDetailModal.getByText("部分执行", { exact: true }).waitFor();
    await partialDetailModal.getByText("仅成交一半", { exact: true }).waitFor();
    await partialDetailModal.getByText("UNALLOCATED", { exact: true }).waitFor();
    assert.equal(truxWritePosts, 1, "partial continuation must not issue attribution/unplanned writes");
    const partialReadback = await jsonRequest(backend, `/api/trades/${partialRecord.trade_id}`);
    assert.equal(partialReadback.execution_status, "partial");
    assert.equal(partialReadback.planned_quantity, 2);
    assert.equal(partialReadback.actual_quantity, 1);
    assert.equal(partialReadback.unexecuted_reason, "仅成交一半");
    assert.equal(partialReadback.fee, 0);
    assert.equal(partialReadback.other_cost, 0);
    assert.equal(new Date(partialReadback.executed_at).toISOString(), expectedPartialIso);
    const partialState = await jsonRequest(backend, `/api/trades/${partialRecord.trade_id}/reconciliation`);
    assert.equal(partialState.allocation_state, "UNALLOCATED");
    assert.equal(partialState.reconciliation_requirement, "REQUIRED");

    // --- not_executed：同样自动打开详情，但诚实显示 NOT_APPLICABLE ---
    const notExecutedModal = await openCreateModal();
    await fillCreateForm(notExecutedModal, { status: "not_executed" });
    const [notExecutedResponse] = await Promise.all([
      waitForCreatedTrade(),
      notExecutedModal.getByRole("button", { name: "提交创建" }).click(),
    ]);
    assert.equal(notExecutedResponse.ok(), true, await notExecutedResponse.text());
    const notExecutedRecord = (await notExecutedResponse.json()).data;
    await notExecutedModal.waitFor({ state: "detached" });
    await page.getByText(`ID: ${notExecutedRecord.trade_id}`).waitFor();
    // 状态与对账字段都诚实显示 NOT_APPLICABLE（TRADE_NOT_EXECUTED）
    await page.getByText("NOT_APPLICABLE", { exact: true }).first().waitFor();
    assert.equal(await page.getByRole("button", { name: "明确归属" }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "标记为 UNPLANNED" }).count(), 0);
    assert.equal(truxWritePosts, 1, "not_executed continuation must not issue attribution/unplanned writes");

    // --- 持久化成功但详情读取失败：不回滚、不伪装失败，诚实显示读取错误 ---
    // trade_id 为无前缀 hex；模式只匹配详情单段路径，不影响列表/recon/candidates。
    await page.route("**/api/trades/*", async (route) => {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "TRUX1_DETAIL_READ_FAILED" }) });
    });
    const failingReadModal = await openCreateModal();
    await fillCreateForm(failingReadModal, { notExecuted: false });
    const [failingReadResponse] = await Promise.all([
      waitForCreatedTrade(),
      failingReadModal.getByRole("button", { name: "提交创建" }).click(),
    ]);
    assert.equal(failingReadResponse.ok(), true, await failingReadResponse.text());
    const failingReadRecord = (await failingReadResponse.json()).data;
    await failingReadModal.waitFor({ state: "detached" });
    await page.getByText("交易流水创建成功，已打开该笔交易详情").waitFor();
    await page.getByText("TRUX1_DETAIL_READ_FAILED").waitFor();
    assert.equal(truxWritePosts, 1, "read failure must not trigger attribution/unplanned writes");
    await page.unroute("**/api/trades/*");

    const persistedIds = [createdRecord.trade_id, partialRecord.trade_id, notExecutedRecord.trade_id, failingReadRecord.trade_id];
    for (const tradeId of persistedIds) {
      const persisted = await jsonRequest(backend, `/api/trades/${tradeId}`);
      assert.equal(persisted.trade_id, tradeId);
    }
    const notExecutedReadback = await jsonRequest(backend, `/api/trades/${notExecutedRecord.trade_id}`);
    assert.equal(notExecutedReadback.execution_status, "not_executed");
    assert.equal(notExecutedReadback.executed_at, null);
    assert.equal(
      consoleErrors.filter((message) => !message.includes("ERR_NETWORK_ACCESS_DENIED")
        && !message.includes("503 (Service Unavailable)")).length,
      0,
      JSON.stringify(consoleErrors),
    );
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
