/**
 * PLANNING-PARITY-FACTOR-VALIDATION1 source-to-sink browser vertical.
 *
 * A deterministic 61-security RDP artifact is imported into an isolated
 * directory. The browser then reaches a real FastAPI route and the built
 * frontend. The factor calculation is not mocked.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
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
const screenshotDir = process.env.E2E_SCREENSHOT_DIR || path.join(tmpdir(), "vr-factor-validation-e2e-evidence");

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function resolvePython() {
  if (process.env.VR_E2E_PYTHON?.trim()) return { command: process.env.VR_E2E_PYTHON.trim(), prefix: [] };
  const venv = process.platform === "win32"
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python");
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

function priceFor(codeIndex, index) {
  const base = 100 + codeIndex * 0.2;
  const group = (codeIndex % 5) - 2;
  const signal = group * 0.01;
  const zeroIcTarget = [-0.02, 0.02, 0.01, 0, -0.01][group + 2];
  let close = base;
  if (index >= 60) close = base * (1 + signal);
  if (index >= 65) close = base * (1 + signal) * (1 + signal);
  if (index >= 70) close *= 1 + signal;
  if (index >= 75) close *= 1 - signal;
  if (index >= 80) close *= 1 + signal;
  if (index >= 85) close *= 1 + zeroIcTarget;
  return close;
}

async function seedRdp() {
  const tempDir = await mkdtemp(path.join(tmpdir(), "vr-factor-validation-"));
  const csv = path.join(tempDir, "factor.csv");
  const rdpRoot = path.join(tempDir, "research_data_plane");
  const lines = ["code,trade_date,open,high,low,close,volume"];
  const start = Date.UTC(2026, 0, 1);
  for (let index = 0; index < 90; index += 1) {
    const tradeDate = new Date(start + index * 86400000).toISOString().slice(0, 10);
    for (let codeIndex = 0; codeIndex < 61; codeIndex += 1) {
      // One observed security ends early: its factor can be visible but its
      // forward outcome is immature, proving the null/immature path.
      if (codeIndex === 60 && index > 63) continue;
      const close = priceFor(codeIndex, index);
      lines.push(`${String(600001 + codeIndex)},${tradeDate},${close},${close},${close},${close},${1000 + index}`);
    }
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
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((req, res) => {
    if ((req.url || "").startsWith("/api/")) {
      const proxy = httpRequest({
        hostname: "127.0.0.1",
        port: backendPort,
        path: req.url,
        method: req.method,
        headers: { ...req.headers, host: `127.0.0.1:${backendPort}` },
      }, (upstream) => {
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
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function chromiumPath() {
  const installed = [
    process.env.CHROME_PATH,
    process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Google", "Chrome", "Application", "chrome.exe") : undefined,
    process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Google", "Chrome", "Application", "chrome.exe") : undefined,
  ].filter(Boolean);
  const known = installed.find((candidate) => existsSync(candidate));
  if (known) return known;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH === "0"
    ? path.join(root, "frontend", "node_modules", "playwright-core")
    : path.join(process.env.LOCALAPPDATA || "", "ms-playwright");
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
    const directResponse = await fetch(`http://127.0.0.1:${backendPort}/api/signals/factor-validation/evaluate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ factor_id: "return_5d", forward_windows: [5, 20], date_from: "2026-01-01", date_to: "2026-03-31" }),
    });
    assert.equal(directResponse.status, 200);
    const direct = await directResponse.json();
    assert.equal(direct.status, "normal");
    assert.equal(direct.schema_version, "factor_validation.v0.1");
    assert.equal(direct.parity.status, "PROVEN");
    assert.equal(direct.parity.mode, "DIRECT_SOURCE_METRIC_REUSE");
    assert.equal(direct.parity.source_metric, "return_5d");
    assert.equal(direct.parity.mismatches, 0);
    assert.equal(direct.parity.security_factor_values_checked, 5490);
    const observations = direct.results["5"].observations;
    assert.ok(observations.some((item) => item.rank_ic > 0), "fixture has positive IC");
    assert.ok(observations.some((item) => item.rank_ic < 0), "fixture has negative IC");
    assert.equal(observations.find((item) => item.factor_date === "2026-03-22").rank_ic, 0);
    assert.equal(observations.find((item) => item.factor_date === "2026-01-06").rank_ic, null);
    assert.ok(observations.some((item) => item.high_minus_low_spread > 0), "fixture has positive spread");
    assert.ok(observations.some((item) => item.status === "IMMATURE_FORWARD_WINDOW"), "fixture has immature outcome");

    staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (message) => { if (["error", "warning"].includes(message.type())) consoleErrors.push(message.text()); });
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto(`http://127.0.0.1:${frontendPort}/signals`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "因子有效性", exact: true }).click();
    await page.waitForURL(/\/signals\/factor-validation/);
    await page.getByTestId("factor-validation").waitFor();
    await page.getByLabel("Factor", { exact: true }).selectOption("return_5d");
    await page.getByLabel("因子验证起始日期", { exact: true }).fill("2026-01-01");
    await page.getByLabel("因子验证结束日期", { exact: true }).fill("2026-03-31");
    await page.getByRole("button", { name: "运行因子验证", exact: true }).click();
    await page.getByTestId("factor-validation-results").waitFor({ timeout: 30000 });
    await page.getByText("Factor value parity · PROVEN", { exact: true }).waitFor();
    await page.getByText("Historical validity not proven", { exact: false }).first().waitFor();
    await page.getByText("2026-03-22", { exact: true }).waitFor();
    const desktopBody = await page.locator("body").innerText();
    assert.match(desktopBody, /RDP_OBSERVED_CROSS_SECTION/);
    assert.match(desktopBody, /UNADJUSTED/);
    assert.match(desktopBody, /0\.0000/);
    assert.match(desktopBody, /—/);
    await page.screenshot({ path: path.join(screenshotDir, "factor-validation-desktop.png"), fullPage: false });

    await page.getByRole("button", { name: "20 条已存储观测", exact: true }).click();
    await page.getByText("20 条已存储观测", { exact: true }).last().waitFor();
    await page.screenshot({ path: path.join(screenshotDir, "factor-validation-forward-20.png"), fullPage: false });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(screenshotDir, "factor-validation-mobile.png"), fullPage: false });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2);
    assert.equal(overflow, true, "narrow viewport has no page-level horizontal overflow");
    assert.deepEqual(consoleErrors, [], `console warnings/errors: ${consoleErrors.join(" | ")}`);
    assert.deepEqual(pageErrors, [], `page errors: ${pageErrors.join(" | ")}`);
    console.log(`[E2E] Factor Validation passed; screenshots=${screenshotDir}`);
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
