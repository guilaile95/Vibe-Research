/**
 * PLANNING-PARITY-PATTERN-DISCOVERY1 source-to-sink browser vertical.
 *
 * The fixture is imported through the existing RDP CSV importer. The browser
 * talks to a real FastAPI process and the production Vite build; the duplicate
 * scenario rewrites only a temporary Parquet artifact and manifest so the
 * runtime identity guard, rather than the importer duplicate check, is tested.
 */
import { chromium } from "playwright";
import { createReadStream, existsSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = path.join(root, "backend");
const frontendDist = path.join(root, "frontend", "dist");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolvePython() {
  if (process.env.VR_E2E_PYTHON?.trim()) return { command: process.env.VR_E2E_PYTHON.trim(), prefix: [] };
  const win = path.join(backendDir, ".venv", "Scripts", "python.exe");
  const lin = path.join(backendDir, ".venv", "bin", "python");
  if (existsSync(win)) return { command: win, prefix: [] };
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

async function waitHttp(url, attempts = 100) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return response;
    } catch {
      // FastAPI may still be starting.
    }
    await sleep(300);
  }
  throw new Error(`timeout waiting for ${url}`);
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

async function startStaticServer(dir, port, backendPort) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
  };
  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    if (rawUrl.startsWith("/api/")) {
      req.pipe(createServerProxyRequest(req, res, backendPort), { end: true });
      return;
    }
    const resolvedDir = path.resolve(dir);
    let target = path.join(dir, rawUrl.split("?")[0] === "/" ? "index.html" : rawUrl.split("?")[0]);
    let resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep)) {
      res.writeHead(403);
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || path.extname(target) === "") target = path.join(dir, "index.html");
    resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep)) {
      res.writeHead(403);
      res.end("forbidden");
      return;
    }
    res.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  return server;
}

async function startBackend(rdpRoot, tempDir) {
  const port = await getFreePort();
  const python = resolvePython();
  const child = spawn(python.command, [...python.prefix, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: backendDir,
    env: {
      ...process.env,
      PYTHONPATH: backendDir,
      VR_DATA_DIR: tempDir,
      VR_REPORTS_DIR: path.join(tempDir, "reports"),
      VIBE_RESEARCH_RESEARCH_DATA_DIR: rdpRoot,
      VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: "1",
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
  if (process.platform === "win32") await runProcess("taskkill", ["/pid", String(child.pid), "/t", "/f"]).catch(() => {});
  else child.kill("SIGTERM");
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 5000);
    child.once("exit", () => { clearTimeout(timer); resolve(); });
  });
}

async function seedFixture() {
  const tempDir = await mkdtemp(path.join(tmpdir(), "vr-pattern-e2e-"));
  const csv = path.join(tempDir, "patterns.csv");
  const rdpRoot = path.join(tempDir, "research-data-plane");
  const lines = ["code,trade_date,open,high,low,close,volume"];
  const start = Date.UTC(2026, 0, 1);
  for (const [code, kind] of [["000001", "up"], ["000002", "down"], ["000003", "flat"], ["000004", "exact-volume"], ["000005", "above-volume"]]) {
    for (let index = 0; index < 66; index += 1) {
      const tradeDate = new Date(start + index * 86400000).toISOString().slice(0, 10);
      const close = kind === "up" && index === 65 ? 20 : kind === "down" && index === 65 ? 1 : 10;
      const volume = index === 65 && kind === "exact-volume" ? 11000
        : index === 65 && kind === "above-volume" ? 11001
          : index === 65 && (kind === "up" || kind === "down") ? 100000
            : 1000;
      lines.push(`${code},${tradeDate},${close},${close + 0.5},${Math.max(0.1, close - 0.5)},${close},${volume}`);
    }
  }
  for (let index = 0; index < 10; index += 1) {
    const tradeDate = new Date(start + index * 86400000).toISOString().slice(0, 10);
    lines.push(`600519,${tradeDate},12,12.5,11.5,12,300`);
  }
  await writeFile(csv, `${lines.join("\n")}\n`, "utf8");
  const python = resolvePython();
  await runProcess(python.command, [...python.prefix, "-m", "research_data_plane", "import-csv", csv, "--root", rdpRoot], {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: backendDir },
  });
  return { tempDir, rdpRoot, manifest: JSON.parse(await readFile(path.join(rdpRoot, "manifest.json"), "utf8")) };
}

async function makeDuplicateArtifact(fixture) {
  const python = resolvePython();
  const script = [
    "import hashlib, json, os, sys, duckdb",
    "from pathlib import Path",
    "root=Path(sys.argv[1]); manifest_path=root/'manifest.json'; manifest=json.loads(manifest_path.read_text(encoding='utf-8'))",
    "old=root/'artifacts'/manifest['artifact_file']; temp=root/'artifacts'/'overlap-temp.parquet'",
    "con=duckdb.connect(database=':memory:')",
    "con.execute(\"CREATE TEMP TABLE duplicated AS WITH source AS (SELECT * FROM read_parquet(?)) SELECT * FROM source UNION ALL SELECT * FROM (SELECT * FROM source LIMIT 1)\", [str(old)])",
    "con.execute(\"COPY duplicated TO ? (FORMAT PARQUET, COMPRESSION ZSTD)\", [str(temp)])",
    "con.close(); digest=hashlib.sha256(temp.read_bytes()).hexdigest(); target=root/'artifacts'/f'{digest}.parquet'; os.replace(temp, target); old.unlink(missing_ok=True)",
    "manifest['artifact_sha256']=digest; manifest['artifact_file']=target.name; manifest['row_count'] += 1; manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\\n', encoding='utf-8')",
  ].join(";");
  await runProcess(python.command, [...python.prefix, "-c", script, fixture.rdpRoot], {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: backendDir },
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
  const metrics = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  if (metrics.documentWidth > metrics.innerWidth + 1 || metrics.bodyWidth > metrics.innerWidth + 1) {
    throw new Error(`${label} horizontal overflow: ${JSON.stringify(metrics)}`);
  }
}

async function runNormalScenario(browser, fixture, screenshotDir) {
  const backend = await startBackend(fixture.rdpRoot, fixture.tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port);
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const apiRequests = [];
  const consoleErrors = [];
  await page.route("https://fonts.googleapis.com/**", (route) => route.fulfill({ contentType: "text/css", body: "" }));
  page.on("request", (request) => { if (request.url().includes("/api/")) apiRequests.push(request.url()); });
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  try {
    const baseUrl = `http://127.0.0.1:${frontendPort}`;
    await page.goto(`${baseUrl}/screener`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("pattern-discovery-tab").click();
    await page.getByTestId("pattern-form").waitFor({ state: "visible" });
    const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/research-data/patterns");
    await page.getByTestId("run-patterns").click();
    const response = await responsePromise;
    const payload = await response.json();
    if (response.status() !== 200 || payload.schema_version !== "research-data-plane.patterns.v0.1") throw new Error(`unexpected Pattern response: ${JSON.stringify(payload)}`);
    if (payload.status !== "partial" || payload.total_events !== 7 || payload.matched_stock_count !== 3 || payload.not_evaluable_count !== 5) {
      throw new Error(`unexpected Pattern counts: ${JSON.stringify(payload)}`);
    }
    if (payload.events.some((event) => !["close_above_20d_high", "close_below_20d_low", "sma20_cross_above_sma60", "sma20_cross_below_sma60", "volume_surge"].includes(event.event_type))) {
      throw new Error("Pattern response contained an event outside the five-event registry");
    }
    if (payload.events.some((event) => event.code === "000004" && event.event_type === "volume_surge")) {
      throw new Error("exact volume ratio 2.0 incorrectly rendered as volume_surge");
    }
    const aboveBoundary = payload.events.find((event) => event.code === "000005" && event.event_type === "volume_surge");
    if (!aboveBoundary || Number(aboveBoundary.evidence?.volume_ratio_5_20) <= 2.0) {
      throw new Error(`volume ratio above 2.0 did not render as volume_surge: ${JSON.stringify(payload.events)}`);
    }
    if (apiRequests.filter((url) => url.includes("/api/research-data/patterns")).length !== 1) throw new Error("expected one Pattern request");
    if (apiRequests.some((url) => url.includes("/api/kline") || url.includes("/api/screener/evaluate"))) throw new Error("Pattern scan emitted a per-security request");
    const summary = await page.getByTestId("pattern-summary").innerText();
    for (const expected of ["部分可评估", "不可评估（不是未触发）", "600519", "INSUFFICIENT_HISTORY", "命中股票 3"]) {
      if (!summary.includes(expected)) throw new Error(`Pattern summary missing ${expected}: ${summary}`);
    }
    if (await page.getByTestId("pattern-results").getByRole("link", { name: "000001" }).count() !== 3) throw new Error("same-stock multiple events were compressed");
    if (await page.getByTestId("pattern-results").getByRole("link", { name: "000004" }).count() !== 0) throw new Error("exact 2.0 boundary rendered a result link");
    if (await page.getByTestId("pattern-results").getByRole("link", { name: "000005" }).count() !== 1) throw new Error("above 2.0 boundary did not render one result link");
    await page.screenshot({ path: path.join(screenshotDir, "pattern-normal-desktop.png"), fullPage: true });
    await assertNoOverflow(page, "desktop Pattern page");

    await page.getByLabel("使用最新 artifact 日期", { exact: true }).uncheck();
    await page.getByLabel("Pattern as of", { exact: true }).fill("2026-03-06");
    const historicalResponsePromise = page.waitForResponse((item) => new URL(item.url()).pathname === "/api/research-data/patterns");
    await page.getByTestId("run-patterns").click();
    const historicalResponse = await historicalResponsePromise;
    const historical = await historicalResponse.json();
    const historicalUrl = new URL(historicalResponse.url());
    if (historicalUrl.searchParams.get("latest") !== "false" || historicalUrl.searchParams.get("as_of") !== "2026-03-06") throw new Error("Pattern historical cutoff was not submitted");
    if (historical.events.length !== 0 || historical.events.some((event) => event.trade_date > "2026-03-06")) throw new Error("Pattern historical query read future rows");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId("pattern-summary").waitFor({ state: "visible" });
    await page.screenshot({ path: path.join(screenshotDir, "pattern-historical-narrow.png"), fullPage: true });
    await assertNoOverflow(page, "narrow Pattern page");
    if (consoleErrors.length) throw new Error(`browser console errors: ${consoleErrors.join(" | ")}`);
    console.log(`[E2E] Pattern normal status=${payload.status} events=${payload.total_events} not_evaluable=${payload.not_evaluable_count}; desktop+narrow OK`);
  } finally {
    await page.close().catch(() => {});
    await new Promise((resolve) => staticServer.close(resolve));
    await stopProcess(backend.child);
  }
}

async function runOverlapScenario(browser, fixture, screenshotDir) {
  const backend = await startBackend(fixture.rdpRoot, fixture.tempDir);
  const frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort, backend.port);
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  await page.route("https://fonts.googleapis.com/**", (route) => route.fulfill({ contentType: "text/css", body: "" }));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  try {
    const baseUrl = `http://127.0.0.1:${frontendPort}`;
    await page.goto(`${baseUrl}/screener`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("pattern-discovery-tab").click();
    const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/research-data/patterns");
    await page.getByTestId("run-patterns").click();
    const response = await responsePromise;
    const payload = await response.json();
    if (response.status() !== 200 || payload.status !== "unavailable" || payload.events.length !== 0 || !payload.limitations.join(" ").includes("PATTERN_SOURCE_DUPLICATE_OR_INVALID_OBSERVATION_IDENTITY")) {
      throw new Error(`overlap was not fail-closed: ${JSON.stringify(payload)}`);
    }
    const summary = await page.getByTestId("pattern-summary").innerText();
    if (!summary.includes("不可用") || !summary.includes("PATTERN_SOURCE_DUPLICATE_OR_INVALID_OBSERVATION_IDENTITY")) throw new Error(`overlap limitation not visible: ${summary}`);
    if (await page.getByTestId("pattern-results").getByRole("link").count()) throw new Error("overlap rendered matched result links");
    await page.screenshot({ path: path.join(screenshotDir, "pattern-overlap-unavailable.png"), fullPage: true });
    await assertNoOverflow(page, "overlap Pattern page");
    await page.setViewportSize({ width: 390, height: 844 });
    await assertNoOverflow(page, "narrow overlap Pattern page");
    if (consoleErrors.length) throw new Error(`overlap browser console errors: ${consoleErrors.join(" | ")}`);
    console.log("[E2E] Pattern duplicate identity -> unavailable, no complete result links OK");
  } finally {
    await page.close().catch(() => {});
    await new Promise((resolve) => staticServer.close(resolve));
    await stopProcess(backend.child);
  }
}

async function main() {
  if (!existsSync(frontendDist)) throw new Error(`Frontend dist missing: ${frontendDist}; run npm run build first`);
  const screenshotDir = process.env.E2E_SCREENSHOT_DIR || await mkdtemp(path.join(tmpdir(), "vr-pattern-screenshots-"));
  const ownsScreenshotDir = !process.env.E2E_SCREENSHOT_DIR;
  const normal = await seedFixture();
  const overlap = await seedFixture();
  await makeDuplicateArtifact(overlap);
  const { browser, label } = await launchBrowser();
  try {
    console.log(`[E2E] browser=${label}`);
    await runNormalScenario(browser, normal, screenshotDir);
    await runOverlapScenario(browser, overlap, screenshotDir);
    console.log(`[E2E] Pattern source-to-sink browser vertical OK; screenshots=${screenshotDir}`);
  } finally {
    await browser.close().catch(() => {});
    await rm(normal.tempDir, { recursive: true, force: true });
    await rm(overlap.tempDir, { recursive: true, force: true });
    if (ownsScreenshotDir) await rm(screenshotDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error("[E2E] FAILED", error);
  process.exitCode = 1;
});
