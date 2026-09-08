/**
 * PLANNING-PARITY-SIGVAL1 source-to-sink browser vertical.
 *
 * The RDP CSV is imported into an isolated temporary directory. The browser
 * talks to the built frontend through a real proxy and reaches the production
 * historical-signal-validation router and calculation module. No core API
 * response is mocked.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer, request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = path.join(root, "backend");
const frontendDist = path.join(root, "frontend", "dist");
const screenshotDir = process.env.E2E_SCREENSHOT_DIR || path.join(tmpdir(), "vr-sigval-e2e-evidence");

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function resolvePython() {
  if (process.env.VR_E2E_PYTHON?.trim()) return { command: process.env.VR_E2E_PYTHON.trim(), prefix: [] };
  const venv = process.platform === "win32" ? path.join(backendDir, ".venv", "Scripts", "python.exe") : path.join(backendDir, ".venv", "bin", "python");
  if (existsSync(venv)) return { command: venv, prefix: [] };
  return process.platform === "win32" ? { command: "py", prefix: ["-3"] } : { command: "python3", prefix: [] };
}
function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}
async function waitHttp(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch { /* process is still starting */ }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}
async function runProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.once("error", reject);
    child.once("exit", (code) => code === 0 ? resolve({ stdout, stderr }) : reject(new Error(`${command} exited ${code}: ${stderr || stdout}`)));
  });
}
async function seedRdp() {
  const tempDir = await mkdtemp(path.join(tmpdir(), "vr-sigval-"));
  const csv = path.join(tempDir, "daily.csv");
  const rdpRoot = path.join(tempDir, "research_data_plane");
  const lines = ["code,trade_date,open,high,low,close,volume"];
  const start = Date.UTC(2024, 0, 1);
  const sample = Array.from({ length: 130 }, () => 100);
  sample[80] = 101;
  for (let i = 81; i < 85; i += 1) sample[i] = 101;
  sample[85] = 105;
  for (let i = 86; i < 100; i += 1) sample[i] = 101;
  sample[100] = 110;
  for (let i = 101; i < sample.length; i += 1) sample[i] = 110;
  for (let i = 0; i < sample.length; i += 1) {
    const day = new Date(start + i * 86400000).toISOString().slice(0, 10);
    lines.push(`600001,${day},${sample[i]},${sample[i]},${sample[i]},${sample[i]},1000`);
    lines.push(`600002,${day},200,200,200,200,1000`);
    if (i !== 85) lines.push(`600003,${day},200,200,200,200,1000`);
  }
  await writeFile(csv, `${lines.join("\n")}\n`, "utf8");
  const python = resolvePython();
  await runProcess(python.command, [...python.prefix, "-m", "research_data_plane", "import-csv", csv, "--root", rdpRoot], {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: backendDir },
  });
  return { tempDir, rdpRoot };
}
function startStaticServer(dir, port, backendPort) {
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png" };
  const server = createServer((req, res) => {
    if ((req.url || "").startsWith("/api/")) {
      const proxy = httpRequest({ hostname: "127.0.0.1", port: backendPort, path: req.url, method: req.method, headers: { ...req.headers, host: `127.0.0.1:${backendPort}` } }, (upstream) => {
        res.writeHead(upstream.statusCode || 502, upstream.headers);
        upstream.pipe(res);
      });
      proxy.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end("proxy failed"); });
      req.pipe(proxy);
      return;
    }
    let pathname = (req.url || "/").split("?")[0];
    if (pathname === "/" || !path.extname(pathname)) pathname = "/index.html";
    const target = path.join(dir, pathname);
    const safeTarget = path.resolve(target);
    if (!safeTarget.startsWith(path.resolve(dir) + path.sep) || !existsSync(target)) {
      res.writeHead(404); res.end(); return;
    }
    res.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => { server.once("error", reject); server.listen(port, "127.0.0.1", () => resolve(server)); });
}
function chromiumPath() {
  const installed = [
    process.env.CHROME_PATH,
    process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Google", "Chrome", "Application", "chrome.exe") : undefined,
    process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Google", "Chrome", "Application", "chrome.exe") : undefined,
  ].filter(Boolean);
  const known = installed.find((candidate) => existsSync(candidate));
  if (known) return known;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH === "0" ? path.join(root, "frontend", "node_modules", "playwright-core") : path.join(process.env.LOCALAPPDATA || "", "ms-playwright");
  if (!existsSync(base)) return undefined;
  const entries = readdirSync(base);
  for (const entry of entries) {
    if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
    const candidate = path.join(base, entry, "chrome-win", "chrome.exe");
    if (existsSync(candidate)) return candidate;
  }
  return undefined;
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built first");
  const { tempDir, rdpRoot } = await seedRdp();
  await mkdir(screenshotDir, { recursive: true });
  const beforeFiles = (await readFile(path.join(rdpRoot, "manifest.json"), "utf8"));
  const backendPort = await freePort();
  const frontendPort = await freePort();
  const python = resolvePython();
  const env = {
    ...process.env,
    PYTHONPATH: backendDir,
    VR_DATA_DIR: tempDir,
    VR_REPORTS_DIR: tempDir,
    VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: "1",
    VIBE_NATIVE_INTEL_DISABLE_SCHEDULER: "1",
    VIBE_RESEARCH_RESEARCH_DATA_DIR: rdpRoot,
    VR_ALLOW_ORIGINS: `http://127.0.0.1:${frontendPort}`,
    PYTHONUNBUFFERED: "1",
  };
  const backend = spawn(python.command, [...python.prefix, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"] });
  let staticServer;
  let browser;
  try {
    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    const direct = await (await fetch(`http://127.0.0.1:${backendPort}/api/signals/validation/evaluate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ signal_id: "sma20_gt_sma60", codes: ["600001"], benchmark_code: "600002" }) })).json();
    assert.equal(direct.status, "normal");
    assert.equal(direct.data.dataset_id, "ashare_daily_unadjusted");
    assert.equal(direct.results["5"].events_evaluated, 1);
    assert.equal(direct.results["5"].rows[0].benchmark_return_pct, 0);
    assert.equal(await readFile(path.join(rdpRoot, "manifest.json"), "utf8"), beforeFiles, "evaluation does not rewrite RDP manifest");

    staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (message) => { if (["error", "warning"].includes(message.type())) consoleErrors.push(message.text()); });
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const url = `http://127.0.0.1:${frontendPort}/signals/validation?signal=sma20_gt_sma60&codes=600001&benchmark=600002`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    assert.equal(new URL(page.url()).pathname, "/signals/validation");
    assert.ok((await page.title()).length > 0);
    try {
      await page.getByText("Event Ledger", { exact: false }).waitFor({ timeout: 30000 });
    } catch (error) {
      console.error("[E2E] initial body:\n" + (await page.locator("body").innerText()));
      await page.screenshot({ path: path.join(screenshotDir, "historical-signal-validation-failure.png"), fullPage: false });
      throw error;
    }
    await page.getByText("ashare_daily_unadjusted", { exact: true }).waitFor();
    await page.getByText("已评估", { exact: true }).first().waitFor();
    assert.ok((await page.locator("body").innerText()).includes("Historical validity not proven"));
    assert.ok(!(await page.locator("body").innerText()).includes("Application error"));
    await page.screenshot({ path: path.join(screenshotDir, "historical-signal-validation-desktop.png"), fullPage: false });
    await page.getByText("Event Ledger", { exact: false }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(screenshotDir, "historical-signal-validation-ledger.png"), fullPage: false });

    // Distinct empty, immature, partial-benchmark, and missing-sample states.
    const runUi = async ({ sampleCodes, benchmark = "", endDate = "" }) => {
      await page.getByLabel("显式样本代码").fill(sampleCodes);
      await page.getByLabel("benchmark code").fill(benchmark);
      await page.locator('input[type="date"]').nth(1).fill(endDate);
      await page.getByRole("button", { name: "运行验证" }).click();
      const expectedCodes = sampleCodes.split(/\s+/).filter(Boolean).join(",");
      await page.waitForURL((url) => url.searchParams.get("codes") === expectedCodes
        && (benchmark ? url.searchParams.get("benchmark") === benchmark : !url.searchParams.has("benchmark"))
        && (endDate ? url.searchParams.get("to") === endDate : !url.searchParams.has("to")), { timeout: 30000 });
      await page.getByText("Event Ledger", { exact: false }).waitFor({ timeout: 30000 });
    };
    await runUi({ sampleCodes: "600002" });
    await page.getByText("当前范围没有信号事件", { exact: false }).waitFor();
    await runUi({ sampleCodes: "600001", endDate: "2024-03-23" });
    await page.getByText("窗口未成熟", { exact: true }).first().waitFor();
    await runUi({ sampleCodes: "600001", benchmark: "600003" });
    await page.getByText("基准缺失：1", { exact: true }).waitFor();
    await runUi({ sampleCodes: "600001\n600004" });
    await page.getByText("600004", { exact: true }).first().waitFor();

    await runUi({ sampleCodes: "600001", benchmark: "600002" });
    await page.getByRole("button", { name: "GPU租金" }).click();
    await page.waitForURL(/\/signals\/gpu-rent/);
    await page.goBack();
    await page.waitForURL(/\/signals\/validation/);
    assert.equal(await page.getByLabel("显式样本代码").inputValue(), "600001");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("Event Ledger", { exact: false }).waitFor({ timeout: 30000 });
    assert.equal(await page.getByLabel("显式样本代码").inputValue(), "600001");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(screenshotDir, "historical-signal-validation-mobile.png"), fullPage: false });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2);
    assert.equal(overflow, true, "narrow viewport has no page-level horizontal overflow");
    assert.deepEqual(consoleErrors, [], `console warnings/errors: ${consoleErrors.join(" | ")}`);
    assert.deepEqual(pageErrors, [], `page errors: ${pageErrors.join(" | ")}`);
    console.log(`[E2E] Historical Signal Validation passed; screenshots=${screenshotDir}`);
  } finally {
    try { if (browser) await browser.close(); } catch { /* ignore */ }
    try { if (staticServer) staticServer.close(); } catch { /* ignore */ }
    backend.kill();
    await sleep(300);
    try { backend.kill("kill"); } catch { /* already gone */ }
    await rm(tempDir, { recursive: true, force: true });
  }
}

run().catch((error) => { console.error(error); process.exit(1); });
