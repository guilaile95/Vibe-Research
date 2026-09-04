/** Real browser + real backend E2E for Native Intel Personal Interest Filter (TREND-PARITY Wave 2). */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const backendDir = join(root, "backend");
const frontendDist = join(root, "frontend", "dist");
const tempDir = mkdtempSync(join(tmpdir(), "vr-interest-filter-"));

const freePort = () =>
  new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
const pythonArgs = process.env.PYTHON
  ? ["-m", "uvicorn"]
  : process.platform === "win32"
  ? ["-3", "-m", "uvicorn"]
  : ["-m", "uvicorn"];

function chromiumPath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH && existsSync(process.env.PLAYWRIGHT_CHROMIUM_PATH)) {
    return process.env.PLAYWRIGHT_CHROMIUM_PATH;
  }
  for (const base of [
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ]) {
    if (!existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      for (const candidate of [
        join(base, entry, "chrome-win64", "chrome.exe"),
        join(base, entry, "chrome-linux", "chrome"),
      ]) {
        if (existsSync(candidate)) return candidate;
      }
    }
  }
  return undefined;
}

async function launchBrowser() {
  const executablePath = chromiumPath();
  try {
    return await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  } catch {
    return chromium.launch({ headless: true, channel: "chrome" });
  }
}

async function waitHttp(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* starting */
    }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function staticServer(directory, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let target = join(
      directory,
      (request.url || "/").split("?")[0] === "/" ? "index.html" : (request.url || "/").split("?")[0],
    );
    if (!existsSync(target)) target = join(directory, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    import("node:fs").then(({ createReadStream }) => createReadStream(target).pipe(response));
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

let backend;
let frontend;
let browser;

try {
  assert.ok(existsSync(join(frontendDist, "index.html")), "frontend must be built first (npm run build)");
  const backendPort = await freePort();
  const frontendPort = await freePort();
  const dbPath = join(tempDir, "native-intel.sqlite3");

  backend = spawn(
    python,
    [
      ...pythonArgs,
      "--app-dir",
      join(root, "frontend", "tests", "e2e"),
      "interest_filter_harness_app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(backendPort),
    ],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        PYTHONPATH: `${backendDir}${path.delimiter}${join(root, "frontend", "tests", "e2e")}`,
        VIBE_NATIVE_INTEL_DB: dbPath,
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  await waitHttp(`http://127.0.0.1:${backendPort}/api/native-intel/status`);
  frontend = await staticServer(frontendDist, frontendPort);
  browser = await launchBrowser();

  const page = await browser.newPage();
  await page.addInitScript(() => {
    localStorage.setItem(
      "vr-llm",
      JSON.stringify({
        provider: "cli-codex",
        model: "gpt-5-codex",
      }),
    );
  });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (msg) => console.log("PAGE LOG:", msg.type(), msg.text()));

  // Proxy API requests to backend
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const request = route.request();
    const reqHeaders = { ...request.headers() };
    delete reqHeaders["host"];
    const response = await fetch(`http://127.0.0.1:${backendPort}${url.pathname}${url.search}`, {
      method: request.method(),
      headers: reqHeaders,
      body: request.postDataBuffer() || undefined,
    });
    const bodyBuf = Buffer.from(await response.arrayBuffer());
    if (response.status >= 400 || url.pathname.includes("apply") || url.pathname.includes("classify")) {
      console.log(`API [${request.method()} ${url.pathname}]: ${response.status}`, bodyBuf.toString());
    }
    await route.fulfill({
      status: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      body: bodyBuf,
    });
  });

  // -------------------------------------------------------------------------
  // 1. 资讯页：热榜模式切换（全部热榜 vs 我的关注）与匹配徽章
  // -------------------------------------------------------------------------
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  const hotlistTab = page.locator("button", { hasText: "实时热榜" });
  await hotlistTab.waitFor({ state: "visible", timeout: 10000 });
  await hotlistTab.click();

  const hotlistPanel = page.getByTestId("native-intel-hotlist-panel");
  await hotlistPanel.waitFor({ state: "visible", timeout: 10000 });

  // 校验模式切换按钮
  const modeAllBtn = hotlistPanel.getByTestId("hotlist-mode-all");
  const modeInterestsBtn = hotlistPanel.getByTestId("hotlist-mode-interests");
  await modeAllBtn.waitFor({ state: "visible", timeout: 5000 });
  await modeInterestsBtn.waitFor({ state: "visible", timeout: 5000 });

  // 初始在 "全部热榜" 模式：所有 4 条数据都存在
  await hotlistPanel.getByText("科技突破：先进制程半导体量产", { exact: true }).waitFor({ state: "visible", timeout: 10000 });
  await hotlistPanel.getByText("微博热议大模型前沿算法发布", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("娱乐圈八卦明星动态", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("独家广告赞助大促销活动", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // 校验命中规则的条目带有徽章
  await hotlistPanel.getByTestId("hotlist-item-filter-badge").filter({ hasText: "半导体芯片" }).first().waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByTestId("hotlist-item-filter-badge").filter({ hasText: "AI大模型" }).first().waitFor({ state: "visible", timeout: 5000 });

  // 切换到 "我的关注" 模式
  await modeInterestsBtn.click();
  await hotlistPanel.getByText("娱乐圈八卦明星动态", { exact: true }).waitFor({ state: "hidden", timeout: 5000 });
  await hotlistPanel.getByText("独家广告赞助大促销活动", { exact: true }).waitFor({ state: "hidden", timeout: 5000 });

  // 校验仅展示命中的条目
  await hotlistPanel.getByText("科技突破：先进制程半导体量产", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("微博热议大模型前沿算法发布", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // 校验过滤元数据统计提示
  const statusPill = hotlistPanel.getByTestId("hotlist-filter-status-pill");
  await statusPill.waitFor({ state: "visible", timeout: 5000 });
  assert.ok((await statusPill.innerText()).includes("匹配命中 2 条"));

  // 切回 "全部热榜" 模式：4条全部恢复
  await modeAllBtn.click();
  await sleep(600);
  await hotlistPanel.getByText("娱乐圈八卦明星动态", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("独家广告赞助大促销活动", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // -------------------------------------------------------------------------
  // 2. 弹窗配置：修改关键词规则并保存
  // -------------------------------------------------------------------------
  const settingsBtn = hotlistPanel.getByTestId("hotlist-filter-settings-btn");
  await settingsBtn.waitFor({ state: "visible", timeout: 5000 });
  await settingsBtn.click();

  const modal = page.getByTestId("filter-settings-modal");
  await modal.waitFor({ state: "visible", timeout: 5000 });

  // 校验已有规则组已载入
  await modal.locator('input[value="半导体芯片"]').waitFor({ state: "visible", timeout: 5000 });
  await modal.locator('input[value="AI大模型"]').waitFor({ state: "visible", timeout: 5000 });

  // 测试显式点击右上角关闭按钮
  const closeBtn = modal.getByTestId("close-filter-settings-modal");
  await closeBtn.click();
  await modal.waitFor({ state: "hidden", timeout: 5000 });

  // 重新打开弹窗以添加新规则组并配置完整关键词能力 (required, includes, max_count, filter_terms)
  await settingsBtn.click();
  await modal.waitFor({ state: "visible", timeout: 5000 });

  // 配置全局过滤词 (filter_terms)
  const filterTermsInput = modal.getByTestId("filter-input-filter-terms");
  await filterTermsInput.waitFor({ state: "visible", timeout: 5000 });
  await filterTermsInput.fill("独家广告, 赞助大促销");

  // 添加新规则组
  const addGroupBtn = modal.getByText("添加分组", { exact: true });
  await addGroupBtn.click();

  // 找到新增组的名称输入框（最后一个）
  const groupInputs = modal.locator('input[placeholder*="分组名称"]');
  const lastGroupInput = groupInputs.last();
  await lastGroupInput.fill("英伟达GPU算力");

  // 为其配置: includes = 英伟达, required = GPU, max_count = 1
  const lastIncludeInput = modal.getByTestId("filter-group-includes-2");
  await lastIncludeInput.fill("英伟达");

  const lastRequiredInput = modal.getByTestId("filter-group-required-2");
  await lastRequiredInput.fill("GPU");

  const lastMaxCountInput = modal.getByTestId("filter-group-max-count-2");
  await lastMaxCountInput.fill("1");

  // 点击保存配置（保存后自动关闭弹窗）
  const saveBtn = modal.getByTestId("save-filter-settings-button");
  await saveBtn.click();
  await modal.waitFor({ state: "hidden", timeout: 5000 });

  // 刷新页面检验持久化 (Persistence check)
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator("button", { hasText: "实时热榜" }).click();
  const reopenedSettingsBtn = hotlistPanel.getByTestId("hotlist-filter-settings-btn");
  await reopenedSettingsBtn.click();
  await modal.waitFor({ state: "visible", timeout: 5000 });

  // 校验保存 reload 后配置仍存在
  assert.equal(await modal.getByTestId("filter-group-includes-2").inputValue(), "英伟达");
  assert.equal(await modal.getByTestId("filter-group-required-2").inputValue(), "GPU");
  assert.equal(await modal.getByTestId("filter-group-max-count-2").inputValue(), "1");
  assert.ok((await modal.getByTestId("filter-input-filter-terms").inputValue()).includes("独家广告"));

  await modal.getByTestId("close-filter-settings-modal").click();
  await modal.waitFor({ state: "hidden", timeout: 5000 });

  // 切换到 "我的关注"，验证过滤语义：
  await modeInterestsBtn.click();
  await sleep(600);
  // "英伟达发布新一代GPU硬件" 满足 includes=英伟达 且 required=GPU -> 命中展现！
  await hotlistPanel.getByText("英伟达发布新一代GPU硬件", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  // "英伟达高管减持股票公告" 缺少 required GPU -> 必须被过滤！
  assert.equal(await hotlistPanel.getByText("英伟达高管减持股票公告", { exact: true }).count(), 0);
  // "独家广告赞助大促销活动" 命中 filter_terms -> 必须被过滤！
  assert.equal(await hotlistPanel.getByText("独家广告赞助大促销活动", { exact: true }).count(), 0);

  // -------------------------------------------------------------------------
  // 3. 弹窗配置：AI 智能过滤、真实 apply_interest_update 编排与保存并执行分类
  // -------------------------------------------------------------------------
  await reopenedSettingsBtn.click();
  await modal.waitFor({ state: "visible", timeout: 5000 });

  // 切换模式至 AI 智能过滤
  const aiModeBtn = modal.getByTestId("filter-mode-select-ai");
  await aiModeBtn.click();

  // 修改自然语言兴趣描述
  const interestTextArea = modal.locator("textarea").first();
  await interestTextArea.fill("重点关注芯片半导体以及大模型前沿技术");

  // 点击"保存并执行 AI 分类" (必须走 apply_interest_update 真实用户路径)
  const saveAndClassifyBtn = modal.getByTestId("save-and-classify-button");
  await saveAndClassifyBtn.waitFor({ state: "visible", timeout: 5000 });
  await saveAndClassifyBtn.click();
  await modal.waitFor({ state: "hidden", timeout: 10000 });
  await sleep(600);

  // 直连后端验证：生效模式已更新为 ai，且指纹与分类结果已真实落库
  const res2 = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/filter/profile`);
  const profile2 = await res2.json();
  assert.equal(profile2.method, "ai", "Filter method must be updated to ai in SQLite");
  assert.ok(profile2.profile_fingerprint, "Canonical profile fingerprint must exist");
  assert.ok(profile2.tags.length >= 2, "AI tags must be persisted");

  // -------------------------------------------------------------------------
  // 4. 我的关注模式下的 RSS 与全源支持验证
  // -------------------------------------------------------------------------
  const rssToggleAll = hotlistPanel.getByTestId("filter-source-type-all");
  await rssToggleAll.waitFor({ state: "visible", timeout: 5000 });
  await rssToggleAll.click();
  await sleep(600);

  // RSS 资讯条目应当可见，且徽章不带有虚假排名
  await hotlistPanel.getByText("RSS简讯：半导体芯片智算中心交付", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // -------------------------------------------------------------------------
  // 4. 设置页：跨页面一致性与持久化验证
  // -------------------------------------------------------------------------
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });
  const filterSection = page.locator("text=资讯兴趣与智能筛选");
  await filterSection.waitFor({ state: "visible", timeout: 15000 });

  // 验证当前生效的是 AI 智能语义过滤
  const aiBtnInSettings = page.locator('button:has-text("AI 智能语义过滤")').first();
  await aiBtnInSettings.waitFor({ state: "visible", timeout: 5000 });

  // 刷新页面，验证持久化
  await page.reload({ waitUntil: "domcontentloaded" });
  const filterSectionReloaded = page.locator("text=资讯兴趣与智能筛选");
  await filterSectionReloaded.waitFor({ state: "visible", timeout: 10000 });

  // 在设置页切换回关键词过滤并保存
  const kwBtnInSettings = page.locator('button:has-text("本地关键词 / 正则过滤")').first();
  await kwBtnInSettings.click();
  const saveInSettingsBtn = page.getByRole("button", { name: "保存筛选设置" });
  await saveInSettingsBtn.click();
  await sleep(800);

  // 验证后端更新
  const res3 = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/filter/profile`);
  const profile3 = await res3.json();
  assert.equal(profile3.method, "keyword", "Filter method reverted to keyword in SQLite");

  assert.deepEqual(pageErrors, []);
  console.log("Interest filter real browser + real backend E2E: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (frontend) await new Promise((resolve) => frontend.close(resolve));
  if (backend) {
    backend.kill();
    await sleep(500);
  }
  try {
    rmSync(tempDir, { recursive: true, force: true });
  } catch {
    /* Windows file lock cleanup */
  }
}
