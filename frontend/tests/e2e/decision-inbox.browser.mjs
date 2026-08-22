/**
 * 决策待办（Decision Inbox）— Real FastAPI Backend Playwright E2E（P0-CS1-R1）。
 *
 * 开启真实 FastAPI 后端与前端构建产物，使用独立临时数据目录。
 * 覆盖 render-level 产品闭环（R1 blocker 修复的证明）：
 *
 * 1. 种子：bootstrap position reality（600519 legacy holding）。
 * 2. /decision-inbox → UNASSIGNED_HOLDING 行 + 「创建 Campaign」按钮。
 * 3. 创建 SWING → 创建表单自动收起，页面定位并高亮新 DRAFT setup card；
 *    同一 card 直接展示 Campaign lifecycle 与 Current Thesis 下一步入口。
 * 4. 刷新后 DRAFT 仍持续存在（不依赖 transient focus component）。
 * 5. 同 Security 再创建 MEDIUM DRAFT —— 两个 setup 卡共存。
 * 6. SWING 卡显式点击：开始研究 → 标记待入场 → 激活 Campaign（每步一次，无链式）。
 * 7. ACTIVE 后：SWING 离开 setup 区域，进入「当前 Campaign」；
 *    MEDIUM DRAFT sibling 仍可见（ACTIVE sibling 不隐藏 DRAFT sibling）；
 *    决策状态为诚实状态（绝不显示 NO_ACTION_REQUIRED）。
 * 8. 刷新后状态保持（backend 权威，无本地伪造）。
 * 9. 非法 transition（MEDIUM DRAFT→ACTIVE 直跳）→ backend 409；
 *    刷新后 MEDIUM 仍「草稿」（状态绝不本地推进）。
 */
import { chromium } from "playwright";
import { spawn, execSync } from "node:child_process";
import {
  mkdtempSync,
  rmSync,
  existsSync,
  readdirSync,
  createReadStream,
} from "node:fs";
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
          const mac = join(
            base,
            d,
            "chrome-mac",
            "Chromium.app",
            "Contents",
            "MacOS",
            "Chromium",
          );
          if (existsSync(mac)) return mac;
        }
      }
    } catch {
      /* next */
    }
  }
  return undefined;
}

const SEED_SCRIPT = `
import os, sys
sys.path.insert(0, os.getcwd())
import position_reality_service as ps
result = ps.bootstrap_commit({
    "ledger_start_at": "2026-08-01",
    "opening_cash": 100000.0,
    "positions": [{"code": "600519", "name": "贵州茅台", "shares": 100, "cost_basis": 150000.0}],
})
assert result.get("status") == "BOOTSTRAPPED", result
print("SEED_OK")
`;

async function createCampaignViaUi(page, strategyLabel) {
  // 前提：holding 行显示「创建 Campaign」按钮（DRAFT 不算 current，入口持续存在）
  await page.click("button:has-text('创建 Campaign')");
  await page.waitForSelector("text=不会自动激活");
  await page.click(`label:has-text('${strategyLabel}')`);
  await page.click("button:has-text('确认创建 Campaign')");
  await page.waitForSelector("text=尚未进入当前 Campaign");
}

async function runE2E() {
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-inbox-e2e-"));
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

    console.log(`[E2E] seeding position reality bootstrap...`);
    const pyCmd = py.cmd === "py" ? "py -3" : py.cmd;
    const seedOut = execSync(pyCmd, {
      input: SEED_SCRIPT,
      env,
      cwd: backendDir,
      encoding: "utf8",
    });
    assert.ok(seedOut.includes("SEED_OK"), `seed failed: ${seedOut}`);

    console.log(`[E2E] starting FastAPI backend on port ${backendPort}...`);
    backendProc = spawn(
      py.cmd,
      [...py.extraArgs, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
      { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"] },
    );
    backendProc.stdout.on("data", (chunk) => process.stdout.write(`[backend] ${chunk}`));
    backendProc.stderr.on("data", (chunk) => process.stderr.write(`[backend] ${chunk}`));

    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    console.log(`[E2E] backend ready.`);

    staticServer = await startStaticServer(frontendDist, frontendPort);

    browser = await chromium.launch({
      executablePath: findChromium(),
      headless: true,
    });
    const context = await browser.newContext();
    const page = await context.newPage();
    const forbiddenMutationRequests = [];
    page.on("request", (request) => {
      if (request.method() !== "POST") return;
      const pathname = new URL(request.url()).pathname;
      if (
        /\/api\/campaigns\/[^/]+\/transitions$/.test(pathname)
        || /\/api\/campaigns\/[^/]+\/thesis-binding$/.test(pathname)
        || /\/api\/thesis\/[^/]+\/(begin-formalization|confirm|freeze)$/.test(pathname)
      ) {
        forbiddenMutationRequests.push(pathname);
      }
    });

    await page.route("**/api/**", (route) => {
      const u = new URL(route.request().url());
      route.continue({ url: `http://127.0.0.1:${backendPort}${u.pathname}${u.search}` });
    });

    // 1. UNASSIGNED row + CREATE_CAMPAIGN
    console.log("[E2E] 1. opening /decision-inbox...");
    await page.goto(`http://127.0.0.1:${frontendPort}/decision-inbox`, {
      waitUntil: "networkidle",
    });
    await page.waitForSelector("h1:has-text('决策待办')");
    await page.waitForSelector("h2:has-text('待建立 Campaign 的持仓')");
    await page.waitForSelector("text=600519");
    await page.waitForSelector("text=未分配 Campaign");

    // 2. 创建表单：strategy 必选（未选时提交禁用）+ 显式 DRAFT 确认文案
    console.log("[E2E] 2. CREATE_CAMPAIGN form requires strategy...");
    await page.click("button:has-text('创建 Campaign')");
    await page.waitForSelector("text=不会自动激活");
    await page.waitForSelector("text=证券代码（固定，不可修改）");
    assert.equal(
      await page.locator("text=只读，所有变更经显式操作").count(),
      0,
      "page copy must not claim read-only while create/transition exist",
    );
    const submitBtn = page.locator("button:has-text('确认创建 Campaign')");
    assert.equal(await submitBtn.isDisabled(), true, "strategy selection required");

    // 3. 创建 SWING → 自动收起表单并定位到 DRAFT setup card；holding 仍 UNASSIGNED
    console.log("[E2E] 3. creating SWING campaign (DRAFT) and continuing to setup...");
    await page.click("label:has-text('波段')");
    await page.click("button:has-text('确认创建 Campaign')");
    await page.waitForSelector("h2:has-text('正在建立的 Campaign')");
    await page.waitForSelector('[data-campaign-setup-focused="true"]');
    const focusedSetupCard = page.locator('[data-campaign-setup-focused="true"]');
    await focusedSetupCard.getByTestId("campaign-setup-continuation").getByText("下一步从这里继续").waitFor();
    await focusedSetupCard.locator('[data-campaign-role="setup"]').waitFor();
    const swingCard = page.locator('[data-campaign-strategy="SWING"][data-campaign-role="setup"]');
    await swingCard.getByText("尚未进入当前 Campaign").waitFor();
    await swingCard.getByText("600519").waitFor();
    await focusedSetupCard.locator('[data-campaign-thesis]').waitFor();
    await focusedSetupCard.getByText("新建 Formal Thesis 草稿").waitFor();
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "DRAFT");
    assert.equal(await swingCard.getAttribute("data-campaign-role"), "setup");
    assert.equal(await page.getByTestId("create-campaign-form").count(), 0, "create form must auto-close after success");
    assert.equal(await page.getByText("Campaign 已创建（状态：草稿）").count(), 0, "success card must not block setup continuation");
    assert.deepEqual(forbiddenMutationRequests, [], "creation continuation must not mutate lifecycle or Thesis");
    // DRAFT 不算 current：holding 行仍 UNASSIGNED（创建入口仍在）
    await page.waitForSelector("text=未分配 Campaign");

    // 4. 刷新后 DRAFT 仍持续存在（不依赖 transient focus component）
    console.log("[E2E] 4. refresh keeps DRAFT reachable...");
    await page.click("button:has-text('刷新')");
    await swingCard.getByText("尚未进入当前 Campaign").waitFor();
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "DRAFT");

    // 5. 同 Security 再创建 MEDIUM DRAFT（两个 setup 卡共存）
    console.log("[E2E] 5. second campaign (MEDIUM DRAFT) coexists...");
    await createCampaignViaUi(page, "中线");
    const mediumCard = page.locator('[data-campaign-strategy="MEDIUM"]');
    await mediumCard.getByText("尚未进入当前 Campaign").waitFor();
    assert.equal(await mediumCard.getAttribute("data-campaign-status"), "DRAFT");
    assert.equal(await mediumCard.getAttribute("data-campaign-role"), "setup");

    // 6. SWING 显式 lifecycle（每步一次点击，无链式；用「下一动作按钮出现」证明到达）
    console.log("[E2E] 6. explicit SWING lifecycle...");
    await swingCard.locator('button:has-text("开始研究")').click();
    await swingCard.locator('button:has-text("标记待入场")').waitFor(); // RESEARCHING
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "RESEARCHING");
    await swingCard.locator('button:has-text("标记待入场")').click();
    await swingCard.locator('button:has-text("激活 Campaign")').waitFor(); // PRE-ENTRY
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "PRE-ENTRY");
    await swingCard.locator('button:has-text("激活 Campaign")').click();

    // 7. ACTIVE：SWING 离开 setup，进入决策项；MEDIUM DRAFT sibling 仍可见
    console.log("[E2E] 7. ACTIVE recognized by inbox; DRAFT sibling stays reachable...");
    const swingActiveCard = page.locator(
      '[data-campaign-strategy="SWING"][data-campaign-status="ACTIVE"]',
    );
    await swingActiveCard.waitFor();
    await page.waitForSelector("h2:has-text('当前 Campaign')");
    await swingActiveCard.getByText("当前 Campaign", { exact: true }).waitFor();
    assert.equal(await swingActiveCard.getAttribute("data-campaign-role"), "current");
    // MEDIUM DRAFT 仍在 setup section（ACTIVE sibling 不隐藏 DRAFT sibling）
    await page.waitForSelector("h2:has-text('正在建立的 Campaign')");
    await mediumCard.getByText("尚未进入当前 Campaign").waitFor();
    assert.equal(await mediumCard.getAttribute("data-campaign-role"), "setup");
    // 诚实状态：绝不显示 NO_ACTION_REQUIRED；reason code 不以调试串作为主解释
    assert.equal(
      await page.locator("text=NO_ACTION_REQUIRED").count(),
      0,
      "must not fake a clean NO_ACTION_REQUIRED",
    );
    await swingActiveCard.getByText("尚未绑定正式投资逻辑", { exact: true }).waitFor();
    await swingActiveCard.getByText("设置尚未完成", { exact: true }).waitFor();
    assert.equal(
      await swingActiveCard.getByText("THESIS_MISSING / THESIS_UNKNOWN").count(),
      0,
      "raw reason dump must not be the primary explanation",
    );

    // 8. 刷新后状态保持（backend 权威）
    console.log("[E2E] 8. refresh preserves backend state...");
    await page.click("button:has-text('刷新')");
    await swingActiveCard.getByText("当前 Campaign", { exact: true }).waitFor();
    await mediumCard.getByText("尚未进入当前 Campaign").waitFor();

    // 8b. destructive 需要二次确认，取消后状态不变
    console.log("[E2E] 8b. destructive action requires confirm...");
    await mediumCard.locator('button[data-action-kind="destructive"]:has-text("拒绝 Campaign")').click();
    await mediumCard.locator('[data-destructive-confirm="REJECTED"]').waitFor();
    await mediumCard.locator('button:has-text("取消")').click();
    assert.equal(await mediumCard.locator("[data-destructive-confirm]").count(), 0);
    assert.equal(await mediumCard.getAttribute("data-campaign-status"), "DRAFT");

    // 9. 非法 transition（MEDIUM DRAFT→ACTIVE 直跳）→ backend 409；刷新后仍「草稿」
    console.log("[E2E] 9. illegal transition rejected (409) + state unchanged...");
    const mediumResp = await page.request.get(
      `http://127.0.0.1:${backendPort}/api/campaigns?strategy=MEDIUM`,
    );
    assert.equal(mediumResp.status(), 200);
    const mediumId = (await mediumResp.json()).data[0].campaign_id;
    const illegal = await page.request.post(
      `http://127.0.0.1:${backendPort}/api/campaigns/${mediumId}/transitions`,
      { data: { expected_status: "DRAFT", to_status: "ACTIVE" } },
    );
    assert.equal(illegal.status(), 409);
    await page.click("button:has-text('刷新')");
    await mediumCard.getByText("尚未进入当前 Campaign").waitFor();
    assert.equal(
      await mediumCard.getAttribute("data-campaign-status"),
      "DRAFT",
      "MEDIUM must remain DRAFT after rejected transition",
    );

    // 9b. UI 409：点击合法推进但 backend 拒绝 → 显示失败，不本地改状态
    console.log("[E2E] 9b. UI 409 honesty...");
    await page.route(`**/api/campaigns/${mediumId}/transitions`, (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Campaign 状态冲突" }),
        });
      }
      return route.continue();
    });
    await mediumCard.locator('button[data-action-kind="advance"]:has-text("开始研究")').click();
    await mediumCard.getByText("未能变更状态").waitFor();
    assert.equal(await mediumCard.getAttribute("data-campaign-status"), "DRAFT");

    console.log("[E2E] Decision Inbox E2E test passed successfully!");
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
