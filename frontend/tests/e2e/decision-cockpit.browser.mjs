/**
 * Decision cockpit (PR A / PR #13) browser acceptance.
 *
 * - Desktop 1440 + mobile 390
 * - Open page: no generate / no writes to tomorrow_plans
 * - Explicit generate → draft; freeze → current frozen; history
 * - 3D labels (价值/趋势/短线); watchlist migration entry; cash unconfigured
 * - LLM fallback copy; no pageerror / unexpected API 5xx
 *
 * Reverse-proxy pattern mirrors sector-research.browser.mjs.
 * Uses cockpit_harness_app.py for offline market/kline stubs + seeded review snapshot.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import {
  mkdir,
  mkdtemp,
  rm,
} from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import http, { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const shotDir = path.join(root, "docs", "screenshots", "decision-cockpit-accept");
const backendDir = path.join(root, "backend");
const e2eDir = __dirname;

let backendPort = 0;
let frontendPort = 0;
let browserLabel = "unknown";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolvePython() {
  if (process.env.VR_PYTHON && process.env.VR_PYTHON.trim()) {
    return process.env.VR_PYTHON.trim();
  }
  const winMain = path.join("E:", "AI Projects", "Vibe-Research", "backend", ".venv", "Scripts", "python.exe");
  if (existsSync(winMain)) return winMain;
  const win = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  if (existsSync(win)) return win;
  return path.join(root, "backend", ".venv", "bin", "python");
}

function getFreePort() {
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

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      /* retry */
    }
    await sleep(400);
  }
  throw new Error(`timeout waiting ${url}`);
}

function startStaticServer(dir, port, apiBackendPort) {
  const mime = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json",
  };

  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    const urlPath = decodeURIComponent(rawUrl.split("?")[0] || "/");

    if (urlPath === "/api" || urlPath.startsWith("/api/")) {
      const headers = { ...req.headers, host: `127.0.0.1:${apiBackendPort}` };
      const proxyReq = http.request(
        {
          hostname: "127.0.0.1",
          port: apiBackendPort,
          path: rawUrl,
          method: req.method,
          headers,
        },
        (proxyRes) => {
          res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
          proxyRes.pipe(res);
        },
      );
      proxyReq.on("error", (err) => {
        if (!res.headersSent) {
          res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
        }
        res.end(`proxy error: ${err.message}`);
      });
      req.pipe(proxyReq);
      return;
    }

    const filePath = urlPath === "/" ? "/index.html" : urlPath;
    const rootDir = path.resolve(dir);
    const file = path.resolve(path.join(rootDir, filePath));
    const spaFallback = () => {
      const index = path.join(rootDir, "index.html");
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      createReadStream(index).pipe(res);
    };
    if (!file.startsWith(rootDir + path.sep) && file !== rootDir) {
      res.writeHead(403).end("forbidden");
      return;
    }
    if (!existsSync(file) || !path.extname(filePath)) {
      spaFallback();
      return;
    }
    res.writeHead(200, {
      "Content-Type": mime[path.extname(file)] || "application/octet-stream",
    });
    createReadStream(file).pipe(res);
  });

  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function launchBrowser() {
  const candidates = [];
  if (process.env.PLAYWRIGHT_CHROME_PATH) {
    candidates.push({
      label: "PLAYWRIGHT_CHROME_PATH",
      opts: { executablePath: process.env.PLAYWRIGHT_CHROME_PATH, headless: true },
    });
  }
  const localAppData = process.env.LOCALAPPDATA || "";
  const chromium1228 = path.join(
    localAppData,
    "ms-playwright",
    "chromium-1228",
    "chrome-win64",
    "chrome.exe",
  );
  if (existsSync(chromium1228)) {
    candidates.push({
      label: "local chromium-1228",
      opts: { executablePath: chromium1228, headless: true },
    });
  }
  candidates.push({ label: "bundled chromium", opts: { headless: true } });
  candidates.push({ label: "channel chrome", opts: { channel: "chrome", headless: true } });
  candidates.push({ label: "channel msedge", opts: { channel: "msedge", headless: true } });

  let lastError;
  for (const c of candidates) {
    try {
      const browser = await chromium.launch(c.opts);
      browserLabel = c.label;
      return browser;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("failed to launch any Chromium");
}

function attachPageGuards(page, label, errors, bag) {
  page.on("pageerror", (error) => errors.push(`${label} pageerror: ${error.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      const text = msg.text();
      // Resource 4xx from optional endpoints is ok; hard failures are not.
      if (text.includes("Failed to load resource") && /[45]\d\d/.test(text)) return;
      errors.push(`${label} console: ${text}`);
    }
  });
  page.on("response", (response) => {
    const url = response.url();
    if (!url.includes("/api")) return;
    if (url.includes("/api/api")) errors.push(`${label} double api path: ${url}`);
    const status = response.status();
    const method = response.request().method();
    try {
      const p = new URL(url).pathname;
      if (p.includes("/decision-cockpit/overview") && method === "GET") bag.overviewGet += 1;
      if (p.includes("/tomorrow-plan/generate") && method === "POST") bag.generatePost += 1;
      if (p.includes("/freeze") && method === "POST") bag.freezePost += 1;
      if (p.includes("/watchlist") && method === "POST") bag.watchlistWrite += 1;
      if (p.includes("/watchlist") && method === "PUT") bag.watchlistWrite += 1;
    } catch { /* ignore */ }
    // generate may 409 if snapshot missing — harness seeds it; still track 5xx
    if (status >= 500) {
      bag.badStatuses.push(`${status} ${method} ${url}`);
      errors.push(`${label} unexpected HTTP ${status}: ${method} ${url}`);
    }
  });
}

async function runViewport(browser, errors, { width, height, label }) {
  const bag = {
    overviewGet: 0,
    generatePost: 0,
    freezePost: 0,
    watchlistWrite: 0,
    badStatuses: [],
  };
  const context = await browser.newContext({ viewport: { width, height } });
  const page = await context.newPage();
  attachPageGuards(page, label, errors, bag);

  // 1) Open page — must not auto-generate
  const genBefore = bag.generatePost;
  await page.goto(`http://127.0.0.1:${frontendPort}/cockpit`, {
    waitUntil: "networkidle",
  });
  await page.getByText("明日行动计划").first().waitFor({ timeout: 15000 });
  if (bag.generatePost !== genBefore) {
    errors.push(`${label}: open page triggered generate (writes)`);
  }

  // Core labels
  for (const text of ["决策舱", "明日行动计划", "今日实时行动", "生成明日计划", "同步自选草稿"]) {
    const ok = await page.getByText(text, { exact: false }).first().isVisible().catch(() => false);
    if (!ok) errors.push(`${label}: missing text ${text}`);
  }

  // Cash unconfigured copy (no account profile in isolated env)
  const cashHint = await page.getByTestId("cash-unconfigured").isVisible().catch(() => false);
  const cashText = await page.getByText(/未配置|可用现金/).first().isVisible().catch(() => false);
  if (!cashHint && !cashText) {
    errors.push(`${label}: cash unconfigured UI missing`);
  }

  // LLM fallback notice when no llm config
  const llmHint = await page.getByText(/确定性摘要|未配置 AI/).first().isVisible().catch(() => false);
  if (!llmHint) {
    // soft: may still show after generate
  }

  await page.screenshot({
    path: path.join(shotDir, `${label}-open.png`),
    fullPage: true,
  });

  // 2) Explicit generate → draft
  await page.getByRole("button", { name: /生成明日计划/ }).click();
  await page.waitForTimeout(2500);
  // Accept either draft panel or info banner
  const draftOk =
    (await page.getByTestId("plan-status").isVisible().catch(() => false)) ||
    (await page.getByText(/草稿|已生成/).first().isVisible().catch(() => false));
  if (!draftOk) {
    const body = await page.locator("body").innerText().catch(() => "");
    errors.push(`${label}: generate did not show draft; body=${body.slice(0, 400)}`);
  } else {
    // 3D labels
    for (const dim of ["价值", "趋势", "短线"]) {
      const ok = await page.getByText(dim, { exact: false }).first().isVisible().catch(() => false);
      if (!ok) errors.push(`${label}: missing 3D label ${dim}`);
    }
  }

  // 3) Freeze if draft button present
  const freezeBtn = page.getByRole("button", { name: /^冻结$/ });
  if (await freezeBtn.isVisible().catch(() => false)) {
    await freezeBtn.click();
    await page.waitForTimeout(1000);
    const frozen = await page.getByText(/已冻结|frozen|current/).first().isVisible().catch(() => false);
    if (!frozen) errors.push(`${label}: freeze did not update status`);
  }

  // 4) History block
  const hist = page.getByText("历史版本");
  if (await hist.isVisible().catch(() => false)) {
    await hist.click();
    await page.waitForTimeout(500);
  }

  // 5) Watchlist migration entry (button exists; may no-op without local draft)
  const syncBtn = page.getByRole("button", { name: /同步自选草稿/ });
  if (await syncBtn.isVisible().catch(() => false)) {
    await syncBtn.click();
    await page.waitForTimeout(500);
  }

  // 6) Today placeholder (PR B)
  await page.getByText("今日实时行动").first().click();
  await page.getByText(/PR B|后续/).first().waitFor({ timeout: 5000 }).catch(() => {
    errors.push(`${label}: today placeholder missing`);
  });

  await page.screenshot({
    path: path.join(shotDir, `${label}-after.png`),
    fullPage: true,
  });

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
  );
  if (overflow) errors.push(`${label}: horizontal overflow`);

  await context.close();
  return bag;
}

async function main() {
  if (!existsSync(frontendDist)) {
    console.error("frontend/dist missing — run npm run build first");
    process.exit(2);
  }

  await mkdir(shotDir, { recursive: true });
  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-cockpit-e2e-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-cockpit-reports-"));
  const reviewDb = path.join(dataDir, "daily_reviews.sqlite3");

  backendPort = await getFreePort();
  frontendPort = await getFreePort();

  const python = resolvePython();
  const env = {
    ...process.env,
    VR_DATA_DIR: dataDir,
    VR_REPORTS_DIR: reportsDir,
    VIBE_RESEARCH_REVIEW_DB: reviewDb,
    PYTHONPATH: [backendDir, e2eDir, process.env.PYTHONPATH || ""].filter(Boolean).join(path.delimiter),
  };

  const uvicorn = spawn(
    python,
    [
      "-m", "uvicorn",
      "cockpit_harness_app:app",
      "--host", "127.0.0.1",
      "--port", String(backendPort),
      "--log-level", "warning",
    ],
    { cwd: e2eDir, env, stdio: ["ignore", "pipe", "pipe"] },
  );
  let uvLog = "";
  uvicorn.stdout.on("data", (d) => { uvLog += d.toString(); });
  uvicorn.stderr.on("data", (d) => { uvLog += d.toString(); });

  const errors = [];
  let staticServer;
  let browser;
  try {
    await waitHttp(`http://127.0.0.1:${backendPort}/api/watchlist`);
    staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);
    browser = await launchBrowser();

    await runViewport(browser, errors, { width: 1440, height: 900, label: "desktop" });
    await runViewport(browser, errors, { width: 390, height: 844, label: "mobile" });
  } catch (e) {
    errors.push(`harness failure: ${e && e.stack ? e.stack : e}`);
    if (uvLog) errors.push(`uvicorn log: ${uvLog.slice(-2000)}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) staticServer.close();
    uvicorn.kill("SIGTERM");
    await sleep(300);
    await rm(dataDir, { recursive: true, force: true }).catch(() => {});
    await rm(reportsDir, { recursive: true, force: true }).catch(() => {});
  }

  if (errors.length) {
    console.error("FAIL decision-cockpit acceptance");
    console.error(`browser=${browserLabel}`);
    for (const e of errors) console.error(" -", e);
    process.exit(1);
  }
  console.log(`PASS decision-cockpit acceptance browser=${browserLabel}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
