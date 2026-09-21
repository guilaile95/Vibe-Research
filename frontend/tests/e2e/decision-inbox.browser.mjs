/**
 * 决策待办（Decision Inbox）— Real FastAPI Backend Playwright E2E（P0-CS1-R1）。
 *
 * 开启真实 FastAPI 后端与前端构建产物，使用独立临时数据目录。
 * 覆盖 render-level 产品闭环（R1 blocker 修复的证明）：
 *
 * 1. 种子：bootstrap position reality（600519 legacy holding）。
 * 2. /decision-inbox → UNASSIGNED_HOLDING 行 + 「创建 Campaign」按钮。
 * 3. 创建 SWING → 创建表单自动收起，选中新 DRAFT setup card；
 *    同一详情直接展示 Campaign lifecycle 与 Current Thesis 下一步入口。
 * 4. 刷新后 DRAFT 仍持续存在（不依赖 transient focus component）。
 * 5. 同 Security 再创建 MEDIUM DRAFT —— 两个 setup 计划是工作列表里的两个独立行。
 * 6. SWING 显式点击：开始研究 → 标记待入场；PRE-ENTRY 不提供无交易激活。
 * 7. 夹具在 store 层种入既有 ACTIVE 历史后：SWING 离开 setup 区域，进入「当前 Campaign」；
 *    MEDIUM DRAFT sibling 仍可达（ACTIVE sibling 不隐藏 DRAFT sibling）；
 *    决策状态为诚实状态（绝不显示 NO_ACTION_REQUIRED）。
 * 8. 刷新后状态保持（backend 权威，无本地伪造）。
 * 9. 非法 transition（MEDIUM DRAFT→ACTIVE 直跳）→ backend 409；
 *    刷新后 MEDIUM 仍「草稿」（状态绝不本地推进）。
 *
 * IA-CONVERGENCE-V1：分组由三个页签承载（当前投资计划 / 正在建立的投资计划 /
 * 尚未建立投资计划的持仓），左侧工作列表一行一个对象（campaign_id 或 security_code），
 * 右侧只挂载「当前选中对象」的详情 —— 计划不再同时展开。
 * 因此本测试用 selectInboxGroup / selectInboxItem 显式表达「先选分组、再选对象」，
 * 被证实的性质（身份唯一、状态以后端为准、草稿不进入 current）都没有放宽。
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
import { seedActiveCampaign } from "./campaign-active-fixture.mjs";

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
  if (
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
    && existsSync(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH)
  ) return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
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

// 新 IA：右侧只挂载「选中对象」的详情，选中对象由工作列表行决定。
// 下面几个 helper 就是这条规则的显式表达：先落分组页签，再点工作列表行。
async function selectInboxGroup(page, key) {
  const tab = page.getByTestId(`decision-inbox-tab-${key}`);
  await tab.waitFor({ state: "visible", timeout: 15000 });
  if ((await tab.getAttribute("aria-selected")) !== "true") await tab.click();
  await page.waitForFunction(
    (k) =>
      document.querySelector(`[data-testid="decision-inbox-tab-${k}"]`)?.getAttribute("aria-selected") === "true",
    key,
    { timeout: 15000 },
  );
}

async function selectInboxItem(page, id) {
  const item = page.getByTestId(`decision-inbox-item-${id}`);
  await item.waitFor({ state: "visible", timeout: 15000 });
  if ((await item.getAttribute("data-selected")) !== "true") await item.click();
  await page.waitForFunction(
    (i) =>
      document.querySelector(`[data-testid="decision-inbox-item-${i}"]`)?.getAttribute("data-selected") === "true",
    id,
    { timeout: 15000 },
  );
}

/** 持仓条目身份 = security_code（在「尚未建立投资计划的持仓」分组）。 */
async function selectHoldingItem(page, code) {
  await selectInboxGroup(page, "unassigned");
  await selectInboxItem(page, code);
}

/** 投资计划条目身份 = campaign_id：先定位它所在的分组，再选中它。 */
async function selectCampaignItem(page, campaignId) {
  for (const key of ["current", "setup"]) {
    await selectInboxGroup(page, key);
    if ((await page.getByTestId(`decision-inbox-item-${campaignId}`).count()) > 0) {
      await selectInboxItem(page, campaignId);
      return;
    }
  }
  throw new Error(`Campaign ${campaignId} 不在决策待办工作列表中`);
}

/** 点击刷新，并等后端快照真正返回，避免读取刷新前的 DOM。 */
async function clickRefresh(page) {
  const reloaded = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/decision-inbox",
  );
  await page.click("button:has-text('刷新')");
  await reloaded;
}

async function createCampaignViaUi(page, strategyLabel) {
  // 前提：holding 行显示「创建投资计划」按钮（DRAFT 不算 current，入口持续存在）。
  // 创建按钮只属于当前选中对象，所以先选中该持仓。
  await selectHoldingItem(page, "600519");
  await page.getByTestId("decision-inbox-create-campaign-600519").click();
  await page.waitForSelector("text=不会自动激活");
  await page.click(`label:has-text('${strategyLabel}')`);
  await page.click("button:has-text('确认创建投资计划')");
  await page.waitForSelector("text=这项投资计划尚未生效");
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
    // 新 IA：三个分组页签常驻；默认落在第一个非空分组（此处只有未建立计划的持仓）。
    for (const key of ["current", "setup", "unassigned"]) {
      await page.getByTestId(`decision-inbox-tab-${key}`).waitFor();
    }
    assert.equal(
      await page.getByTestId("decision-inbox-tab-unassigned").getAttribute("aria-selected"),
      "true",
      "只有未建立计划的持仓时，默认分组应为「尚未建立投资计划的持仓」",
    );
    await page.waitForSelector("h2:has-text('尚未建立投资计划的持仓')");
    await page.waitForSelector("text=600519");
    await page.waitForSelector("text=尚无投资计划");
    // 工作列表一行一个对象，且默认选中第一行（右侧详情随之出现）。
    await page.getByTestId("decision-inbox-item-600519").waitFor();
    assert.equal(
      await page.getByTestId("decision-inbox-item-600519").getAttribute("data-selected"),
      "true",
    );

    // 2. 创建表单：strategy 必选（未选时提交禁用）+ 显式 DRAFT 确认文案
    console.log("[E2E] 2. CREATE_CAMPAIGN form requires strategy...");
    await page.click("button:has-text('创建投资计划')");
    await page.waitForSelector("text=不会自动激活");
    await page.waitForSelector("text=证券代码（固定，不可修改）");
    assert.equal(
      await page.locator("text=只读，所有变更经显式操作").count(),
      0,
      "page copy must not claim read-only while create/transition exist",
    );
    const submitBtn = page.locator("button:has-text('确认创建投资计划')");
    assert.equal(await submitBtn.isDisabled(), true, "strategy selection required");

    // 3. 创建 SWING → 自动收起表单并定位到 DRAFT setup card；holding 仍 UNASSIGNED
    console.log("[E2E] 3. creating SWING campaign (DRAFT) and continuing to setup...");
    await page.click("label:has-text('波段')");
    await page.click("button:has-text('确认创建投资计划')");
    await page.waitForSelector("h2:has-text('正在建立的投资计划')");
    await page.waitForSelector('[data-campaign-setup-focused="true"]');
    const focusedSetupCard = page.locator('[data-campaign-setup-focused="true"]');
    await focusedSetupCard.getByTestId("campaign-setup-continuation").getByText("下一步从这里继续").waitFor();
    await focusedSetupCard.locator('[data-campaign-role="setup"]').waitFor();
    const swingCard = page.locator('[data-campaign-strategy="SWING"][data-campaign-role="setup"]');
    await swingCard.getByText("这项投资计划尚未生效", { exact: false }).waitFor();
    await swingCard.getByText("600519").waitFor();
    await focusedSetupCard.locator('[data-campaign-thesis]').waitFor();
    await focusedSetupCard.getByText("新建正式投资逻辑草稿").waitFor();
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "DRAFT");
    assert.equal(await swingCard.getAttribute("data-campaign-role"), "setup");
    assert.equal(await page.getByTestId("create-campaign-form").count(), 0, "create form must auto-close after success");
    assert.equal(await page.getByText("Campaign 已创建（状态：草稿）").count(), 0, "success card must not block setup continuation");
    assert.deepEqual(forbiddenMutationRequests, [], "creation continuation must not mutate lifecycle or Thesis");
    const swingId = await swingCard.getAttribute("data-campaign-id");
    assert.ok(swingId, "SWING Campaign id must be present on the lifecycle card");
    // DRAFT 不算 current：切回「尚未建立投资计划的持仓」，holding 行仍在（入口仍在）。
    // 新 IA 下右侧只展示选中对象，所以必须显式选中该行后才能读它的详情。
    await selectHoldingItem(page, "600519");
    await page.getByTestId("decision-inbox-item-600519").getByText("尚无投资计划").waitFor();
    await page
      .getByTestId("decision-inbox-actions")
      .getByTestId("decision-inbox-create-campaign-600519")
      .waitFor();

    // 4. 刷新后 DRAFT 仍持续存在（不依赖 transient focus component）
    console.log("[E2E] 4. refresh keeps DRAFT reachable...");
    await clickRefresh(page);
    await selectCampaignItem(page, swingId);
    await swingCard.getByText("这项投资计划尚未生效", { exact: false }).waitFor();
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "DRAFT");

    // 5. 同 Security 再创建 MEDIUM DRAFT
    console.log("[E2E] 5. second campaign (MEDIUM DRAFT) coexists...");
    await createCampaignViaUi(page, "中线");
    const mediumCard = page.locator('[data-campaign-strategy="MEDIUM"]');
    await mediumCard.getByText("这项投资计划尚未生效", { exact: false }).waitFor();
    assert.equal(await mediumCard.getAttribute("data-campaign-status"), "DRAFT");
    assert.equal(await mediumCard.getAttribute("data-campaign-role"), "setup");
    const mediumId = await mediumCard.getAttribute("data-campaign-id");
    assert.ok(mediumId, "MEDIUM Campaign id must be present on the lifecycle card");

    // 5b. 新 IA 下两个 setup 计划不再同时展开；同一性质改由「工作列表两行 + 选中谁只展示谁」
    // 证明：两个 campaign_id 都是独立的可选中行，切来切去右侧只出现被选中的那一个。
    console.log("[E2E] 5b. both setup plans exist as distinct worklist rows...");
    const setupWorklist = page.getByTestId("decision-inbox-worklist");
    await setupWorklist.getByTestId(`decision-inbox-item-${swingId}`).waitFor();
    await setupWorklist.getByTestId(`decision-inbox-item-${mediumId}`).waitFor();
    await selectInboxItem(page, swingId);
    await swingCard.waitFor();
    assert.equal(
      await page.locator('[data-campaign-strategy="MEDIUM"]').count(),
      0,
      "未选中的投资计划不得同时展开",
    );
    await selectInboxItem(page, mediumId);
    await mediumCard.waitFor();
    assert.equal(
      await page.locator('[data-campaign-strategy="SWING"]').count(),
      0,
      "未选中的投资计划不得同时展开",
    );

    // 6. SWING 显式 lifecycle（每步一次点击，无链式）；PRE-ENTRY 必须等待交易证明。
    console.log("[E2E] 6. explicit SWING lifecycle...");
    await selectInboxItem(page, swingId);
    await swingCard.locator('button:has-text("开始研究")').click();
    await swingCard.locator('button:has-text("标记待入场")').waitFor(); // RESEARCHING
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "RESEARCHING");
    await swingCard.locator('button:has-text("标记待入场")').click();
    await page.waitForFunction(
      (campaignId) => document.querySelector(`[data-campaign-id="${campaignId}"]`)?.getAttribute("data-campaign-status") === "PRE-ENTRY",
      swingId,
    );
    assert.equal(await swingCard.getAttribute("data-campaign-status"), "PRE-ENTRY");
    assert.equal(
      await swingCard.locator('button:has-text("启用投资计划")').count(),
      0,
      "PRE-ENTRY must not expose generic activation without an attributed executed BUY",
    );

    // Decision Inbox 只验证既有 ACTIVE 的组合读取；直接 store seed 是隔离夹具，
    // 不伪装成生产命令，也不放宽公开 API 的 trade-proven gate。
    seedActiveCampaign(backendDir, env, swingId);
    await clickRefresh(page);

    // 7. ACTIVE fixture：SWING 进入「当前投资计划」；MEDIUM DRAFT sibling 仍可达
    console.log("[E2E] 7. ACTIVE recognized by inbox; DRAFT sibling stays reachable...");
    const swingActiveCard = page.locator(
      '[data-campaign-strategy="SWING"][data-campaign-status="ACTIVE"]',
    );
    // 显式选中 SWING（它会从 setup 分组移到 current 分组）。
    await selectCampaignItem(page, swingId);
    await page.waitForSelector("h2:has-text('当前投资计划')");
    await swingActiveCard.waitFor();
    await swingActiveCard.getByText("当前投资计划", { exact: true }).waitFor();
    assert.equal(await swingActiveCard.getAttribute("data-campaign-role"), "current");
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
    // ACTIVE sibling 不隐藏 DRAFT sibling：MEDIUM 仍是「正在建立」页签里的独立工作列表行，
    // 选中它时右侧只展示它自己。
    await selectCampaignItem(page, mediumId);
    await page.waitForSelector("h2:has-text('正在建立的投资计划')");
    await mediumCard.getByText("这项投资计划尚未生效", { exact: false }).waitFor();
    assert.equal(await mediumCard.getAttribute("data-campaign-role"), "setup");
    assert.equal(
      await page.locator('[data-campaign-strategy="SWING"]').count(),
      0,
      "未选中的投资计划不得同时展开",
    );

    // 8. 刷新后状态保持（backend 权威）
    console.log("[E2E] 8. refresh preserves backend state...");
    await clickRefresh(page);
    await selectCampaignItem(page, swingId);
    await swingActiveCard.getByText("当前投资计划", { exact: true }).waitFor();
    await selectCampaignItem(page, mediumId);
    await mediumCard.getByText("这项投资计划尚未生效", { exact: false }).waitFor();
    assert.equal(
      await mediumCard.getAttribute("data-campaign-status"),
      "DRAFT",
      "MEDIUM must remain DRAFT after refresh",
    );

    // 8b. destructive 需要二次确认，取消后状态不变
    console.log("[E2E] 8b. destructive action requires confirm...");
    await mediumCard.locator('button[data-action-kind="destructive"]:has-text("放弃投资计划")').click();
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
    const mediumFromApi = (await mediumResp.json()).data[0].campaign_id;
    assert.equal(mediumFromApi, mediumId, "UI 上的 Campaign 身份必须与后端一致");
    const illegal = await page.request.post(
      `http://127.0.0.1:${backendPort}/api/campaigns/${mediumFromApi}/transitions`,
      { data: { expected_status: "DRAFT", to_status: "ACTIVE" } },
    );
    assert.equal(illegal.status(), 409);
    await clickRefresh(page);
    // 刷新后仍停在 MEDIUM（选中对象是它自己），状态以后端为准。
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
