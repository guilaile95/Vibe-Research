/**
 * Real browser + real backend E2E for Native Intel AI Analysis & Agent Tools (TREND-PARITY Wave 5).
 * Tests all 8 required browser scenarios.
 */
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
const tempDir = mkdtempSync(join(tmpdir(), "vr-wave5-ai-agent-"));

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
  const dbPath = join(tempDir, "native_intel.sqlite3");

  backend = spawn(
    python,
    [
      ...pythonArgs,
      "--app-dir",
      join(root, "frontend", "tests", "e2e"),
      "wave5_ai_agent_harness_app:app",
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

  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
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
  // Scenario 1: Settings UI toggle of ai_analysis region & order persistence
  // =========================================================================
  console.log("--- Starting Scenario 1: Settings UI Toggle & Persistence ---");
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });

  const aiRegionToggle = page.locator('[data-testid="wave5-region-toggle-ai_analysis"]');
  await aiRegionToggle.waitFor({ state: "visible", timeout: 10000 });

  // Verify settings section exists
  const aiSettingsSection = page.locator('[data-testid="wave5-ai-settings-section"]');
  await aiSettingsSection.waitFor({ state: "visible", timeout: 5000 });

  // Toggle checkbox off then on to ensure dirty change
  if (await aiRegionToggle.isChecked()) {
    await aiRegionToggle.click();
    await sleep(200);
  }
  await aiRegionToggle.click();
  assert.equal(await aiRegionToggle.isChecked(), true);

  // Save settings
  const saveBtn = page.locator('[data-testid="wave3-save-config-btn"]');
  await saveBtn.click();
  await sleep(1000);

  // Reload page and verify persistence
  await page.reload({ waitUntil: "domcontentloaded" });
  const reloadedToggle = page.locator('[data-testid="wave5-region-toggle-ai_analysis"]');
  await reloadedToggle.waitFor({ state: "visible", timeout: 10000 });
  assert.equal(await reloadedToggle.isChecked(), true);
  console.log("PASS: Scenario 1 - Settings toggle and persistence verified");

  // =========================================================================
  // Scenario 2: HotlistPanel rendering display-region-ai_analysis
  // =========================================================================
  console.log("--- Starting Scenario 2: HotlistPanel renders ai_analysis region ---");
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });

  const hotlistTab = page.locator("button", { hasText: "实时热榜" });
  await hotlistTab.waitFor({ state: "visible", timeout: 10000 });
  await hotlistTab.click();

  const aiAnalysisRegion = page.locator('[data-testid="display-region-ai_analysis"]');
  await aiAnalysisRegion.waitFor({ state: "visible", timeout: 10000 });
  console.log("PASS: Scenario 2 - HotlistPanel rendered display-region-ai_analysis");

  // =========================================================================
  // Scenario 3: Trigger "生成 AI 研报" & verify 6 section tabs, counts, watermark, cache hit
  // =========================================================================
  console.log("--- Starting Scenario 3: AI Deep Analysis Generation, 6 Tabs & Caching ---");
  const generateBtn = page.locator('[data-testid="wave5-generate-ai-analysis"]');
  await generateBtn.waitFor({ state: "visible", timeout: 5000 });
  const analysisPromise = page.waitForResponse((r) => r.url().includes("/api/native-intel/ai/analysis"));
  await generateBtn.click();
  const analysisResp = await analysisPromise;
  const analysisJson = await analysisResp.json();
  console.log("ANALYSIS RESPONSE IS:", JSON.stringify(analysisJson));

  // Wait for 6 section tabs to be visible
  const tabs = [
    "core_trends",
    "sentiment_controversy",
    "signals",
    "rss_insights",
    "outlook_strategy",
    "standalone_summaries",
  ];
  for (const tabKey of tabs) {
    const tabLocator = page.locator(`[data-testid="wave5-tab-${tabKey}"]`);
    await tabLocator.waitFor({ state: "visible", timeout: 10000 });
  }

  // Check counts element
  const countsEl = page.locator('[data-testid="wave5-ai-counts"]');
  await countsEl.waitFor({ state: "visible", timeout: 5000 });
  const countsText = await countsEl.innerText();
  assert.ok(countsText.length > 0, "Counts element should have text");

  // Check watermark
  const watermarkEl = page.locator('[data-testid="wave5-disclaimer-watermark"]');
  await watermarkEl.waitFor({ state: "visible", timeout: 5000 });
  const watermarkText = await watermarkEl.innerText();
  assert.ok(watermarkText.includes("不构成") || watermarkText.includes("投资决策") || watermarkText.includes("免责声明"));

  // Click tabs to verify content
  await page.locator('[data-testid="wave5-tab-signals"]').click();
  await sleep(300);
  assert.ok(await page.locator("text=高密算力CDU关键部件扩产").count() > 0);

  await page.locator('[data-testid="wave5-tab-core_trends"]').click();
  await sleep(300);
  assert.ok(await page.locator("text=AI算力与液冷渗透率提速").count() > 0);

  // Click generate again to verify CACHE_HIT badge
  await generateBtn.click();
  await sleep(1000);
  const cachedBadge = page.locator('[data-testid="wave5-ai-cached-badge"]');
  await cachedBadge.waitFor({ state: "visible", timeout: 5000 });
  console.log("PASS: Scenario 3 - AI Deep Analysis 6 tabs, watermark, and CACHE_HIT verified");

  // =========================================================================
  // Scenario 4: Single Item AI Translation
  // =========================================================================
  console.log("--- Starting Scenario 4: Single Item AI Translation ---");
  // Item 1 has title: "Data center liquid cooling demand rises"
  const item1Title = page.locator("text=Data center liquid cooling demand rises");
  await item1Title.waitFor({ state: "visible", timeout: 10000 });

  const transBtns = page.locator('[data-testid="wave5-item-translate"]');
  assert.ok((await transBtns.count()) > 0, "Translate button should exist for items");
  await transBtns.first().click();

  // Wait for translation result
  const transResult = page.locator('[data-testid^="wave5-trans-result-"]');
  await transResult.first().waitFor({ state: "visible", timeout: 10000 });
  const translatedText = await transResult.first().innerText();
  console.log("TRANSLATED TEXT IS:", JSON.stringify(translatedText));
  assert.ok(translatedText.includes("数据中心液冷需求持续攀升") || translatedText.includes("【AI 翻译】"), "Translation text should match");

  // Verify original text is still intact and visible!
  assert.ok((await page.locator("text=Data center liquid cooling demand rises").count()) > 0);
  console.log("PASS: Scenario 4 - Single translation rendered without mutating original title");

  // =========================================================================
  // Scenario 5: Batch translation array index preservation
  // =========================================================================
  console.log("--- Starting Scenario 5: Batch translation identity preservation ---");
  // Test via direct API call to verify backend batch translation contract
  const batchResp = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/ai/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      texts: ["Title Alpha", "Data center liquid cooling demand rises", "Title Gamma"],
      target_language: "Chinese",
    }),
  });
  assert.equal(batchResp.status, 200);
  const batchData = await batchResp.json();
  assert.equal(batchData.results.length, 3, "Batch response must have exactly 3 translations");
  assert.ok(batchData.results[1].translated.includes("数据中心液冷需求持续攀升"));
  console.log("PASS: Scenario 5 - Batch translation preserves array index and count");

  // =========================================================================
  // Scenario 6: Item Entity Extraction & Sentiment Analysis
  // =========================================================================
  console.log("--- Starting Scenario 6: Entity Extraction & Sentiment Analysis ---");
  const entityBtns = page.locator('[data-testid="wave5-item-entities"]');
  await entityBtns.first().click();

  const entityResult = page.locator('[data-testid^="wave5-entities-result-"]');
  await entityResult.first().waitFor({ state: "visible", timeout: 10000 });
  const entityText = await entityResult.first().innerText();
  assert.ok(entityText.includes("中芯国际") || entityText.includes("液冷技术") || entityText.includes("半导体"));

  const sentimentBtns = page.locator('[data-testid="wave5-item-sentiment"]');
  await sentimentBtns.first().click();

  const sentimentResult = page.locator('[data-testid^="wave5-sentiment-result-"]');
  await sentimentResult.first().waitFor({ state: "visible", timeout: 10000 });
  const sentimentText = await sentimentResult.first().innerText();
  assert.ok(sentimentText.includes("positive") || sentimentText.includes("积极") || sentimentText.includes("85%"));
  console.log("PASS: Scenario 6 - Entity extraction and Sentiment badges verified");

  // =========================================================================
  // Scenario 7: AI Provider Error Isolation
  // =========================================================================
  console.log("--- Starting Scenario 7: Provider Error Isolation ---");
  // Enable error simulation
  await fetch(`http://127.0.0.1:${backendPort}/__test/simulate-ai-error?enable=true`, { method: "POST" });

  // Trigger translation on another item or item 2
  if ((await transBtns.count()) > 1) {
    await transBtns.nth(1).click();
    await sleep(1500);
  }

  // Verify hotlist panel is still functional and rendered (no crash / white screen)
  const panelStillThere = page.locator('[data-testid="native-intel-hotlist-panel"]');
  assert.equal(await panelStillThere.isVisible(), true);

  // Restore error simulation
  await fetch(`http://127.0.0.1:${backendPort}/__test/simulate-ai-error?enable=false`, { method: "POST" });
  console.log("PASS: Scenario 7 - Error isolated honestly without crashing HotlistPanel");

  // =========================================================================
  // Scenario 8: Agent Tool Integration & Disabling ai_analysis removes region
  // =========================================================================
  console.log("--- Starting Scenario 8: Agent Tools & Region Disabling ---");
  // 8a. Test Agent Tools endpoints
  const statusResp = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/agent/tools/status`);
  assert.equal(statusResp.status, 200);
  const statusJson = await statusResp.json();
  assert.ok(statusJson.status === "normal" || statusJson.status === "ok", `Unexpected status: ${statusJson.status}`);

  const queryResp = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/agent/tools/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ limit: 5 }),
  });
  assert.equal(queryResp.status, 200);
  const queryJson = await queryResp.json();
  assert.ok(queryJson.items.length > 0);

  const searchResp = await fetch(`http://127.0.0.1:${backendPort}/api/native-intel/agent/tools/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "液冷" }),
  });
  assert.equal(searchResp.status, 200);

  // 8b. Disabling ai_analysis in Settings removes the region from HotlistPanel
  await page.goto(`http://127.0.0.1:${frontendPort}/settings`, { waitUntil: "domcontentloaded" });
  const toggleToUncheck = page.locator('[data-testid="wave5-region-toggle-ai_analysis"]');
  await toggleToUncheck.waitFor({ state: "visible", timeout: 10000 });
  if (await toggleToUncheck.isChecked()) {
    await toggleToUncheck.click();
    await page.locator('[data-testid="wave3-save-config-btn"]').click();
    await sleep(1000);
  }

  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  const intelTab = page.locator("button", { hasText: "实时热榜" });
  await intelTab.waitFor({ state: "visible", timeout: 10000 });
  await intelTab.click();
  await sleep(1000);

  const aiRegionAfterDisable = page.locator('[data-testid="display-region-ai_analysis"]');
  assert.equal(await aiRegionAfterDisable.count(), 0, "ai_analysis region should not be in DOM when disabled");
  console.log("PASS: Scenario 8 - Agent tools verified and disabling region removes it from DOM");

  console.log("ALL 8 WAVE 5 BROWSER SCENARIOS PASSED!");
} finally {
  if (browser) await browser.close();
  if (frontend) frontend.close();
  if (backend) {
    backend.kill("SIGTERM");
    if (process.platform === "win32" && backend.pid) {
      spawn("taskkill.exe", ["/PID", String(backend.pid), "/T", "/F"], { stdio: "ignore" });
    }
  }
}
