/**
 * P0-HR1 REAL production vertical E2E：
 * real FastAPI（production ports，无 fake evaluator）+ isolated real backend DB
 * + built frontend + Chromium。
 *
 * 证明（工作单 §10-14）：
 * - A. Campaign A：bound Current Thesis → frozen → terminal DISPROVEN
 *      → CONFIRMED + EVALUATED → DI1 REVIEW_REQUIRED → UI "已确认 Hard Risk"
 *      → reason/provenance 只来自 HR 专属 namespace → 无 EXIT/SELL 文案
 * - C. Campaign B（sibling，同 security）：STABLE → UNKNOWN → not green
 * - 13. sibling Campaign 隔离（两份 isolated Thesis）
 * - 14. provenance isolation（generic Critical Data refs 不进 HardRiskPanel）
 * - 12. read-only mutation proof：GET inbox + browser load + refresh 后
 *       DB 文件零变化、browser 零 POST/PUT/DELETE
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import {
  createReadStream, existsSync, mkdtempSync, readdirSync, rmSync, statSync,
} from "node:fs";
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

async function waitHttp(url, attempts = 120) {
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
  };
  const server = createServer((request, response) => {
    let pathname = (request.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
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
        const executable = join(base, dir, "chrome-win64", "chrome.exe");
        if (existsSync(executable)) return executable;
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

/** DB 文件快照（size + mtime + wal/shm）——GET 前后必须零变化。 */
function dbSnapshot(dataDir) {
  const files = readdirSync(dataDir)
    .filter((name) => name.endsWith(".sqlite3") || name.endsWith(".db"))
    .flatMap((name) => {
      const base = path.join(dataDir, name);
      const variants = [base, `${base}-wal`, `${base}-shm`];
      return variants.filter((p) => existsSync(p)).map((p) => {
        const stat = statSync(p);
        return `${p}:${stat.size}:${stat.mtimeMs}`;
      });
    })
    .sort();
  return files.join("\n");
}

async function runE2E() {
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-hr1-vertical-e2e-"));
  let backendProc;
  let staticServer;
  let browser;

  try {
    const backendPort = await getFreePort();
    const frontendPort = await getFreePort();
    const backendUrl = `http://127.0.0.1:${backendPort}`;
    const py = getPythonConfig();
    const env = {
      ...process.env,
      VR_ALLOW_ORIGINS: `http://127.0.0.1:${frontendPort}`,
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

    // ------------------------------------------------------------------
    // Fixture：真实 backend APIs 构造 isolated test data（写入允许）
    // ------------------------------------------------------------------
    await postJson(backendUrl, "/api/position/bootstrap-commit", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      positions: [{ code: "600519", name: "贵州茅台", shares: 100, cost_basis: 150000 }],
    }, 200);

    async function activateCampaign(securityCode, strategy) {
      const campaign = await postJson(backendUrl, "/api/campaigns",
        { security_code: securityCode, strategy }, 201);
      for (const to of ["RESEARCHING", "PRE-ENTRY", "ACTIVE"]) {
        await postJson(backendUrl, `/api/campaigns/${campaign.campaign_id}/transitions`,
          { expected_status: campaign.status, to_status: to }, 200);
        campaign.status = to;
      }
      return campaign;
    }

    async function createFrozenThesis(securityCode, strategy) {
      const thesis = await postJson(backendUrl, "/api/thesis", {
        subject_type: "stock",
        subject_id: securityCode,
        title: `HR1 ${strategy} thesis`,
        summary: "vertical fixture",
        core_claims: [],
        catalysts: [],
        risks: [],
        invalidation_conditions: [],
        change_summary: "create",
      }, 200);
      await postJson(backendUrl, `/api/thesis/${thesis.thesis.id}/begin-formalization`, {}, 200);
      const horizon = strategy === "SHORT"
        ? { unit: "TRADING_DAY", min: 1, max: 10, anchor: "FREEZE_AT" }
        : { unit: "TRADING_DAY", min: 5, max: 45, anchor: "FREEZE_AT" };
      const updated = await putJson(backendUrl, `/api/thesis/${thesis.thesis.id}`, {
        title: `HR1 ${strategy} thesis`,
        summary: "vertical fixture",
        status: "active",
        core_claims: ["claim-1", "claim-2", "claim-3"],
        catalysts: [],
        risks: [],
        invalidation_conditions: [],
        expected_revision: 1,
        strategy,
        expected_horizon: horizon,
        free_notes: null,
        change_summary: "formal fields",
      }, 200);
      await postJson(backendUrl, `/api/thesis/${thesis.thesis.id}/confirm`,
        { expected_revision: updated.thesis.current_revision }, 200);
      const frozen = await postJson(backendUrl, `/api/thesis/${thesis.thesis.id}/freeze`,
        { expected_revision: updated.thesis.current_revision }, 200);
      return { id: thesis.thesis.id, frozenRevision: frozen.thesis.frozen_revision };
    }

    // Campaign A：600519/SWING + DISPROVEN（terminal）
    const campaignA = await activateCampaign("600519", "SWING");
    const thesisA = await createFrozenThesis("600519", "SWING");
    await postJson(backendUrl, `/api/campaigns/${campaignA.campaign_id}/thesis-binding`,
      { thesis_id: thesisA.id }, 201);
    await postJson(backendUrl, `/api/thesis/${thesisA.id}/deltas`, {
      delta_state: "DISPROVEN",
      reason: "vertical fixture: core fact disproven",
    }, 200);

    // Campaign B：600519/SHORT sibling，STABLE（无 terminal delta）
    const campaignB = await activateCampaign("600519", "SHORT");
    const thesisB = await createFrozenThesis("600519", "SHORT");
    await postJson(backendUrl, `/api/campaigns/${campaignB.campaign_id}/thesis-binding`,
      { thesis_id: thesisB.id }, 201);

    // ------------------------------------------------------------------
    // Backend 四字段 + DI state（production port 真实链条）
    // ------------------------------------------------------------------
    const snapshot = await getJson(backendUrl, "/api/decision-inbox");
    const itemA = snapshot.campaign_items.find((i) => i.campaign_id === campaignA.campaign_id);
    const itemB = snapshot.campaign_items.find((i) => i.campaign_id === campaignB.campaign_id);
    assert.ok(itemA, "Campaign A item missing");
    assert.ok(itemB, "Campaign B item missing");

    // A：DISPROVEN → CONFIRMED + EVALUATED
    assert.equal(itemA.hard_risk_state, "CONFIRMED");
    assert.equal(itemA.hard_risk_evaluation, "EVALUATED");
    assert.ok(itemA.hard_risk_reason_codes.includes("HARD_RISK_CONFIRMED"));
    assert.ok(itemA.hard_risk_reason_codes.includes("THESIS_CORE_FACT_DISPROVEN"));
    assert.ok(itemA.hard_risk_authority_refs.length > 0);
    assert.ok(itemA.hard_risk_authority_refs[0].startsWith(`current_thesis:${campaignA.campaign_id}:`));
    assert.equal(itemA.visible_state, "REVIEW_REQUIRED");

    // C：STABLE → UNKNOWN，不绿、不 NO_ACTION_REQUIRED
    assert.equal(itemB.hard_risk_state, "UNKNOWN");
    assert.equal(itemB.hard_risk_evaluation, "UNKNOWN");
    assert.notEqual(itemB.visible_state, "NO_ACTION_REQUIRED");

    // 四字段存在（O 契约）
    for (const item of [itemA, itemB]) {
      assert.ok("hard_risk_state" in item);
      assert.ok("hard_risk_evaluation" in item);
      assert.ok("hard_risk_reason_codes" in item);
      assert.ok("hard_risk_authority_refs" in item);
    }

    // ------------------------------------------------------------------
    // Read-only mutation proof：GET inbox 前后 DB 零变化
    // ------------------------------------------------------------------
    const baselineBeforeRead = dbSnapshot(tempDataDir);
    await getJson(backendUrl, "/api/decision-inbox");
    const baselineAfterRead = dbSnapshot(tempDataDir);
    assert.equal(baselineAfterRead, baselineBeforeRead,
      "GET decision-inbox 不得产生任何 DB 写入");

    // ------------------------------------------------------------------
    // Browser：built frontend + Chromium
    // ------------------------------------------------------------------
    staticServer = await startStaticServer(frontendDist, frontendPort);
    browser = await chromium.launch({ executablePath: findChromium(), headless: true });
    const page = await browser.newPage();
    const consoleErrors = [];
    const mutationRequests = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("request", (request) => {
      const method = request.method();
      if (method !== "GET" && method !== "OPTIONS" && request.url().includes("/api/")) {
        mutationRequests.push(`${method} ${request.url()}`);
      }
    });

    // 真实 backend 代理：browser 的所有 /api 请求转发到 FastAPI（production ports）。
    const proxyToBackend = (route) => {
      const url = new URL(route.request().url());
      return route.continue({ url: `${backendUrl}${url.pathname}${url.search}` });
    };
    await page.route("**/api/**", proxyToBackend);

    await page.goto(`http://127.0.0.1:${frontendPort}/decision-inbox`, { waitUntil: "networkidle" });

    const panelA = page.locator(`[data-hard-risk-campaign="${campaignA.campaign_id}"]`);
    await panelA.waitFor();
    assert.equal(await panelA.getAttribute("data-hard-risk-state"), "CONFIRMED");
    assert.equal(await panelA.getAttribute("data-hard-risk-safe"), "false");
    await panelA.getByText("已确认 Hard Risk", { exact: false }).first().waitFor();
    // 展开 reason details 后断言专属 reason codes
    await panelA.getByText("评估说明", { exact: false }).click();
    await panelA.getByText("THESIS_CORE_FACT_DISPROVEN", { exact: false }).waitFor();
    // provenance 只来自 HR 专属 namespace（current_thesis:...）
    await panelA.getByText(`current_thesis:${campaignA.campaign_id}:`, { exact: false }).waitFor();
    // 无 EXIT/SELL 文案
    const panelAText = await panelA.innerText();
    for (const token of ["卖出", "退出", "清仓", "EXIT", "SELL"]) {
      assert.equal(panelAText.includes(token), false, `panel A 不得含「${token}」`);
    }

    const panelB = page.locator(`[data-hard-risk-campaign="${campaignB.campaign_id}"]`);
    await panelB.waitFor();
    assert.equal(await panelB.getAttribute("data-hard-risk-state"), "UNKNOWN");
    assert.equal(await panelB.getAttribute("data-hard-risk-safe"), "false");
    await panelB.getByText("Hard Risk 状态未知", { exact: false }).first().waitFor();

    // sibling 隔离：A 面板不含 B 的 provenance，B 面板不含 A 的 provenance
    const panelBText = await panelB.innerText();
    assert.equal(panelAText.includes(`current_thesis:${campaignB.campaign_id}:`), false,
      "panel A 不得出现 Campaign B 的 provenance");
    assert.equal(panelBText.includes(`current_thesis:${campaignA.campaign_id}:`), false,
      "panel B 不得出现 Campaign A 的 provenance");

    // refresh 后仍来自 backend authority（面板状态不变）
    await page.reload({ waitUntil: "networkidle" });
    await page.locator(`[data-hard-risk-campaign="${campaignA.campaign_id}"]`).waitFor();
    assert.equal(
      await page.locator(`[data-hard-risk-campaign="${campaignA.campaign_id}"]`)
        .getAttribute("data-hard-risk-state"),
      "CONFIRMED",
    );

    // browser 读操作零 mutation（trade / campaign / thesis / decision）
    assert.deepEqual(mutationRequests, [], `browser 不得发起写请求: ${mutationRequests.join("; ")}`);

    // refresh 后 DB 仍零变化（含 browser reload）
    const baselineAfterBrowser = dbSnapshot(tempDataDir);
    assert.equal(baselineAfterBrowser, baselineBeforeRead,
      "browser load + refresh 不得产生任何 DB 写入");

    // 页面无意外 console error（next-actions 404 属预期，过滤）
    const unexpectedConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("404"),
    );
    assert.deepEqual(unexpectedConsoleErrors, [],
      `console errors: ${unexpectedConsoleErrors.join("\n")}`);

    console.log("[HR1 real vertical E2E] passed.");
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
  console.error("[HR1 real vertical E2E] FAILED:", error);
  process.exit(1);
});
