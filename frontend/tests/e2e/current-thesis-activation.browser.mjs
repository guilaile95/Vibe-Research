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

async function runE2E() {
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-current-thesis-e2e-"));
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

    staticServer = await startStaticServer(frontendDist, frontendPort);
    browser = await chromium.launch({ executablePath: findChromium(), headless: true });
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    const calls = { begin: 0, confirm: 0, freeze: 0, bind: 0 };
    const proxyToBackend = (route) => {
      const url = new URL(route.request().url());
      return route.continue({ url: `${backendUrl}${url.pathname}${url.search}` });
    };
    await page.route("**/api/**", proxyToBackend);
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

    await page.goto(`http://127.0.0.1:${frontendPort}/decision-inbox`, { waitUntil: "networkidle" });
    const thesisCard = page.locator(`[data-campaign-thesis="${campaign.campaign_id}"]`);
    await thesisCard.getByText("尚未绑定", { exact: true }).waitFor();
    assert.deepEqual(calls, { begin: 0, confirm: 0, freeze: 0, bind: 0 });

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
    await thesisCard.getByText("Current 状态：", { exact: false }).waitFor();

    const binding = await (await fetch(
      `${backendUrl}/api/campaigns/${campaign.campaign_id}/thesis-binding`,
    )).json();
    const current = await (await fetch(
      `${backendUrl}/api/campaigns/${campaign.campaign_id}/current-thesis`,
    )).json();
    assert.equal(binding.data.campaign_id, campaign.campaign_id);
    assert.equal(current.data.ready, true);
    assert.equal(current.data.formal_status, "READY");
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
