/**
 * Dragon-Tiger market discovery source-to-sink browser acceptance.
 *
 * Uses the production build and the real FastAPI app.  The E2E-only Python
 * entry replaces only the existing Eastmoney request function with an isolated
 * report fixture; no page.route mocks or production-only HTTP endpoints are
 * involved.
 */
import { chromium } from "playwright";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { createServer, request as httpRequest } from "node:http";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = path.join(root, "backend");
const harnessDir = __dirname;
const frontendDist = path.join(root, "frontend", "dist");
const screenshotDir = path.join(root, "docs", "screenshots", "dragon-tiger-discovery1-r2");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolvePython() {
  if (process.env.VR_E2E_PYTHON?.trim()) return { command: process.env.VR_E2E_PYTHON.trim(), prefix: [] };
  if (process.env.VR_PYTHON?.trim()) return { command: process.env.VR_PYTHON.trim(), prefix: [] };
  const win = path.join(backendDir, ".venv", "Scripts", "python.exe");
  if (existsSync(win)) return { command: win, prefix: [] };
  const lin = path.join(backendDir, ".venv", "bin", "python");
  if (existsSync(lin)) return { command: lin, prefix: [] };
  return process.platform === "win32" ? { command: "py", prefix: ["-3"] } : { command: "python3", prefix: [] };
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitHttp(url, attempts = 100) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return response;
    } catch {
      // The child process may still be starting.
    }
    await sleep(300);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function createProxyRequest(req, res, backendPort) {
  const proxyReq = httpRequest(
    {
      hostname: "127.0.0.1",
      port: backendPort,
      path: req.url,
      method: req.method,
      headers: { ...req.headers, host: `127.0.0.1:${backendPort}` },
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
      proxyRes.pipe(res, { end: true });
    },
  );
  proxyReq.on("error", (error) => {
    if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(`Bad Gateway: ${error.message}`);
  });
  return proxyReq;
}

async function startStaticServer(dir, port, backendPort) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  };
  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    if (rawUrl.startsWith("/api/")) {
      const proxyReq = createProxyRequest(req, res, backendPort);
      req.pipe(proxyReq, { end: true });
      return;
    }

    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    let resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || path.extname(target) === "") target = path.join(dir, "index.html");
    resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep)) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    res.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve());
  });
  return server;
}

async function startBackend(tempDir) {
  const port = await getFreePort();
  const python = resolvePython();
  const inheritedPythonPath = process.env.PYTHONPATH?.trim();
  const pythonPath = [backendDir, harnessDir, inheritedPythonPath].filter(Boolean).join(path.delimiter);
  const child = spawn(
    python.command,
    [...python.prefix, "-m", "uvicorn", "dragon_tiger_discovery_harness_app:app", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        PYTHONPATH: pythonPath,
        VR_DATA_DIR: tempDir,
        VR_REPORTS_DIR: path.join(tempDir, "reports"),
        VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let logs = "";
  child.stdout.on("data", (chunk) => { logs += chunk.toString(); });
  child.stderr.on("data", (chunk) => { logs += chunk.toString(); });
  try {
    await waitHttp(`http://127.0.0.1:${port}/api/health`);
  } catch (error) {
    await stopProcess(child);
    throw new Error(`${error.message}\n${logs}`);
  }
  return { child, port };
}

async function stopProcess(child) {
  if (!child || child.exitCode != null) return;
  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" });
      killer.once("exit", resolve);
      killer.once("error", resolve);
    });
  } else {
    child.kill("SIGTERM");
  }
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 5000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function launchBrowser() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  const options = { headless: true, ...(executablePath ? { executablePath } : { channel: "chrome" }) };
  try {
    const browser = await chromium.launch(options);
    return { browser, label: `${options.channel || "executable"}-${browser.version()}` };
  } catch (error) {
    if (executablePath) throw error;
    const browser = await chromium.launch({ headless: true });
    return { browser, label: `playwright-chromium-${browser.version()}` };
  }
}

async function assertNoOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  if (dimensions.scrollWidth > dimensions.innerWidth + 1) {
    throw new Error(`${label} has horizontal overflow: ${JSON.stringify(dimensions)}`);
  }
}

async function requestPayload(page, testId) {
  const responsePromise = page.waitForResponse((response) => {
    try {
      return new URL(response.url()).pathname === "/api/market/dragon-tiger";
    } catch {
      return false;
    }
  });
  await page.getByTestId(testId).click();
  const response = await responsePromise;
  if (response.status() !== 200) throw new Error(`Dragon-Tiger HTTP ${response.status()}`);
  const body = await response.json();
  if (!body || typeof body !== "object" || !body.data) throw new Error(`Dragon-Tiger response wrapper missing data: ${JSON.stringify(body)}`);
  return body.data;
}

async function main() {
  if (!existsSync(frontendDist)) throw new Error(`Frontend dist missing: ${frontendDist}; run npm run build first`);
  await mkdir(screenshotDir, { recursive: true });
  const tempDir = await mkdtemp(path.join(tmpdir(), "vr-dragon-tiger-e2e-"));
  const backend = await startBackend(tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port);
  const { browser, label } = await launchBrowser();
  const apiRequests = [];
  const consoleErrors = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  const baseUrl = `http://127.0.0.1:${frontendPort}`;

  try {
    console.log(`[E2E] browser=${label}`);
    await page.goto(`${baseUrl}/screener`, { waitUntil: "networkidle" });
    for (const name of ["机会发现", "候选筛选", "Full Market", "龙虎榜"]) {
      const tab = page.getByRole("tab", { name, exact: true });
      await tab.waitFor({ state: "visible", timeout: 15000 });
    }
    await page.getByTestId("dragon-tiger-tab").click();
    if (await page.getByTestId("dragon-tiger-tab").getAttribute("aria-selected") !== "true") {
      throw new Error("Dragon-Tiger tab did not become selected");
    }
    const normal = await requestPayload(page, "load-dragon-tiger-discovery");
    if (normal.schema_version !== "dragon_tiger_discovery.v0.1" || normal.status !== "NORMAL" || normal.trade_date !== "2026-09-09") {
      throw new Error(`unexpected normal envelope: ${JSON.stringify(normal)}`);
    }
    if (normal.pagination.returned_rows !== 66 || normal.pagination.source_count !== 66 || normal.pagination.source_pages !== 2 || normal.pagination.fetched_pages !== 2 || normal.pagination.truncated || normal.completeness.status !== "COMPLETE" || normal.rows.length !== 66) {
      throw new Error(`normal completeness mismatch: ${JSON.stringify(normal.pagination)}`);
    }
    const sameSecurityRows = normal.rows.filter((row) => row.security_code === "000001");
    if (sameSecurityRows.length !== 2 || new Set(sameSecurityRows.map((row) => row.source_record_identity)).size !== 2 || new Set(sameSecurityRows.map((row) => row.reason)).size !== 2) {
      throw new Error("normal fixture did not preserve distinct same-security source records");
    }
    if (normal.formal_state_write?.performed !== false) throw new Error("normal discovery reported a formal write");
    const result = page.getByTestId("dragon-tiger-discovery-result");
    await result.waitFor({ state: "visible" });
    const normalText = await result.innerText();
    for (const expected of [
      "数据状态：源记录已返回",
      "源交易日：2026-09-09",
      "来源：EASTMONEY_DATA_CENTER",
      "报告：RPT_DAILYBILLBOARD_DETAILSNEW",
      "返回记录：66 / 66",
      "已覆盖源报告记录",
    ]) {
      if (!normalText.includes(expected)) throw new Error(`normal UI missing ${expected}`);
    }
    const panelText = await page.getByTestId("dragon-tiger-discovery-panel").innerText();
    for (const expected of ["不是全 A 股票清单", "不产生买卖建议"]) {
      if (!panelText.includes(expected)) throw new Error(`normal source-boundary UI missing ${expected}`);
    }
    const stockLink = result.locator('a[href="/stock-data?code=000001"]').first();
    const candidateLink = result.locator('a[href="/candidates/000001"]').first();
    if (!(await stockLink.isVisible()) || !(await candidateLink.isVisible())) throw new Error("allowed research links missing");
    if (await result.getByText("BUY", { exact: true }).count() || await result.getByText("SELL", { exact: true }).count()) {
      throw new Error("Dragon-Tiger panel exposed BUY/SELL semantics");
    }
    if (await result.getByTestId("dragon-tiger-discovery-row").count() !== 66) {
      throw new Error("normal UI did not render the complete multi-page result");
    }
    await assertNoOverflow(page, "desktop Dragon-Tiger result");
    await page.screenshot({ path: path.join(screenshotDir, "normal-desktop.png"), fullPage: true });

    const marketRequests = apiRequests.filter((url) => url.includes("/api/market/dragon-tiger"));
    if (marketRequests.length !== 1) throw new Error(`expected one market discovery request, got ${marketRequests.length}`);
    if (apiRequests.some((url) => url.includes("/api/dragon-tiger") || url.includes("/api/market/dragon-tiger/seat"))) {
      throw new Error("market discovery emitted per-security or seat requests");
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId("dragon-tiger-trade-date").fill("2026-09-08");
    const overlap = await requestPayload(page, "load-dragon-tiger-discovery");
    if (overlap.schema_version !== "dragon_tiger_discovery.v0.1" || overlap.status !== "UNAVAILABLE" || overlap.completeness.status !== "UNAVAILABLE" || overlap.rows.length !== 0 || !overlap.limitations.includes("SOURCE_PAGE_IDENTITY_OVERLAP")) {
      throw new Error(`unexpected overlap envelope: ${JSON.stringify(overlap)}`);
    }
    const overlapText = await result.innerText();
    for (const expected of ["数据状态：源暂不可用", "源交易日：2026-09-08", "未完成读取", "限制：SOURCE_PAGE_IDENTITY_OVERLAP"]) {
      if (!overlapText.includes(expected)) throw new Error(`overlap UI missing ${expected}`);
    }
    if (overlapText.includes("已覆盖源报告记录") || await page.getByTestId("dragon-tiger-discovery-table").count()) {
      throw new Error("overlap UI presented a complete Dragon-Tiger result");
    }
    await assertNoOverflow(page, "narrow overlapping Dragon-Tiger result");
    await page.screenshot({ path: path.join(screenshotDir, "overlap-narrow.png"), fullPage: true });

    await page.getByTestId("dragon-tiger-trade-date").fill("2026-09-06");
    const empty = await requestPayload(page, "load-dragon-tiger-discovery");
    if (empty.schema_version !== "dragon_tiger_discovery.v0.1" || empty.status !== "EMPTY" || empty.trade_date !== null || empty.requested_trade_date !== "2026-09-06") {
      throw new Error(`unexpected empty envelope: ${JSON.stringify(empty)}`);
    }
    const emptyResult = page.getByTestId("dragon-tiger-discovery-result");
    await emptyResult.waitFor({ state: "visible" });
    const emptyText = await emptyResult.innerText();
    for (const expected of ["数据状态：该交易日无记录", "源交易日：2026-09-06", "返回记录：0 / 0", "源报告无记录"]) {
      if (!emptyText.includes(expected)) throw new Error(`empty UI missing ${expected}`);
    }
    if (await page.getByTestId("dragon-tiger-discovery-table").count()) throw new Error("empty result rendered a table");
    await assertNoOverflow(page, "narrow empty Dragon-Tiger result");
    await page.screenshot({ path: path.join(screenshotDir, "empty-narrow.png"), fullPage: true });

    const allMarketRequests = apiRequests.filter((url) => url.includes("/api/market/dragon-tiger"));
    if (allMarketRequests.length !== 3) throw new Error(`expected three market discovery requests, got ${allMarketRequests.length}`);

    if (consoleErrors.length) throw new Error(`browser console errors: ${consoleErrors.join(" | ")}`);
    console.log(`[E2E] normal=${normal.status} rows=${normal.rows.length}; overlap=${overlap.status}; empty=${empty.status}; screenshots=${screenshotDir}`);
    console.log("[E2E] Dragon-Tiger market discovery source-to-sink browser acceptance OK");
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
    await new Promise((resolve) => staticServer.close(resolve));
    await stopProcess(backend.child);
    await rm(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error("[E2E] FAILED", error);
  process.exitCode = 1;
});
