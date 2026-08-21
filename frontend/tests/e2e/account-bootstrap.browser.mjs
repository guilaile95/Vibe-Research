/**
 * P0-AB2 账户初始化（Bootstrap）— Real FastAPI Backend Playwright E2E。
 *
 * 独立临时数据目录 + 真实后端（未预置 bootstrap）+ 真实前端构建产物：
 * 覆盖从「canonical=false → Bootstrap 激活卡」到「canonical=true →
 * CREATE_CAMPAIGN 入口」的完整纵向闭环。
 *
 * 1. 初始 /decision-inbox → canonical=false + POSITION_LEDGER_NOT_BOOTSTRAPPED；
 *    页面出现「初始化持仓事实」卡（不再只是“决策待办暂不可用”）。
 * 2. GET /portfolio 返回模拟 legacy holdings → 仅预填（不自动 commit）。
 * 3. ledger_start_at 为空 → 预览按钮禁用；显式填写日期后预览。
 * 4. 预览只调用 bootstrap-preview，绝不调用 bootstrap-commit（请求计数）。
 * 5. 预览展示 LEGACY_POSITION_OPENING / PRE_VIBE / UNKNOWN + 反 BUY 文案。
 * 6. 预览后修改表单 → PREVIEW_INVALIDATED，commit 禁用，须重新预览。
 * 7. 显式确认 checkbox → commit 启用；commit payload == 预览时同一份 payload。
 * 8. commit 成功后自动刷新：canonical=true → 待建立 Campaign 的持仓 +
 *    「创建 Campaign」按钮。
 * 9. 页面全程不提供覆盖 / 重置动作。
 */
import { chromium } from "playwright";
import { spawn, execSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, readdirSync, createReadStream } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import path from "node:path";
import assert from "node:assert/strict";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitHttp(url, attempts = 100) {
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await fetch(url);
      if (r.ok || r.status < 500) return r;
    } catch {
      /* retry */
    }
    await sleep(300);
  }
  throw new Error(`timeout waiting ${url}`);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
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
  const server = createServer((req, res) => {
    let pn = (req.url || "/").split("?")[0];
    if (pn === "/") pn = "/index.html";
    let target = path.join(dir, pn);
    const rd = path.resolve(dir);
    const rt = path.resolve(target);
    if (!rt.startsWith(rd + path.sep) && rt !== rd) {
      res.writeHead(403);
      res.end("forbidden");
      return;
    }
    if (!existsSync(target)) target = path.join(dir, "index.html");
    const ext = path.extname(target);
    res.setHeader("Content-Type", mime[ext] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function getPythonConfig() {
  const envPy = process.env.PYTHON;
  if (envPy) return { cmd: envPy, extraArgs: ["-m", "uvicorn"] };
  const isWin = process.platform === "win32";
  return isWin
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
      for (const d of readdirSync(base)) {
        if (d.startsWith("chromium-") && !d.includes("headless")) {
          const exe = join(base, d, "chrome-win64", "chrome.exe");
          if (existsSync(exe)) return exe;
          const linux = join(base, d, "chrome-linux", "chrome");
          if (existsSync(linux)) return linux;
          const mac = join(base, d, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium");
          if (existsSync(mac)) return mac;
        }
      }
    } catch {
      /* next */
    }
  }
  return undefined;
}

const MOCK_PORTFOLIO = {
  data: {
    holdings: [
      {
        code: "001896",
        name: "豫能控股",
        price: 4.2,
        shares: 1000,
        cost: 3.5,
        market_value: 4200,
        pnl: 700,
        pnl_pct: 20.0,
        data_status: "normal",
      },
      {
        code: "002031",
        name: "巨轮智能",
        price: 14.1,
        shares: 500,
        cost: 12.0,
        market_value: 7050,
        pnl: 1050,
        pnl_pct: 17.5,
        data_status: "normal",
      },
    ],
    totals: { market_value: 11250, cost: 9500, pnl: 1750, pnl_pct: 18.42 },
    closed: [],
    realized_pnl: 0,
    updated: "2026-08-15 10:00",
    last_refresh: null,
    data_status: "normal",
  },
};

async function runE2E() {
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-bootstrap-e2e-"));
  console.log(`[E2E] temporary isolated data dir: ${tempDataDir}`);

  let backendProc = null;
  let staticServer = null;
  let browser = null;

  try {
    const backendPort = await getFreePort();
    const frontendPort = await getFreePort();

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

    console.log(`[E2E] starting unseeded FastAPI backend on port ${backendPort}...`);
    backendProc = spawn(
      py.cmd,
      [...py.extraArgs, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
      { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"] },
    );
    backendProc.stdout.on("data", (chunk) => process.stdout.write(`[backend] ${chunk}`));
    backendProc.stderr.on("data", (chunk) => process.stderr.write(`[backend] ${chunk}`));

    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    console.log(`[E2E] backend ready.`);

    // 初始状态：canonical=false + POSITION_LEDGER_NOT_BOOTSTRAPPED
    const initial = await (
      await fetch(`http://127.0.0.1:${backendPort}/api/decision-inbox`)
    ).json();
    assert.equal(initial.data.canonical, false, "unseeded inbox must be non-canonical");
    assert.ok(
      initial.data.reason_codes.includes("POSITION_LEDGER_NOT_BOOTSTRAPPED"),
      "reason must include POSITION_LEDGER_NOT_BOOTSTRAPPED",
    );

    staticServer = await startStaticServer(frontendDist, frontendPort);

    browser = await chromium.launch({ executablePath: findChromium(), headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();

    let previewCount = 0;
    let commitCount = 0;
    const previewBodies = [];
    const commitBodies = [];

    // —— portfolio Promise gate：显式挂起 GET /api/portfolio 响应，直到测试释放。
    // 事件驱动等待请求到达（不用 sleep 猜时序）。
    let portfolioRequestedResolve;
    let portfolioRelease;
    const portfolioRequested = new Promise((resolve) => {
      portfolioRequestedResolve = resolve;
    });
    const portfolioGate = new Promise((resolve) => {
      portfolioRelease = resolve;
    });

    const proxyToBackend = (route) => {
      const u = new URL(route.request().url());
      return route.continue({
        url: `http://127.0.0.1:${backendPort}${u.pathname}${u.search}`,
      });
    };

    // 通用代理（先注册：后注册的特定 route 优先命中）
    await page.route("**/api/**", proxyToBackend);
    // 计数：preview 零写 vs commit 写（同时代理到真实后端）
    await page.route("**/api/position/bootstrap-preview", async (route) => {
      previewCount += 1;
      previewBodies.push(route.request().postDataJSON());
      await proxyToBackend(route);
    });
    await page.route("**/api/position/bootstrap-commit", async (route) => {
      commitCount += 1;
      commitBodies.push(route.request().postDataJSON());
      await proxyToBackend(route);
    });
    // legacy portfolio：挂起响应直到测试释放 gate；只作为预填输入
    await page.route("**/api/portfolio", async (route) => {
      if (route.request().method() !== "GET") return proxyToBackend(route);
      portfolioRequestedResolve();
      await portfolioGate;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_PORTFOLIO),
      });
    });

    // 1. Bootstrap Activation Card（不再是单纯“暂不可用”）
    // 注意：portfolio 被 gate 挂起时 networkidle 永不满足，改用 domcontentloaded +
    // 显式 waitForSelector 同步渲染。
    console.log("[E2E] 1. opening /decision-inbox (non-canonical)...");
    await page.goto(`http://127.0.0.1:${frontendPort}/decision-inbox`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForSelector("h1:has-text('决策待办')");
    await page.waitForSelector("h2:has-text('初始化持仓事实')");
    assert.equal(
      await page.locator("text=决策待办暂不可用").count(),
      0,
      "bootstrap card replaces the generic unavailable box",
    );

    // 2. prefilling 期间（portfolio pending）：Preview/Commit 门 fail-closed
    console.log("[E2E] 2. prefilling gate: preview & commit stay closed while portfolio pending...");
    // 事件驱动：等待 GET /api/portfolio 到达 route handler（防御性超时，防无限挂起）
    await Promise.race([
      portfolioRequested,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("GET /api/portfolio never reached the gate")), 15000),
      ),
    ]);
    await page.waitForSelector("text=正在读取当前持仓…");
    const previewBtn = page.locator("button:has-text('预览初始化')");
    const commitBtn = page.locator("button:has-text('确认初始化账户事实')");
    assert.equal(
      await previewBtn.isDisabled(),
      true,
      "preview stays disabled while prefilling",
    );
    await page.fill("input[type='date']", "2026-08-01");
    assert.equal(
      await previewBtn.isDisabled(),
      true,
      "preview stays disabled while prefilling even with valid date",
    );
    assert.equal(await commitBtn.isDisabled(), true, "commit stays disabled while prefilling");
    assert.equal(previewCount, 0, "no preview request while prefilling");
    assert.equal(commitCount, 0, "no commit request while prefilling");

    // 3. 释放 portfolio gate → legacy portfolio 仅预填 → 预览门开放
    console.log("[E2E] 3. releasing portfolio gate -> prefill completes...");
    portfolioRelease();
    await page.waitForSelector("input[aria-label='持仓 1 代码']");
    assert.equal(await page.inputValue("input[aria-label='持仓 1 代码']"), "001896");
    assert.equal(await page.inputValue("input[aria-label='持仓 2 代码']"), "002031");
    assert.equal(await page.inputValue("input[aria-label='持仓 1 数量']"), "1000");
    await page.waitForSelector("text=以下内容从当前持仓预填");
    assert.equal(commitCount, 0, "prefill must never trigger commit");

    // ledger_start_at 仍是独立必填门：prefill 完成后为空也不得 Preview。
    await page.fill("input[type='date']", "");
    assert.equal(
      await previewBtn.isDisabled(),
      true,
      "preview stays disabled without ledger_start_at after prefilling",
    );
    await page.fill("input[type='date']", "2026-08-01");
    assert.equal(
      await previewBtn.isDisabled(),
      false,
      "preview opens only after prefilling finishes and ledger_start_at is explicit",
    );

    // 4. Preview：只调用 bootstrap-preview，不调用 commit
    console.log("[E2E] 4. preview calls bootstrap-preview only...");
    await previewBtn.click();
    await page.waitForSelector("text=初始化预览");
    assert.equal(previewCount, 1);
    assert.equal(commitCount, 0);

    // 5. Preview 展示事实类型 / 来源 / 历史 + 反 BUY 文案
    console.log("[E2E] 5. preview facts are LEGACY_POSITION_OPENING / PRE_VIBE / UNKNOWN...");
    await page.waitForSelector("text=事实类型 = LEGACY_POSITION_OPENING");
    await page.waitForSelector("text=持仓来源 = PRE_VIBE");
    await page.waitForSelector("text=历史交易 = UNKNOWN");
    await page.waitForSelector("text=这不是历史买入记录，不会把现有持仓伪造成 BUY。");
    assert.equal(
      await page.locator("text=事实类型 = BUY").count(),
      0,
      "no copy may describe legacy opening as BUY",
    );
    assert.equal(
      await page.locator("text=持仓来源 = BUY").count(),
      0,
      "no copy may describe legacy origin as BUY",
    );

    // 6. 未确认 → commit 禁用；预览后修改 → PREVIEW_INVALIDATED + 禁用
    console.log("[E2E] 6. commit gates: confirm + input equality...");
    assert.equal(await commitBtn.isDisabled(), true, "checkbox required");
    await page.fill("input[aria-label='持仓 1 数量']", "999");
    await page.waitForSelector("text=表单已在预览后修改");
    assert.equal(await commitBtn.isDisabled(), true, "edit invalidates preview");
    await page.fill("input[aria-label='持仓 1 数量']", "1000");
    await previewBtn.click();
    await page.waitForSelector("text=初始化预览");
    assert.equal(previewCount, 2);
    assert.equal(
      await page.locator("text=表单已在预览后修改").count(),
      0,
      "re-preview clears invalidation",
    );

    // 7. 显式确认 → commit 可用；commit payload == 预览 payload
    console.log("[E2E] 7. explicit confirmation enables commit...");
    assert.equal(await commitBtn.isDisabled(), true, "still needs confirmation");
    await page.check("input[type='checkbox']");
    assert.equal(await commitBtn.isDisabled(), false);
    await commitBtn.click();
    await page.waitForFunction(() => {
      return document.body.textContent.includes("待建立 Campaign 的持仓");
    });
    assert.equal(commitCount, 1, "commit called exactly once");
    assert.deepEqual(commitBodies[0], previewBodies[1], "commit payload == preview payload");

    // 8. commit 成功 → 自动刷新 → canonical holdings + CREATE_CAMPAIGN
    console.log("[E2E] 8. canonical holdings + CREATE_CAMPAIGN entry...");
    await page.waitForSelector("h2:has-text('待建立 Campaign 的持仓')");
    await page.waitForSelector("text=001896");
    await page.waitForSelector("button:has-text('创建 Campaign')");
    assert.equal(
      await page.locator("h2:has-text('初始化持仓事实')").count(),
      0,
      "bootstrap card gone after canonical refresh",
    );
    const refreshed = await (
      await fetch(`http://127.0.0.1:${backendPort}/api/decision-inbox`)
    ).json();
    assert.equal(refreshed.data.canonical, true);
    assert.ok(
      refreshed.data.holding_setup_items.some((item) => item.security_code === "001896"),
      "committed holding must appear in holding_setup_items",
    );

    // 9. 全程无覆盖 / 重置动作
    console.log("[E2E] 9. no overwrite/reset actions exist...");
    assert.equal(await page.locator("button:has-text('覆盖')").count(), 0);
    assert.equal(await page.locator("button:has-text('重置')").count(), 0);

    console.log("[E2E] Account Bootstrap E2E test passed successfully!");
  } finally {
    if (browser) await browser.close();
    if (backendProc) backendProc.kill();
    if (staticServer) await new Promise((r) => staticServer.close(r));
    try {
      rmSync(tempDataDir, { recursive: true, force: true });
    } catch {
      /* best effort */
    }
  }
}

runE2E().catch((err) => {
  console.error("[E2E] FAILED:", err);
  process.exit(1);
});
