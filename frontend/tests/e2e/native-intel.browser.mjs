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
  await page.getByRole("button", { name: /关注雷达/ }).click();
  const panel = page.getByTestId("native-intel-panel");
  await panel.waitFor({ state: "visible", timeout: 20000 });
  await panel.getByText("部分来源不可用", { exact: true }).waitFor();
  await panel.getByText("历史条目 1", { exact: false }).waitFor();
  await panel.getByText("失败来源：失败测试源", { exact: false }).waitFor();
  await panel.getByText("固态电池产业化进展加速", { exact: true }).waitFor();
  await panel.getByText("固态电池 · 1 条", { exact: false }).waitFor();
  assert.deepEqual(pageErrors, []);
  console.log("Native Intel rendered vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (frontend) await new Promise((resolve) => frontend.close(resolve));
  if (backend) {
    backend.kill();
    await sleep(500);
  }
  try { rmSync(tempDir, { recursive: true, force: true }); } catch { /* Windows may release SQLite shortly after process exit */ }
}
