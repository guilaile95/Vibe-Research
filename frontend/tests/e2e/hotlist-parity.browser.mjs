/** Real browser + real backend E2E for Hotlist & Source Persistence (TREND-PARITY Wave 1). */
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
const tempDir = mkdtempSync(join(tmpdir(), "vr-hotlist-parity-"));

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
      "hotlist_parity_harness_app:app",
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
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  // 绝不 mock /api/native-intel/sources 或 hotlist，真实全流量转发到 harness FastAPI + SQLite
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
    await route.fulfill({
      status: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      body: Buffer.from(await response.arrayBuffer()),
    });
  });

  // -------------------------------------------------------------------------
  // 1. 设置页：11 个系统热榜展示、启停持久化与自建源生命周期
  // -------------------------------------------------------------------------
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });
  const sectionTitle = page.locator("text=资讯源与热榜管理");
  await sectionTitle.waitFor({ state: "visible", timeout: 15000 });

  // 1.1 校验全部 11 个系统热榜均在设置页可见
  const expectedHotlists = [
    "财联社热门",
    "华尔街见闻",
    "今日头条",
    "百度热搜",
    "澎湃新闻",
    "Bilibili 热搜",
    "凤凰网",
    "贴吧",
    "微博",
    "抖音",
    "知乎",
  ];
  for (const name of expectedHotlists) {
    await page.locator(`.divide-y > div:has-text("${name}")`).first().waitFor({ state: "visible", timeout: 10000 });
  }

  // 1.2 校验系统源启停并跨刷新保持持久化（以微博为例）
  const weiboRow = page.locator('.divide-y > div:has-text("微博")').first();
  const weiboToggle = weiboRow.locator('button:has-text("停用")');
  await weiboToggle.waitFor({ state: "visible", timeout: 5000 });
  await weiboToggle.click();
  await weiboRow.locator('button:has-text("启用")').waitFor({ state: "visible", timeout: 5000 });

  // 刷新后仍为停用（enabled=false 持久化）
  await page.reload({ waitUntil: "domcontentloaded" });
  const weiboRowReloaded = page.locator('.divide-y > div:has-text("微博")').first();
  await weiboRowReloaded.locator('button:has-text("启用")').waitFor({ state: "visible", timeout: 10000 });
  // 恢复启用
  await weiboRowReloaded.locator('button:has-text("启用")').click();
  await weiboRowReloaded.locator('button:has-text("停用")').waitFor({ state: "visible", timeout: 5000 });

  // 1.3 用户自定义 RSS 源新增、持久化与软删除
  const nameInput = page.locator('input[placeholder*="来源名称"]');
  const urlInput = page.locator('input[placeholder*="RSS / Atom"]');
  const submitBtn = page.locator('button:has-text("添加源")');

  await nameInput.waitFor({ state: "visible", timeout: 5000 });
  await nameInput.fill("E2E自选科技源");
  await urlInput.fill("https://example.test/e2e-custom.xml");
  await submitBtn.click();

  // 等待 UI 上显示新增源
  const newSourceText = page.locator("text=E2E自选科技源");
  await newSourceText.waitFor({ state: "visible", timeout: 10000 });

  // 直连后端校验真实落库与 origin 属性
  const backendCheck1 = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/sources`);
  const sourcesData1 = await backendCheck1.json();
  const foundSrc = (sourcesData1.sources || []).find((s) => s.name === "E2E自选科技源");
  assert.ok(foundSrc, "User source must be persisted in backend SQLite");
  assert.equal(foundSrc.origin, "user");
  assert.equal(foundSrc.url, "https://example.test/e2e-custom.xml");

  // 刷新页面，验证重启/刷新后持久化仍然有效
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator("text=E2E自选科技源").waitFor({ state: "visible", timeout: 10000 });

  // UI 执行软删除
  const userRow = page.locator(".divide-y > div", { hasText: "E2E自选科技源" });
  await userRow.waitFor({ state: "visible", timeout: 5000 });
  const deleteBtn = userRow.locator('button[title*="删除"]');
  await deleteBtn.waitFor({ state: "visible", timeout: 5000 });
  await deleteBtn.click();

  // 确认 UI 移除
  await userRow.waitFor({ state: "hidden", timeout: 10000 });

  // 直连后端确认活跃源中已剔除
  const backendCheck2 = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/sources`);
  const sourcesData2 = await backendCheck2.json();
  assert.ok(
    !(sourcesData2.sources || []).some((s) => s.name === "E2E自选科技源"),
    "Deleted source must not appear in active sources list",
  );

  // 刷新后确认已彻底消失
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(500);
  assert.equal(await page.locator(".divide-y > div", { hasText: "E2E自选科技源" }).count(), 0);

  // -------------------------------------------------------------------------
  // 2. 资讯页：多平台热榜面板渲染与动态下拉筛选（硬断言，绝不静默跳过）
  // -------------------------------------------------------------------------
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  const hotlistTab = page.locator("button", { hasText: "实时热榜" });
  await hotlistTab.waitFor({ state: "visible", timeout: 10000 });
  await hotlistTab.click();

  const hotlistPanel = page.getByTestId("native-intel-hotlist-panel");
  await hotlistPanel.waitFor({ state: "visible", timeout: 10000 });

  // 2.1 新鲜状态验证：标题、徽章与各平台种子条目
  await hotlistPanel.getByText("实时热榜追踪").waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByTestId("hotlist-freshness-badge").waitFor({ state: "visible", timeout: 5000 });
  assert.equal(await hotlistPanel.getByTestId("hotlist-freshness-badge").innerText(), "原生热点观测");
  assert.equal(await hotlistPanel.getByTestId("hotlist-stale-banner").count(), 0);

  // 校验动态来源选择器存在
  const sourceSelect = hotlistPanel.locator('[data-testid="hotlist-source-select"]');
  await sourceSelect.waitFor({ state: "visible", timeout: 5000 });

  // 校验初始全量条目均可见
  await hotlistPanel.getByText("科技股全线走强", { exact: true }).waitFor({ state: "visible", timeout: 10000 });
  await hotlistPanel.getByText("微博热议人工智能", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("知乎深度解析芯片突破", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("百度热搜机器人产业", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // 2.2 动态来源筛选：选微博 → 只出现微博条目
  await sourceSelect.selectOption("hotlist-weibo");
  await hotlistPanel.getByText("微博热议人工智能", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  assert.equal(await hotlistPanel.getByText("科技股全线走强", { exact: true }).count(), 0);
  assert.equal(await hotlistPanel.getByText("知乎深度解析芯片突破", { exact: true }).count(), 0);
  assert.equal(await hotlistPanel.getByText("百度热搜机器人产业", { exact: true }).count(), 0);

  // 2.3 动态来源筛选：选知乎 → 只出现知乎条目
  await sourceSelect.selectOption("hotlist-zhihu");
  await hotlistPanel.getByText("知乎深度解析芯片突破", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  assert.equal(await hotlistPanel.getByText("微博热议人工智能", { exact: true }).count(), 0);
  assert.equal(await hotlistPanel.getByText("科技股全线走强", { exact: true }).count(), 0);

  // 2.4 切回全部来源 → 多平台同时恢复
  await sourceSelect.selectOption("");
  await hotlistPanel.getByText("科技股全线走强", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("微博热议人工智能", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("知乎深度解析芯片突破", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await hotlistPanel.getByText("百度热搜机器人产业", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // 2.5 过期状态诚实性验证：抓取时间超过 6 小时后，UI 必须显式降级为非实时 / 已过期
  await fetch(`http://127.0.0.1:${backendPort}/api/test/make-stale`, { method: "POST" });
  await page.reload({ waitUntil: "domcontentloaded" });
  const hotlistTab2 = page.locator("button", { hasText: "实时热榜" });
  await hotlistTab2.waitFor({ state: "visible", timeout: 10000 });
  await hotlistTab2.click();
  const stalePanel = page.getByTestId("native-intel-hotlist-panel");
  await stalePanel.waitFor({ state: "visible", timeout: 10000 });

  // 校验过期标识与警告条
  await stalePanel.getByTestId("hotlist-stale-banner").waitFor({ state: "visible", timeout: 5000 });
  await stalePanel.getByText("热榜数据追踪（非实时）").waitFor({ state: "visible", timeout: 5000 });
  assert.equal(await stalePanel.getByTestId("hotlist-freshness-badge").innerText(), "数据已过期 (非实时)");
  // 校验排名降级为 —，保留末次 rank 供审计说明
  await stalePanel.getByText("末次 #1 (已过期)").waitFor({ state: "visible", timeout: 5000 });
  assert.ok((await stalePanel.getByText("已过期").count()) > 0);

  // 2.6 恢复新鲜数据
  await fetch(`http://127.0.0.1:${backendPort}/api/test/make-fresh`, { method: "POST" });

  assert.deepEqual(pageErrors, []);
  console.log("Hotlist parity real browser + real backend E2E: PASS");
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
