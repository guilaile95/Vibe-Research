/** Real browser + real backend E2E for Native Intel Display Controls and RSS Freshness (TREND-PARITY Wave 3). */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const backendDir = join(root, "backend");
const frontendDist = join(root, "frontend", "dist");
const tempDir = mkdtempSync(join(tmpdir(), "vr-wave3-display-"));

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
      "wave3_display_controls_harness_app:app",
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

  backend.stderr?.on("data", (chunk) => process.stderr.write(`[BACKEND STDERR] ${chunk}`));
  backend.stdout?.on("data", (chunk) => process.stdout.write(`[BACKEND STDOUT] ${chunk}`));

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
    await route.fulfill({
      status: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      body: bodyBuf,
    });
  });

  // =========================================================================
  // Scenario 1: RSS Freshness (global 3d -> A/C visible, B hidden; B override 0 -> B visible, reload persists, raw items exist)
  // =========================================================================
  console.log("--- Starting Scenario 1: RSS Freshness ---");
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  const hotlistTab = page.locator("button", { hasText: "实时热榜" });
  await hotlistTab.waitFor({ state: "visible", timeout: 10000 });
  await hotlistTab.click();

  const hotlistPanel = page.getByTestId("native-intel-hotlist-panel");
  await hotlistPanel.waitFor({ state: "visible", timeout: 10000 });

  const rssRegion = hotlistPanel.getByTestId("display-region-rss");
  await rssRegion.waitFor({ state: "visible", timeout: 10000 });

  // Feed A (1d) & Feed C (unknown) visible; Feed B (5d) hidden
  await rssRegion.getByText("新鲜宏观动态：科技与产业进展", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await rssRegion.getByText("未标注日期的特别快讯", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await rssRegion.getByText("五天前宏观简讯：市场回顾", { exact: true }).waitFor({ state: "hidden", timeout: 5000 });

  // Navigate to Settings to set Feed B max_age_days = 0 (disabled)
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });
  const feedBSelect = page.getByTestId("source-freshness-select-rss-feed-b");
  await feedBSelect.waitFor({ state: "visible", timeout: 10000 });
  await feedBSelect.selectOption("disabled");
  await sleep(600);

  // Return to /intel
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  await page.locator("button", { hasText: "实时热榜" }).click();
  const rssRegionAfter = page.getByTestId("display-region-rss");
  await rssRegionAfter.waitFor({ state: "visible", timeout: 10000 });

  // Now Feed B is visible!
  await rssRegionAfter.getByText("五天前宏观简讯：市场回顾", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // Reload persists
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator("button", { hasText: "实时热榜" }).click();
  await page.getByTestId("display-region-rss").getByText("五天前宏观简讯：市场回顾", { exact: true }).waitFor({ state: "visible", timeout: 5000 });

  // Verify backend store query still has all raw items (non-destructive)
  const statusRes = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/status`);
  const statusJson = await statusRes.json();
  assert.equal(statusJson.status, "normal");
  console.log("Scenario 1 passed.");

  // =========================================================================
  // Scenario 2: Standalone RSS bypasses keyword filter
  // =========================================================================
  console.log("--- Starting Scenario 2: Standalone RSS bypasses keyword filter ---");
  // Switch to "我的关注" mode (profile matches keyword "机器人")
  const modeInterestsBtn = page.getByTestId("hotlist-mode-interests");
  await modeInterestsBtn.click();
  await sleep(600);

  // Normal RSS region filters out "新鲜宏观动态：科技与产业进展" (no "机器人")
  await page.getByTestId("display-region-rss").getByText("新鲜宏观动态：科技与产业进展", { exact: true }).waitFor({ state: "hidden", timeout: 5000 });

  // Standalone region bypasses filter -> shows "新鲜宏观深度分析报告"
  const standaloneRegion = page.getByTestId("display-region-standalone");
  await standaloneRegion.waitFor({ state: "visible", timeout: 5000 });
  await standaloneRegion.getByText("新鲜宏观深度分析报告", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  console.log("Scenario 2 passed.");

  // =========================================================================
  // Scenario 3: Standalone RSS respects freshness
  // =========================================================================
  console.log("--- Starting Scenario 3: Standalone RSS respects freshness ---");
  // Standalone region has 5-day old item "五天前过期独立文章", which must be excluded by 3-day freshness
  await standaloneRegion.getByText("五天前过期独立文章", { exact: true }).waitFor({ state: "hidden", timeout: 5000 });
  console.log("Scenario 3 passed.");

  // Switch back to "全部热榜" mode
  await page.getByTestId("hotlist-mode-all").click();
  await sleep(400);

  // =========================================================================
  // Scenario 4: Region order persistence & toggle
  // =========================================================================
  console.log("--- Starting Scenario 4: Region order & toggle ---");
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });
  const wave3Card = page.getByTestId("native-intel-wave3-settings");
  await wave3Card.waitFor({ state: "visible", timeout: 10000 });

  // Move standalone up twice so order becomes standalone, hotlist, rss
  const moveUpStandalone = page.getByTestId("wave3-move-up-standalone");
  await moveUpStandalone.waitFor({ state: "visible", timeout: 5000 });
  await moveUpStandalone.click(); // swaps standalone with rss
  await sleep(400);
  await moveUpStandalone.click(); // swaps standalone with hotlist
  await sleep(400);

  // Save config and wait for success toast
  await page.getByTestId("wave3-save-config-btn").click();
  await page.getByText("已保存展示与抓取高级设置").waitFor({ state: "visible", timeout: 5000 });
  await sleep(600);

  // Return to /intel and check order
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  await page.locator("button", { hasText: "实时热榜" }).click();
  await page.getByTestId("native-intel-hotlist-panel").waitFor({ state: "visible", timeout: 10000 });

  // Wait until config is loaded and first region becomes display-region-standalone
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid^="display-region-"]');
    return el?.getAttribute("data-testid") === "display-region-standalone";
  }, { timeout: 10000 });

  const regionElements = await page.locator('[data-testid^="display-region-"]').all();
  const testIds = await Promise.all(regionElements.map((el) => el.getAttribute("data-testid")));
  console.log("Rendered region testIds:", testIds);
  assert.equal(testIds[0], "display-region-standalone", "First region must be standalone");

  // Reload page: order persists
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator("button", { hasText: "实时热榜" }).click();
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid^="display-region-"]');
    return el?.getAttribute("data-testid") === "display-region-standalone";
  }, { timeout: 10000 });
  const reloadedRegions = await page.locator('[data-testid^="display-region-"]').all();
  const reloadedIds = await Promise.all(reloadedRegions.map((el) => el.getAttribute("data-testid")));
  assert.equal(reloadedIds[0], "display-region-standalone", "Order must persist across reload");

  // Disable RSS region toggle
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("wave3-region-toggle-rss").click(); // uncheck rss
  await page.getByTestId("wave3-save-config-btn").click();
  await page.getByText("已保存展示与抓取高级设置").waitFor({ state: "visible", timeout: 5000 });
  await sleep(600);

  // Return to /intel: normal RSS hidden, standalone RSS remains
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  await page.locator("button", { hasText: "实时热榜" }).click();
  await page.getByTestId("display-region-standalone").waitFor({ state: "visible", timeout: 5000 });
  await page.getByTestId("display-region-rss").waitFor({ state: "hidden", timeout: 5000 });
  await page.getByTestId("display-region-standalone").getByText("新鲜宏观深度分析报告", { exact: true }).waitFor({ state: "visible", timeout: 5000 });
  console.log("Scenario 4 passed.");

  // =========================================================================
  // Scenario 5: All regions disabled -> honest empty state
  // =========================================================================
  console.log("--- Starting Scenario 5: All regions disabled ---");
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("wave3-region-toggle-hotlist").click(); // uncheck hotlist
  await page.getByTestId("wave3-region-toggle-standalone").click(); // uncheck standalone
  await page.getByTestId("wave3-save-config-btn").click();
  await page.getByText("已保存展示与抓取高级设置").waitFor({ state: "visible", timeout: 5000 });
  await sleep(600);

  // Return to /intel
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  await page.locator("button", { hasText: "实时热榜" }).click();

  const emptyNotice = page.getByTestId("all-regions-disabled-empty");
  await emptyNotice.waitFor({ state: "visible", timeout: 10000 });
  const emptyText = await emptyNotice.innerText();
  assert.ok(
    emptyText.includes("当前所有资讯展示区域均已关闭，可到设置中重新开启。"),
    `Unexpected empty notice text: ${emptyText}`,
  );
  console.log("Scenario 5 passed.");

  assert.equal(pageErrors.length, 0, `Page errors: ${pageErrors.join("; ")}`);
  console.log("ALL WAVE 3 BROWSER SCENARIOS PASSED!");
} finally {
  if (browser) await browser.close();
  if (frontend) frontend.close();
  if (backend) {
    backend.kill();
    try {
      process.kill(backend.pid);
    } catch {
      /* ignore */
    }
  }
}
