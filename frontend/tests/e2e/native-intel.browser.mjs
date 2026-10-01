/** One built-frontend Native Intel vertical: partial source health, trend, and real item. */
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
const tempDir = mkdtempSync(join(tmpdir(), "vr-native-intel-"));

const freePort = () => new Promise((resolve, reject) => {
  const server = createServer();
  server.on("error", reject);
  server.listen(0, "127.0.0.1", () => { const port = server.address().port; server.close(() => resolve(port)); });
});
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
const pythonArgs = process.env.PYTHON ? ["-m", "uvicorn"] : (process.platform === "win32" ? ["-3", "-m", "uvicorn"] : ["-m", "uvicorn"]);

function chromiumPath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH && existsSync(process.env.PLAYWRIGHT_CHROMIUM_PATH)) return process.env.PLAYWRIGHT_CHROMIUM_PATH;
  for (const base of [join(process.env.LOCALAPPDATA || "", "ms-playwright"), join(process.env.HOME || "", ".cache", "ms-playwright")]) {
    if (!existsSync(base)) continue;
    for (const entry of readdirSync(base)) for (const candidate of [join(base, entry, "chrome-win64", "chrome.exe"), join(base, entry, "chrome-linux", "chrome")]) if (existsSync(candidate)) return candidate;
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
    try { if ((await fetch(url)).ok) return; } catch { /* starting */ }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function staticServer(directory, port) {
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" };
  const server = createServer((request, response) => {
    let target = join(directory, (request.url || "/").split("?")[0] === "/" ? "index.html" : (request.url || "/").split("?")[0]);
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
  assert.ok(existsSync(join(frontendDist, "index.html")), "frontend must be built first");
  const backendPort = await freePort();
  const frontendPort = await freePort();
  backend = spawn(python, [...pythonArgs, "--app-dir", join(root, "frontend", "tests", "e2e"), "native_intel_harness_app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: `${backendDir}${path.delimiter}${join(root, "frontend", "tests", "e2e")}`, VIBE_NATIVE_INTEL_DB: join(tempDir, "native-intel.sqlite3"), PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  await waitHttp(`http://127.0.0.1:${backendPort}/api/native-intel/status`);
  frontend = await staticServer(frontendDist, frontendPort);
  browser = await launchBrowser();
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const response = await fetch(`http://127.0.0.1:${backendPort}${url.pathname}${url.search}`, { method: route.request().method() });
    await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers.entries()), body: Buffer.from(await response.arrayBuffer()) });
  });
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  const panel = page.getByTestId("market-intel-panel");
  await panel.waitFor({ state: "visible", timeout: 20000 });
  await panel.getByText("PARTIAL · 部分可用", { exact: true }).waitFor();
  await panel.getByText("历史资讯 1", { exact: false }).waitFor();
  await panel.getByText("失败来源：失败测试源", { exact: false }).waitFor();
  await panel.getByText("固态电池产业化进展加速", { exact: true }).waitFor();
  await panel.locator('[aria-label="近 24 小时关注趋势"]').getByText(/固态电池.*1 条/).waitFor();
  // Public feeds: real rendered controls, deterministic provider/watchlist results.
  // Override only the public feed routes; the Native Intel vertical above retains
  // its real isolated backend. No public provider or user data is accessed.
  const unsafeDetail = "ProxyError https://provider.invalid/?token=secret SQL traceback";
  let watchMode = "error";
  let feedMode = "empty";
  let releaseFilings;
  let signalFilings;
  let pendingFilings;
  const json = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(status === 200 ? { data } : { detail: data }) });
  await page.route("**/api/watchlist", async (route) => {
    if (watchMode === "error") return json(route, unsafeDetail, 502);
    return json(route, {
      status: watchMode === "corrupted" ? "corrupted" : "valid",
      data: watchMode === "corrupted" ? null : { codes: watchMode === "empty" ? [] : ["000001", "000002"], updated_at: "2026-09-30T10:00:00Z" },
      etag: watchMode === "corrupted" ? null : "synthetic-watchlist",
    });
  });
  await page.route("**/api/quote?**", (route) => json(route, {}));
  for (const endpoint of ["announcements", "news"]) {
    await page.route(`**/api/${endpoint}?**`, async (route) => {
      const code = new URL(route.request().url()).searchParams.get("code");
      if (endpoint === "announcements" && feedMode === "delayed") {
        signalFilings();
        await pendingFilings;
        return json(route, [{ title: "Old announcement must not render", date: "2026-09-30", type: "公告", url: "" }]);
      }
      if (feedMode === "failure" || (feedMode === "partial" && code === "000002")) return json(route, unsafeDetail, 502);
      if (feedMode === "dependency") return json(route, unsafeDetail, 501);
      if (feedMode === "malformed") return json(route, { unexpected: [] });
      if (feedMode === "empty") return json(route, []);
      return json(route, endpoint === "announcements"
        ? [{ title: "Synthetic retained announcement", date: "2026-09-30", type: "公告", url: "" }]
        : [{ 新闻标题: "Synthetic retained news", 发布时间: "2026-09-30 10:00" }]);
    });
  }
  const assertNoFalseEmpty = async () => {
    assert.equal(await page.getByText(/关注列表里的个股近期暂无|还没有关注股票/).count(), 0);
    assert.doesNotMatch(await page.locator("body").innerText(), /ProxyError|provider\.invalid|SQL|traceback/);
  };
  await page.getByRole("button", { name: "公开新闻", exact: true }).click();
  await page.getByRole("alert").getByText("关注列表加载失败，请重试。", { exact: true }).waitFor();
  await assertNoFalseEmpty();
  watchMode = "valid";
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await page.getByText("关注列表里的个股近期暂无新闻。", { exact: true }).waitFor();

  for (const [tab, label, title] of [["公开新闻", "新闻", "Synthetic retained news"], ["A股公告", "公告", "Synthetic retained announcement"]]) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await page.getByText(`关注列表里的个股近期暂无${label}。`, { exact: true }).waitFor();
    feedMode = "partial";
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page.getByRole("alert").getByText(`部分${label}加载失败（1/2 只）`, { exact: false }).waitFor();
    await page.getByText(title, { exact: true }).waitFor();
    await assertNoFalseEmpty();

    for (const failure of ["failure", "malformed"]) {
      feedMode = failure;
      await page.getByRole("button", { name: "重试", exact: true }).click();
      await page.getByRole("alert").getByText(`${label}加载失败（2/2 只）`, { exact: false }).waitFor();
      assert.equal(await page.getByText(title, { exact: true }).count(), 0);
      await assertNoFalseEmpty();
    }
    feedMode = "empty";
    await page.getByRole("button", { name: "重试", exact: true }).click();
    await page.getByText(`关注列表里的个股近期暂无${label}。`, { exact: true }).waitFor();
  }

  // A delayed old tab cannot overwrite the newly selected feed.
  const filingsStarted = new Promise((resolve) => { signalFilings = resolve; });
  pendingFilings = new Promise((resolve) => { releaseFilings = resolve; });
  feedMode = "delayed";
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await filingsStarted;
  feedMode = "success";
  await page.getByRole("button", { name: "公开新闻", exact: true }).click();
  await page.getByText("Synthetic retained news", { exact: true }).first().waitFor();
  const oldRequestFinished = page.waitForResponse((response) => response.url().includes("/api/announcements?"));
  releaseFilings();
  await oldRequestFinished;
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await page.getByText("Old announcement must not render", { exact: true }).count(), 0);
  assert.equal(await page.getByText("Synthetic retained news", { exact: true }).count(), 2);

  feedMode = "dependency";
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await page.getByRole("alert").getByText("新闻服务缺少 akshare 依赖", { exact: false }).waitFor();
  await assertNoFalseEmpty();
  watchMode = "corrupted";
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await page.getByRole("alert").getByText("关注列表无法读取", { exact: false }).waitFor();
  await assertNoFalseEmpty();
  watchMode = "empty";
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await page.getByText("还没有关注股票。到", { exact: false }).waitFor();
  assert.deepEqual(pageErrors, []);
  console.log("Native Intel rendered vertical and public feed failure/retry contracts: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (frontend) await new Promise((resolve) => frontend.close(resolve));
  if (backend) {
    backend.kill();
    await sleep(500);
  }
  try { rmSync(tempDir, { recursive: true, force: true }); } catch { /* Windows may release SQLite shortly after process exit */ }
}
