/**
 * PLANNING-PARITY-EVENT-CALENDAR1 browser acceptance.
 *
 * Browser plugin is not available in this environment, so this uses regular
 * Playwright Chromium against a production frontend build and a real FastAPI
 * process.  Provider fixtures are installed only at existing adapter
 * boundaries in research_event_calendar_harness_app.py.
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");
const harnessDir = __dirname;
const screenshotDir = process.env.EVENT_CALENDAR_SCREENSHOT_DIR || path.join(tmpdir(), "vibe-research-event-calendar1");

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitHttp(url, attempts = 100) {
  for (let index = 0; index < attempts; index += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return response;
    } catch { /* retry while uvicorn starts */ }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function resolvePython() {
  if (process.env.PYTHON?.trim()) return process.env.PYTHON.trim();
  if (process.env.VR_PYTHON?.trim()) return process.env.VR_PYTHON.trim();
  const local = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  if (existsSync(local)) return local;
  return process.platform === "win32" ? "py" : "python3";
}

function startStaticServer(dir, port, backendPort) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    const rawUrl = request.url || "/";
    if (rawUrl.startsWith("/api/")) {
      const proxy = fetch(`http://127.0.0.1:${backendPort}${rawUrl}`, {
        method: request.method,
        headers: { ...request.headers, host: `127.0.0.1:${backendPort}` },
      });
      proxy.then(async (upstream) => {
        response.writeHead(upstream.status, Object.fromEntries(upstream.headers.entries()));
        response.end(Buffer.from(await upstream.arrayBuffer()));
      }).catch((error) => {
        response.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
        response.end(`proxy failure: ${error.message}`);
      });
      return;
    }
    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(`${resolvedDir}${path.sep}`) && resolvedTarget !== resolvedDir) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }
    if (!existsSync(target) || path.extname(target) === "") target = path.join(dir, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    import("node:fs").then(({ createReadStream }) => createReadStream(target).pipe(response));
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function chromiumExecutable() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH && existsSync(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH)) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  }
  const roots = [process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "ms-playwright"), process.env.HOME && path.join(process.env.HOME, ".cache", "ms-playwright")].filter(Boolean);
  for (const base of roots) {
    if (!existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const candidates = [
        path.join(base, entry, "chrome-win64", "chrome.exe"),
        path.join(base, entry, "chrome-linux", "chrome"),
      ];
      const found = candidates.find((candidate) => existsSync(candidate));
      if (found) return found;
    }
  }
  return undefined;
}

async function json(url) {
  const response = await fetch(url);
  const body = await response.json();
  assert.equal(response.status, 200, JSON.stringify(body));
  return body;
}

async function main() {
  assert.ok(existsSync(frontendDist), "frontend/dist missing; run npm run build first");
  await mkdir(screenshotDir, { recursive: true });
  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-event-calendar-data-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-event-calendar-reports-"));
  const backendPort = await freePort();
  const frontendPort = await freePort();
  const python = resolvePython();
  const pythonArgs = python === "py" ? ["-3"] : [];
  const campaignDb = path.join(dataDir, "campaigns.sqlite3");
  const env = {
    ...process.env,
    PYTHONPATH: [backendDir, harnessDir, process.env.PYTHONPATH || ""].filter(Boolean).join(process.platform === "win32" ? ";" : ":"),
    VR_ALLOW_ORIGINS: `http://127.0.0.1:${frontendPort}`,
    VR_DATA_DIR: dataDir,
    VR_REPORTS_DIR: reportsDir,
    VIBE_RESEARCH_CAMPAIGN_DB: campaignDb,
    PYTHONUNBUFFERED: "1",
  };
  const backend = spawn(python, [...pythonArgs, "-m", "uvicorn", "research_event_calendar_harness_app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
    cwd: root,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let backendLog = "";
  backend.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
  backend.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
  let staticServer;
  let browser;
  const errors = [];
  const apiBodies = [];
  const forbiddenMutations = [];
  try {
    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`).catch((error) => {
      throw new Error(`${error.message}; backend log: ${backendLog || "<empty>"}`);
    });
    const direct = await json(`http://127.0.0.1:${backendPort}/api/research-events`);
    apiBodies.push(direct);
    const data = direct.data;
    assert.equal(data.schema_version, "research_event_calendar.v0.1");
    assert.equal(data.status, "PARTIAL", JSON.stringify(data));
    assert.equal(data.universe.unique_security_count, 2);
    assert.ok(data.events.some((item) => item.event_type === "PERIODIC_REPORT" && item.state === "EXPECTED"));
    assert.ok(data.events.some((item) => item.event_type === "PERIODIC_REPORT" && item.state === "CONFIRMED"));
    assert.ok(data.events.some((item) => item.event_type === "LOCKUP_EXPIRY" && item.state === "UPCOMING"));
    assert.ok(data.events.some((item) => item.event_type === "DIVIDEND_BONUS" && item.state === "HISTORY"));
    assert.ok(data.events.some((item) => item.event_type === "ANNOUNCEMENT" && item.state === "CONFIRMED"));
    const lockupSource = data.sources.find((item) => item.event_type === "LOCKUP_EXPIRY");
    assert.equal(lockupSource.status, "PARTIAL");
    assert.equal(lockupSource.security_statuses.find((item) => item.security_code === "000002").status, "ERROR");
    assert.deepEqual(data.writes, { campaign: 0, thesis: 0, evidence: 0, decision: 0, trade: 0, account: 0 });

    staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);
    browser = await chromium.launch({ headless: true, ...(chromiumExecutable() ? { executablePath: chromiumExecutable() } : {}) });
    for (const viewport of [
      { name: "desktop-1440", width: 1440, height: 900 },
      { name: "narrow-390", width: 390, height: 844 },
    ]) {
      const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
      const page = await context.newPage();
      // The product already links this optional font from Google; keep the
      // browser assertion independent from that third-party network request.
      await page.route("https://fonts.googleapis.com/**", (route) => route.fulfill({ contentType: "text/css", body: "" }));
      page.on("pageerror", (error) => errors.push(`${viewport.name} pageerror: ${error.message}`));
      page.on("console", (message) => { if (message.type() === "error") errors.push(`${viewport.name} console: ${message.text()}`); });
      page.on("requestfailed", (request) => {
        const failure = request.failure()?.errorText || "unknown";
        // Parent Decision Inbox refresh intentionally aborts the first stale
        // calendar request; this is the response-generation guard under test.
        if (failure !== "net::ERR_ABORTED") errors.push(`${viewport.name} requestfailed ${request.method()} ${request.url()}: ${failure}`);
      });
      page.on("response", (response) => { if (response.status() >= 400) errors.push(`${viewport.name} HTTP ${response.status()} ${response.url()}`); });
      page.on("request", (request) => {
        if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method()) && new URL(request.url()).pathname.startsWith("/api/")) forbiddenMutations.push(`${request.method()} ${request.url()}`);
      });
      await page.goto(`http://127.0.0.1:${frontendPort}/decision-inbox`, { waitUntil: "domcontentloaded" });
      await page.getByTestId("research-event-calendar").waitFor();
      await page.getByRole("heading", { name: "事件日历" }).waitFor();
      await page.getByTestId("research-event-partial").waitFor();
      await page.getByTestId("research-event-row").first().waitFor();
      assert.equal(await page.locator("h1").filter({ hasText: "决策待办" }).count(), 1);
      const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
      assert.ok(dimensions.scroll <= dimensions.client + 2, `${viewport.name} overflow: ${JSON.stringify(dimensions)}`);

      if (viewport.name === "desktop-1440") {
        const typeFilter = page.getByLabel("事件类型");
        await typeFilter.selectOption("ANNOUNCEMENT");
        await page.locator('[data-testid="research-event-row"][data-event-type="ANNOUNCEMENT"]').first().waitFor();
        assert.equal(await page.locator('[data-testid="research-event-row"][data-event-type="PERIODIC_REPORT"]').count(), 0);
        const announcement = page.locator('[data-testid="research-event-row"][data-event-type="ANNOUNCEMENT"]').first();
        await announcement.getByText("来源与限制").click();
        await announcement.getByText("DATE_ONLY", { exact: false }).waitFor();
        await typeFilter.selectOption("ALL");
        await page.locator('[data-testid="research-event-row"][data-event-type="PERIODIC_REPORT"]').first().waitFor();
        const contextLink = page.getByTestId("research-event-context-link").first();
        await contextLink.click();
        await page.waitForURL(/\/decision-inbox#campaign-/);
        assert.match(page.url(), /#campaign-/);
        await page.goBack({ waitUntil: "domcontentloaded" });
        await page.getByTestId("research-event-calendar").waitFor();
      }
      await page.screenshot({ path: path.join(screenshotDir, `${viewport.name}.png`), fullPage: true });
      await context.close();
    }
    assert.deepEqual(forbiddenMutations, [], `read-only calendar issued mutation: ${forbiddenMutations.join(" | ")}`);
    const readme = [
      "# PLANNING-PARITY-EVENT-CALENDAR1 browser evidence", "",
      `Generated: ${new Date().toISOString()}`,
      "Browser plugin: not available; regular Playwright Chromium used.",
      "Backend: real FastAPI process and real `/api/research-events` route.",
      "Provider fixtures: existing Decision Calendar / StockData adapter boundaries only; core aggregation was not HTTP/page-mocked.", "",
      "## Checks", "- 2 active securities / 3 Campaigns with same-security dedup", "- EXPECTED + CONFIRMED periodic reports", "- upcoming lockup + historical dividend + recent announcement", "- one source/security failure retained as PARTIAL", "- Decision Inbox → Event Calendar → type filter → details → Campaign context → back", "- desktop 1440x900 and narrow 390x844", "- no document overflow, pageerror, console error, or API mutation", "", `API envelope: ${JSON.stringify(apiBodies)}`, `Errors: ${errors.length ? errors.join(" | ") : "none"}`, "", `Screenshots: ${path.join(screenshotDir, "desktop-1440.png")}, ${path.join(screenshotDir, "narrow-390.png")}`, "",
    ].join("\n");
    await writeFile(path.join(screenshotDir, "README.md"), readme, "utf8");
    assert.deepEqual(errors, [], errors.join("\n"));
    console.log(`Research Event Calendar browser vertical OK; screenshots=${screenshotDir}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve)).catch(() => {});
    if (backend.pid) {
      if (process.platform === "win32") spawn("taskkill", ["/pid", String(backend.pid), "/t", "/f"], { stdio: "ignore" });
      else backend.kill("SIGKILL");
    }
    await Promise.all([
      rm(dataDir, { recursive: true, force: true }),
      rm(reportsDir, { recursive: true, force: true }),
    ]);
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
