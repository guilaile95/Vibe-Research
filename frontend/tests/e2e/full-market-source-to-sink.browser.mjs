/**
 * #220 Full Market source-to-sink browser vertical.
 *
 * Uses the built frontend, a real isolated FastAPI app, and a real RDP Parquet
 * artifact imported from a temporary CSV. No page.route mocks or production
 * E2E-only endpoints are used. The timing scenario uses the static server's
 * API fixture hook to delay/fail requests without changing business authority.
 */
import { chromium } from "playwright";
import { appendFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { createServer, request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = path.join(root, "backend");
const frontendDist = path.join(root, "frontend", "dist");
const browserForbidden = [];
const backendGuardLogs = [];
const screenshotDir = process.env.E2E_SCREENSHOT_DIR || path.join(root, "docs", "screenshots", "full-market-source-to-sink");

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
  return process.platform === "win32"
    ? { command: "py", prefix: ["-3"] }
    : { command: "python3", prefix: [] };
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

function startStaticServer(dir, port, backendPort, { apiRoute } = {}) {
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
      if (apiRoute?.(req, res, backendPort) === true) return;
      const proxyReq = createServerProxyRequest(req, res, backendPort);
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
    if (path.extname(target) === ".html") {
      // Browser request routes cannot observe speculative DNS/preconnect sockets.
      // Strip only resource hints in this test server; the exact font stylesheet
      // is separately fulfilled locally by the browser guard.
      void readFile(target, "utf8").then(html => {
        res.end(html.replace(/<link\b(?=[^>]*\brel=["'](?:preconnect|dns-prefetch)["'])[^>]*>/gi, ""));
      }).catch(() => { res.writeHead(500); res.end("fixture HTML read failed"); });
      return;
    }
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function createServerProxyRequest(req, res, backendPort) {
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

function delayedProxyRequest(req, res, backendPort, delayMs, onBackendResponse) {
  setTimeout(() => {
    const proxyReq = httpRequest(
      {
        hostname: "127.0.0.1",
        port: backendPort,
        path: req.url,
        method: req.method,
        headers: { ...req.headers, host: `127.0.0.1:${backendPort}` },
      },
      (proxyRes) => {
        onBackendResponse?.();
        if (res.destroyed) {
          proxyRes.resume();
          return;
        }
        res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
        proxyRes.pipe(res, { end: true });
      },
    );
    proxyReq.on("error", (error) => {
      if (res.destroyed) return;
      if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      res.end(`Bad Gateway: ${error.message}`);
    });
    proxyReq.end();
  }, delayMs);
}

function createFailureTimingFixture() {
  let requestCount = 0;
  let resolveStarted;
  let release;
  const started = new Promise((resolve) => { resolveStarted = resolve; });
  const released = new Promise((resolve) => { release = resolve; });
  return {
    started,
    release: () => release(),
    apiRoute(req, res) {
      if ((req.url || "").split("?")[0] !== "/api/screener/full-market") return false;
      requestCount += 1;
      if (requestCount === 1) return false;
      if (requestCount !== 2) return false;
      resolveStarted();
      void released.then(() => {
        if (res.destroyed) return;
        res.writeHead(503, { "content-type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ detail: "timing fixture failure" }));
      });
      return true;
    },
  };
}

function createDelayedResponseFixture() {
  let requestCount = 0;
  let resolveStarted;
  let resolveReturned;
  let release;
  const started = new Promise((resolve) => { resolveStarted = resolve; });
  const returned = new Promise((resolve) => { resolveReturned = resolve; });
  const released = new Promise((resolve) => { release = resolve; });
  return {
    started,
    returned,
    release: () => release(),
    apiRoute(req, res, backendPort) {
      if ((req.url || "").split("?")[0] !== "/api/screener/full-market") return false;
      requestCount += 1;
      if (requestCount !== 1) return false;
      resolveStarted();
      void released.then(() => delayedProxyRequest(req, res, backendPort, 0, resolveReturned));
      return true;
    },
  };
}


async function runProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(" ")} exited ${code}: ${stderr || stdout}`));
    });
  });
}

async function seedRdpFixture(kind = "full-market") {
  const tempDir = await mkdtemp(path.join(tmpdir(), "vr-full-market-e2e-"));
  const csv = path.join(tempDir, `${kind}.csv`);
  const rdpRoot = path.join(tempDir, "research-data-plane");
  const lines = ["code,trade_date,open,high,low,close,volume"];
  if (kind === "candidate-window") {
    const start = Date.UTC(2026, 0, 1);
    for (let index = 0; index < 150; index += 1) {
      const tradeDate = new Date(start + index * 86400000).toISOString().slice(0, 10);
      const close = index < 120 ? 10 + index / 10 : 1;
      lines.push(`000001,${tradeDate},${close},${close + 1},${close - 0.5},${close},${1000 + index}`);
      if (index < 30) {
        const other = 20 - index / 10;
        lines.push(`000003,${tradeDate},${other},${other + 1},${other - 0.5},${other},${1000 + index}`);
      }
    }
  } else {
  const start = Date.UTC(2026, 0, 2);
  for (let index = 0; index < 65; index += 1) {
    const tradeDate = new Date(start + index * 86400000).toISOString().slice(0, 10);
    for (const [code, base, volume] of [["000001", 10, 100], ["000002", 20, 200]]) {
      const close = base + index;
      lines.push(`${code},${tradeDate},${close},${close + 1},${close - 1},${close},${volume + index}`);
    }
  }
  lines.push("600519,2026-03-07,12,13,11,12,300");
  }
  await writeFile(csv, `${lines.join("\n")}\n`, "utf8");
  const python = resolvePython();
  await runProcess(python.command, [...python.prefix, "-m", "research_data_plane", "import-csv", csv, "--root", rdpRoot], {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: backendDir },
  });
  const manifest = JSON.parse(await readFile(path.join(rdpRoot, "manifest.json"), "utf8"));
  return { tempDir, rdpRoot, manifest };
}

async function startBackend(rdpRoot, tempDir) {
  const port = await getFreePort();
  const python = resolvePython();
  const networkLog = path.join(tempDir, `network-guard-${port}.json`);
  backendGuardLogs.push(networkLog);
  const child = spawn(python.command, [...python.prefix, "-m", "uvicorn", "screener_offline_harness_app:app", "--loop", "asyncio", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: backendDir,
    env: {
      ...process.env,
      PYTHONPATH: [__dirname, backendDir].join(path.delimiter),
      VR_SCREENER_NETWORK_LOG: networkLog,
      VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: "1",
      VR_DATA_DIR: tempDir,
      VR_REPORTS_DIR: path.join(tempDir, "reports"),
      VIBE_RESEARCH_RESEARCH_DATA_DIR: rdpRoot,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
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
    await runProcess("taskkill", ["/pid", String(child.pid), "/t", "/f"]).catch(() => {});
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

async function newOfflinePage(browser, origin) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  await context.routeWebSocket("**/*", socket => {
    browserForbidden.push(`WebSocket ${socket.url()}`);
    socket.close();
  });
  await context.route("**/*", route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && request.resourceType() === "stylesheet"
      && url.href === "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap") {
      return route.fulfill({ contentType: "text/css", body: "/* Offline system font fallback. */" });
    }
    if (url.origin !== origin) {
      browserForbidden.push(`HTTP ${url.origin}`);
      return route.abort();
    }
    return route.continue();
  });
  return context.newPage();
}

async function assertOfflineAudit() {
  const backendAttempts = [];
  for (const log of backendGuardLogs) {
    const attempts = JSON.parse(await readFile(log, "utf8"));
    if (!Array.isArray(attempts)) throw new Error("Backend network guard receipt is invalid");
    backendAttempts.push(...attempts);
  }
  const result = { browserForbidden, backendAttempts, guardedBackends: backendGuardLogs.length };
  await writeFile(path.join(screenshotDir, "network-audit.json"), JSON.stringify(result, null, 2));
  if (browserForbidden.length || backendAttempts.length) throw new Error(`Offline guard violations: ${JSON.stringify(result)}`);
  console.log(`[E2E] Offline audit: ${backendGuardLogs.length} guarded backends; zero forbidden browser/backend network attempts`);
}

async function assertVisible(locator, label) {
  if (!(await locator.isVisible().catch(() => false))) throw new Error(`missing visible ${label}`);
}

async function captureScenarioFailure(page, label, error) {
  // Diagnostic failures must not hide the assertion or skip the offline audit.
  await Promise.allSettled([
    page.screenshot({ path: path.join(screenshotDir, `${label}-failure.png`), fullPage: true }),
    page.locator("body").innerText().then(text => writeFile(
      path.join(screenshotDir, `${label}-failure.json`),
      JSON.stringify({ error: String(error?.message || error), url: page.url(), text }, null, 2),
    )),
  ]);
}

async function runNormalScenario(browser, fixture) {
  const backend = await startBackend(fixture.rdpRoot, fixture.tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port);
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const page = await newOfflinePage(browser, baseUrl);
  const apiRequests = [];
  const consoleErrors = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  try {
    // Avoid the default live-provider Discovery tab; these scenarios use local RDP only.
    await page.goto(`${baseUrl}/screener?mode=candidate`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("full-market-tab").waitFor({ state: "visible" });
    await assertVisible(page.getByRole("tab", { name: "全市场筛选", exact: true }), "Full Market tab on /screener");
    await page.screenshot({ path: path.join(screenshotDir, "normal-01-screener.png"), fullPage: true });

    await page.getByTestId("full-market-tab").click();
    await assertVisible(page.getByTestId("full-market-form"), "Full Market query form");
    if (await page.getByTestId("full-market-tab").getAttribute("aria-selected") !== "true") {
      throw new Error("Full Market tab did not become selected");
    }
    await page.screenshot({ path: path.join(screenshotDir, "normal-02-full-market-form.png"), fullPage: true });

    await page.getByLabel("使用最新可用日期", { exact: true }).uncheck();
    await page.getByLabel("Full Market as of", { exact: true }).fill("2026-02-20");
    await page.getByLabel("使用最新可用日期", { exact: true }).check();

    const responsePromise = page.waitForResponse((response) => {
      try {
        return new URL(response.url()).pathname === "/api/screener/full-market";
      } catch {
        return false;
      }
    });
    await page.getByTestId("run-full-market").click();
    const response = await responsePromise;
    if (response.status() !== 200) throw new Error(`Full Market HTTP ${response.status()}`);
    const payload = await response.json();
    const requestUrl = new URL(response.url());
    if (requestUrl.searchParams.get("latest") !== "true") throw new Error("query latest=true missing");
    if (requestUrl.searchParams.has("as_of")) throw new Error("latest query retained a hidden historical cutoff");
    const filters = JSON.parse(requestUrl.searchParams.get("filters") || "null");
    if (JSON.stringify(filters) !== JSON.stringify([{ metric: "return_20d", operator: "gte", value: 0 }])) {
      throw new Error("default Full Market filter was not submitted");
    }
    if (requestUrl.searchParams.get("sort_by") !== "return_20d") throw new Error("query sort_by missing");
    if (requestUrl.searchParams.get("sort_order") !== "desc") throw new Error("query sort_order missing");
    if (requestUrl.searchParams.get("limit") !== "50" || requestUrl.searchParams.get("offset") !== "0") {
      throw new Error("query pagination missing");
    }
    if (payload.schema_version !== "research-data-plane.full-market.v0.1" || payload.status !== "normal") {
      throw new Error(`unexpected normal result envelope: ${JSON.stringify(payload)}`);
    }
    if (payload.rows.length !== 2 || !payload.rows.some((row) => row.code === "000001")) {
      throw new Error(`expected two evaluable result rows, got ${payload.rows.length}`);
    }
    if (payload.coverage?.start !== "2026-01-02" || payload.coverage?.end !== "2026-03-07" || payload.coverage?.row_count !== 131 || payload.coverage?.code_count !== 3 || payload.coverage?.universe_count !== 3) {
      throw new Error(`unexpected coverage: ${JSON.stringify(payload.coverage)}`);
    }
    if (payload.provenance?.source_name !== "full-market.csv" || payload.provenance?.artifact_sha256 !== fixture.manifest.artifact_sha256) {
      throw new Error(`unexpected provenance: ${JSON.stringify(payload.provenance)}`);
    }
    if (payload.rows.some((row) => row.code === "600519")) throw new Error("short-history row should be filtered from return_20d >= 0");
    if (apiRequests.filter((url) => url.includes("/api/screener/full-market")).length !== 1) {
      throw new Error("expected exactly one Full Market request");
    }
    if (apiRequests.some((url) => url.includes("/api/screener/evaluate") || url.includes("/api/kline"))) {
      throw new Error("Full Market query emitted a candidate/per-stock request");
    }

    await page.getByTestId("full-market-summary").waitFor({ state: "visible" });
    const summaryText = await page.getByTestId("full-market-summary").innerText();
    for (const expected of ["全市场筛选数据", "可用", "2026-01-02", "2026-03-07", "131 行", "3 个代码", "横截面 3 个代码", "当期 3 · 过期 0", "full-market.csv", fixture.manifest.artifact_sha256]) {
      if (!summaryText.includes(expected)) throw new Error(`normal summary missing ${expected}`);
    }
    await assertVisible(page.getByTestId("full-market-results"), "normal Full Market results");
    await assertVisible(page.getByRole("link", { name: "000001" }), "000001 result link");
    await page.screenshot({ path: path.join(screenshotDir, "normal-03-result-provenance.png"), fullPage: true });

    await page.getByTestId("full-market-add-filter").click();
    if (await page.getByTestId("full-market-results").count()) throw new Error("adding a condition retained stale results");
    await page.getByLabel("Full Market filter metric", { exact: true }).nth(1).selectOption("latest_close");
    await page.getByLabel("Full Market filter operator", { exact: true }).nth(1).selectOption("lt");
    await page.getByLabel("Full Market filter value", { exact: true }).nth(1).fill("80");
    const combinedResponsePromise = page.waitForResponse((item) => new URL(item.url()).pathname === "/api/screener/full-market");
    await page.getByTestId("run-full-market").click();
    const combinedResponse = await combinedResponsePromise;
    const combined = await combinedResponse.json();
    const combinedFilters = JSON.parse(new URL(combinedResponse.url()).searchParams.get("filters") || "null");
    if (combinedFilters?.length !== 2 || combinedFilters[1].metric !== "latest_close" || combinedFilters[1].operator !== "lt" || combinedFilters[1].value !== 80) {
      throw new Error("UI did not submit both AND conditions");
    }
    if (combinedResponse.status() !== 200 || combined.total_rows !== 1 || combined.rows[0]?.code !== "000001") {
      throw new Error("AND query did not narrow the two matching rows to 000001");
    }
    if (combined.coverage?.universe_count !== 3 || combined.breadth.ma20.evaluable_count !== 2) {
      throw new Error("AND filtering changed the full-universe coverage or breadth");
    }
    await page.getByTestId("full-market-results").waitFor({ state: "visible" });
    const candidate = page.getByTestId("full-market-results").getByRole("link", { name: "候选研究" });
    if (await candidate.getAttribute("href") !== "/candidates/000001") throw new Error("AND result lost its candidate research handoff");
    await page.screenshot({ path: path.join(screenshotDir, "normal-05-and-results.png"), fullPage: true });
    await page.getByTestId("full-market-results").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(screenshotDir, "normal-07-and-result-table.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId("full-market-form").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(screenshotDir, "normal-06-and-mobile.png"), fullPage: true });
    await page.setViewportSize({ width: 1280, height: 720 });
    console.log(`[E2E] AND conditions=2 rows=${combined.total_rows}; candidate=/candidates/000001; url=${baseUrl}/screener`);

    // Keep this vertical within local RDP. Loading StockData would start unrelated
    // live-source reads. This assertion covers the handoff href only; destination
    // query/Back/Forward behavior has separate qa-stock-navigation.browser.mjs
    // coverage, and stock-data-panel.smoke.browser.mjs runs in the existing CI job.
    if (await page.getByRole("link", { name: "000001" }).getAttribute("href") !== "/stock-data?code=000001") {
      throw new Error("code link handoff href mismatch");
    }
    await page.screenshot({ path: path.join(screenshotDir, "normal-04-stock-data-handoff-link.png"), fullPage: true });
    if (consoleErrors.length) throw new Error(`browser console errors: ${consoleErrors.join(" | ")}`);
    return { payload, requestUrl: response.url() };
  } catch (error) {
    await captureScenarioFailure(page, "normal", error);
    throw error;
  } finally {
    await page.close().catch(() => {});
    await new Promise((resolve) => staticServer.close(resolve));
    await stopProcess(backend.child);
  }
}

async function runFailureClearsScenario(browser, fixture) {
  const timing = createFailureTimingFixture();
  const backend = await startBackend(fixture.rdpRoot, fixture.tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port, timing);
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const page = await newOfflinePage(browser, baseUrl);
  try {
    // Avoid the default live-provider Discovery tab; these scenarios use local RDP only.
    await page.goto(`${baseUrl}/screener?mode=candidate`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("full-market-tab").waitFor({ state: "visible" });
    await page.getByTestId("full-market-tab").click();

    const firstResponsePromise = page.waitForResponse((response) => {
      try {
        return new URL(response.url()).pathname === "/api/screener/full-market";
      } catch {
        return false;
      }
    });
    await page.getByTestId("run-full-market").click();
    const firstResponse = await firstResponsePromise;
    if (firstResponse.status() !== 200) throw new Error(`timing setup Full Market HTTP ${firstResponse.status()}`);
    await page.getByRole("link", { name: "000001" }).waitFor({ state: "visible" });

    const oldSummary = page.getByTestId("full-market-summary");
    const oldResults = page.getByTestId("full-market-results");
    if (!(await oldSummary.isVisible()) || !(await oldResults.isVisible())) {
      throw new Error("timing setup did not render the successful Full Market result");
    }

    const failedResponsePromise = page.waitForResponse((response) => {
      try {
        return new URL(response.url()).pathname === "/api/screener/full-market";
      } catch {
        return false;
      }
    });
    await page.getByTestId("run-full-market").click();
    await Promise.all([
      timing.started,
      oldSummary.waitFor({ state: "detached" }),
      oldResults.waitFor({ state: "detached" }),
    ]);
    if (await page.getByRole("link", { name: "000001" }).count()) {
      throw new Error("failed Full Market query left the old result row visible");
    }
    timing.release();
    const failedResponse = await failedResponsePromise;
    if (failedResponse.status() !== 503) throw new Error(`timing failure Full Market HTTP ${failedResponse.status()}`);
    await page.getByText("timing fixture failure").waitFor({ state: "visible" });
    if (await page.getByTestId("full-market-results").count()) {
      throw new Error("failed Full Market query re-rendered the old result table");
    }
    console.log("[E2E] Full Market success -> failure clears stale rows immediately OK");
  } catch (error) {
    await captureScenarioFailure(page, "failure-clears", error);
    throw error;
  } finally {
    timing.release();
    await page.close().catch(() => {});
    await new Promise((resolve) => staticServer.close(resolve));
    await stopProcess(backend.child);
  }
}

async function runModeSwitchScenario(browser, fixture) {
  const timing = createDelayedResponseFixture();
  const backend = await startBackend(fixture.rdpRoot, fixture.tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port, timing);
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const page = await newOfflinePage(browser, baseUrl);
  try {
    // Avoid the default live-provider Discovery tab; these scenarios use local RDP only.
    await page.goto(`${baseUrl}/screener?mode=candidate`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("full-market-tab").waitFor({ state: "visible" });
    await page.getByTestId("full-market-tab").click();
    await page.getByTestId("run-full-market").click();
    await timing.started;
    const fullMarketButton = page.getByTestId("run-full-market");
    if (!(await fullMarketButton.isDisabled()) || (await fullMarketButton.innerText()) !== "查询中…") {
      throw new Error("Full Market loading state was not visible while the request was pending");
    }

    await page.getByTestId("candidate-pool-tab").click();
    if (await page.getByTestId("candidate-pool-tab").getAttribute("aria-selected") !== "true") {
      throw new Error("Candidate Pool did not become selected during pending Full Market request");
    }
    await page.getByRole("button", { name: "运行筛选" }).waitFor({ state: "visible" });
    await page.getByTestId("full-market-tab").click();
    if (await page.getByTestId("run-full-market").isDisabled()) {
      throw new Error("Full Market loading did not reset after switching to Candidate Pool");
    }
    if (await page.getByTestId("full-market-summary").count() || await page.getByTestId("full-market-results").count()) {
      throw new Error("switching back to Full Market retained stale results");
    }

    timing.release();
    await timing.returned;
    await page.waitForTimeout(100);
    if (await page.getByTestId("full-market-summary").count() || await page.getByTestId("full-market-results").count()) {
      throw new Error("late Full Market response repopulated Full Market after mode switch");
    }
    if (await page.getByTestId("run-full-market").isDisabled()) {
      throw new Error("late Full Market response changed the reset loading state");
    }
    console.log("[E2E] Full Market pending -> Candidate Pool resets loading and blocks stale response OK");
  } catch (error) {
    await captureScenarioFailure(page, "mode-switch", error);
    throw error;
  } finally {
    timing.release();
    await page.close().catch(() => {});
    await new Promise((resolve) => staticServer.close(resolve));
    await stopProcess(backend.child);
  }
}

async function runUnavailableScenario(browser, rdpRoot, tempDir, kind, expectedReason) {
  const backend = await startBackend(rdpRoot, tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port);
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const page = await newOfflinePage(browser, baseUrl);
  const prefix = kind === "corrupt" ? "corrupt" : "unavailable";
  try {
    // Avoid the default live-provider Discovery tab; these scenarios use local RDP only.
    await page.goto(`${baseUrl}/screener?mode=candidate`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("full-market-tab").waitFor({ state: "visible" });
    await page.screenshot({ path: path.join(screenshotDir, `${prefix}-01-screener.png`), fullPage: true });
    await page.getByTestId("full-market-tab").click();
    await page.screenshot({ path: path.join(screenshotDir, `${prefix}-02-full-market-form.png`), fullPage: true });
    const responsePromise = page.waitForResponse((response) => {
      try {
        return new URL(response.url()).pathname === "/api/screener/full-market";
      } catch {
        return false;
      }
    });
    await page.getByTestId("run-full-market").click();
    const response = await responsePromise;
    if (response.status() !== 200) throw new Error(`${kind} Full Market HTTP ${response.status()}`);
    const payload = await response.json();
    if (payload.status !== "unavailable" || payload.rows.length !== 0 || payload.coverage !== null || payload.provenance?.artifact_sha256 !== null) {
      throw new Error(`${kind} did not fail closed: ${JSON.stringify(payload)}`);
    }
    if (!payload.limitations.join(" ").includes(expectedReason)) {
      throw new Error(`${kind} limitation missing ${expectedReason}: ${payload.limitations.join(" | ")}`);
    }
    await page.getByTestId("full-market-summary").waitFor({ state: "visible" });
    const summaryText = await page.getByTestId("full-market-summary").innerText();
    if (!summaryText.includes("不可用") || !summaryText.includes("本地研究数据不可用")) {
      throw new Error(`${kind} unavailable state is not visible in the UI: ${summaryText}`);
    }
    if (await page.getByRole("link", { name: "000001" }).count()) throw new Error(`${kind} rendered a result link`);
    await page.screenshot({ path: path.join(screenshotDir, `${prefix}-03-unavailable.png`), fullPage: true });
  } catch (error) {
    await captureScenarioFailure(page, kind, error);
    throw error;
  } finally {
    await page.close().catch(() => {});
    await new Promise((resolve) => staticServer.close(resolve));
    await stopProcess(backend.child);
  }
}

async function runCandidateCoverageScenario(browser, fixture) {
  const backend = await startBackend(fixture.rdpRoot, fixture.tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port);
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const page = await newOfflinePage(browser, baseUrl);
  const mutations = [];
  const errors = [];
  page.on("request", request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith("/api/") && !["GET", "HEAD", "OPTIONS"].includes(request.method())
      && !(pathname === "/api/screener/evaluate" && request.method() === "POST")) {
      mutations.push(`${request.method()} ${pathname}`);
    }
  });
  page.on("pageerror", error => errors.push(error.message));
  const submit = async (codes) => {
    await page.getByPlaceholder("000001 600519", { exact: true }).fill(codes);
    const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === "/api/screener/evaluate"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "运行筛选", exact: true }).click();
    const response = await responsePromise;
    if (response.status() !== 200) throw new Error(`Candidate response ${response.status()}: ${await response.text()}`);
    await page.getByRole("button", { name: "运行筛选", exact: true }).waitFor({ state: "visible" });
    return response.json();
  };
  const requireText = async (locator, expected) => {
    await locator.filter({ hasText: expected }).waitFor({ state: "visible" });
  };
  try {
    // Avoid the default live-provider Discovery tab; these scenarios use local RDP only.
    await page.goto(`${baseUrl}/screener?mode=candidate`, { waitUntil: "domcontentloaded" });
    await page.getByPlaceholder("000001 600519", { exact: true }).waitFor({ state: "visible" });
    const source = page.getByTestId("screener-research-source");
    const batch = page.getByTestId("screener-batch-coverage");
    const latest = await submit("000001");
    const row = latest.rejected?.[0];
    if (latest.matched.length || row?.code !== "000001" || row.trade_date !== "2026-05-30"
      || row.condition_results[0]?.passed !== false || row.data_coverage?.returned_rows !== 120
      || row.data_coverage.start !== "2026-01-31" || row.data_coverage.end !== "2026-05-30"
      || row.data_coverage.artifact_sha256 !== fixture.manifest.artifact_sha256
      || !/^[0-9a-f]{64}$/.test(row.data_coverage.snapshot_id || "")) {
      throw new Error(`Candidate must evaluate latest 120, not oldest matching 120: ${JSON.stringify(latest)}`);
    }
    await requireText(source, "全部请求已读到样本");
    await requireText(source, "整份数据集覆盖（非本次请求）");
    await requireText(source, "180 行 · 2 个代码");
    await requireText(batch, "本次请求 1 股 · 读到样本 1 股");
    const detail = page.locator("details").filter({ has: page.getByTestId("screener-candidate-000001") });
    await detail.locator("summary").press("Enter");
    await requireText(page.getByTestId("screener-sample-000001"), "本股样本：120 行 · 2026-01-31 至 2026-05-30");
    await requireText(page.getByTestId("screener-sample-000001"), row.data_coverage.snapshot_id);
    await requireText(detail, "不通过");
    await page.screenshot({ path: path.join(screenshotDir, "candidate-01-latest-window.png"), fullPage: true });

    const partial = await submit("000001 000002");
    if (partial.status !== "partial" || partial.research_data.status !== "partial"
      || partial.batch_coverage?.requested_count !== 2 || partial.batch_coverage.with_data_count !== 1
      || partial.batch_coverage.empty_count !== 1 || partial.unavailable[0]?.matched !== null) {
      throw new Error(`Missing requested code must remain partial/unknown: ${JSON.stringify(partial)}`);
    }
    await requireText(source, "部分请求读到样本");
    await requireText(batch, "本次请求 2 股 · 读到样本 1 股 · 空样本 1 股");
    await requireText(source, "整份数据集覆盖（非本次请求）");
    await page.screenshot({ path: path.join(screenshotDir, "candidate-02-partial-coverage.png"), fullPage: true });

    const empty = await submit("000002");
    if (empty.status !== "unavailable" || empty.research_data.status !== "unavailable"
      || empty.matched.length || empty.rejected.length || empty.unavailable[0]?.data_coverage?.returned_rows !== 0) {
      throw new Error(`Absent code must not inherit artifact availability: ${JSON.stringify(empty)}`);
    }
    await requireText(source, "请求样本不可用");
    await requireText(batch, "本次请求 1 股 · 读到样本 0 股 · 空样本 1 股");
    if (await page.getByTestId("screener-candidate-000001").count()) throw new Error("Previous candidate result remained after rerun");
    await page.screenshot({ path: path.join(screenshotDir, "candidate-03-unavailable-coverage.png"), fullPage: true });
    if (mutations.length || errors.length) throw new Error(`Unexpected writes/page errors: ${JSON.stringify({ mutations, errors })}`);
    console.log("[E2E] Candidate latest120, immutable source, partial/empty coverage and repeated evaluation OK");
  } catch (error) {
    await captureScenarioFailure(page, "candidate", error);
    throw error;
  } finally {
    await page.close().catch(() => {});
    await new Promise(resolve => staticServer.close(resolve));
    await stopProcess(backend.child);
  }
}

async function main() {
  if (!existsSync(frontendDist)) throw new Error(`Frontend dist missing: ${frontendDist}; run npm run build first`);
  await mkdir(screenshotDir, { recursive: true });

  const normal = await seedRdpFixture();
  const corrupt = await seedRdpFixture();
  const candidate = await seedRdpFixture("candidate-window");
  const corruptArtifact = path.join(corrupt.rdpRoot, "artifacts", `${corrupt.manifest.artifact_sha256}.parquet`);
  await appendFile(corruptArtifact, Buffer.from("tampered-by-#220-e2e"));
  const missing = await mkdtemp(path.join(tmpdir(), "vr-full-market-missing-e2e-"));
  const { browser, label } = await launchBrowser();
  try {
    console.log(`[E2E] browser=${label}`);
    const result = await runNormalScenario(browser, normal);
    console.log(`[E2E] normal result=${result.payload.status} rows=${result.payload.rows.length} artifact=${result.payload.provenance.artifact_sha256}`);
    await runFailureClearsScenario(browser, normal);
    await runModeSwitchScenario(browser, normal);
    await runCandidateCoverageScenario(browser, candidate);
    await runUnavailableScenario(browser, missing, missing, "unavailable", "research bulk dataset is not configured");
    console.log("[E2E] unavailable fail-closed OK");
    await runUnavailableScenario(browser, corrupt.rdpRoot, corrupt.tempDir, "corrupt", "Full Market 数据校验失败");
    console.log("[E2E] corrupt fail-closed OK");
    console.log(`[E2E] Full Market source-to-sink browser vertical OK; screenshots=${screenshotDir}`);
  } finally {
    await browser.close().catch(() => {});
    await assertOfflineAudit();
    await rm(normal.tempDir, { recursive: true, force: true });
    await rm(corrupt.tempDir, { recursive: true, force: true });
    await rm(candidate.tempDir, { recursive: true, force: true });
    await rm(missing, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error("[E2E] FAILED", error);
  process.exitCode = 1;
});
