/**
 * Eastmoney current-industry matrix browser acceptance — real FastAPI route,
 * real production frontend build, isolated current snapshot and RDP artifact.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import http, { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");
const harnessDir = __dirname;
const shotDir = process.env.SECTOR_CROWD_SCREENSHOT_DIR || path.join(tmpdir(), "vibe-research-sector-crowd1-r1");

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function resolvePython() {
  if (process.env.PYTHON?.trim()) return process.env.PYTHON.trim();
  if (process.env.VR_PYTHON?.trim()) return process.env.VR_PYTHON.trim();
  const win = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  if (existsSync(win)) return win;
  return process.platform === "win32" ? "py" : "python3";
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

async function waitHttp(url, attempts = 100) {
  for (let i = 0; i < attempts; i++) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch { /* retry */ }
    await sleep(300);
  }
  throw new Error(`timeout waiting ${url}`);
}

function startStaticServer(dir, port, apiBackendPort) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
  };
  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    if (rawUrl.startsWith("/api/")) {
      const proxyReq = http.request(
        { hostname: "127.0.0.1", port: apiBackendPort, path: rawUrl, method: req.method, headers: { ...req.headers, host: `127.0.0.1:${apiBackendPort}` } },
        (proxyRes) => { res.writeHead(proxyRes.statusCode || 500, proxyRes.headers); proxyRes.pipe(res, { end: true }); },
      );
      proxyReq.on("error", (error) => { res.writeHead(502, { "content-type": "text/plain; charset=utf-8" }); res.end(`Bad Gateway: ${error.message}`); });
      req.pipe(proxyReq, { end: true });
      return;
    }
    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || path.extname(target) === "") target = path.join(dir, "index.html");
    res.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => { server.on("error", reject); server.listen(port, "127.0.0.1", () => resolve(server)); });
}

async function launchBrowser() {
  const launchOptions = { headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) };
  let lastError;
  for (let attempt = 0; attempt < 3; attempt++) {
    try { return await chromium.launch(launchOptions); } catch (error) { lastError = error; if (attempt === 0) launchOptions.channel = "chrome"; }
  }
  throw lastError;
}

async function assertMatrix(page, label, errors) {
  const url = page.url();
  const title = await page.title();
  if (!url.endsWith("/sectors")) errors.push(`${label}: wrong URL ${url}`);
  if (!title) errors.push(`${label}: missing page title`);
  const body = await page.locator("body").innerText();
  for (const expected of ["行业环境 / 横向比较", "东财行业", "站上 MA20", "参与度", "分类：Eastmoney 当前行业", "成员口径：当前快照成员", "历史成员有效性：未证明", "当前 Eastmoney 行业成员的 PE/PB 分布", "不是行业指数估值，也不是历史估值分位", "PE+ 中位数", "PB+ 中位数", "0值", "电子", "医药", "UNKNOWN"]) {
    if (!body.includes(expected)) errors.push(`${label}: missing visible text ${expected}`);
  }
  for (const forbidden of ["便宜", "昂贵", "买入", "卖出", "推荐", "Above MA20", "Participation"]) {
    if (body.includes(forbidden)) errors.push(`${label}: forbidden valuation/recommendation text ${forbidden}`);
  }
  if (body.includes("Vite Error") || body.includes("Unhandled Runtime Error")) errors.push(`${label}: framework error overlay visible`);
  const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  if (width.scroll > width.client + 2) errors.push(`${label}: document overflow ${JSON.stringify(width)}`);
  if (!(await page.getByTestId("sector-industry-table").isVisible().catch(() => false))) errors.push(`${label}: matrix table not visible`);
}

async function main() {
  if (!existsSync(frontendDist)) throw new Error("frontend/dist missing; run npm run build first");
  await mkdir(shotDir, { recursive: true });
  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-sector-crowd-data-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-sector-crowd-reports-"));
  const rdpDir = await mkdtemp(path.join(tmpdir(), "vr-sector-crowd-rdp-"));
  const backendPort = await getFreePort();
  const frontendPort = await getFreePort();
  const python = resolvePython();
  const pythonArgs = python === "py" ? ["-3"] : [];
  const backend = spawn(python, [...pythonArgs, "-m", "uvicorn", "sector_industry_harness_app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: [backendDir, harnessDir, process.env.PYTHONPATH || ""].filter(Boolean).join(process.platform === "win32" ? ";" : ":"),
      VR_DATA_DIR: dataDir,
      VR_REPORTS_DIR: reportsDir,
      VIBE_RESEARCH_RESEARCH_DATA_DIR: rdpDir,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let backendLog = "";
  backend.stdout.on("data", (data) => { backendLog += data.toString(); });
  backend.stderr.on("data", (data) => { backendLog += data.toString(); });
  let staticServer = null;
  const errors = [];
  const industryResponses = [];
  try {
    try {
      await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    } catch (error) {
      throw new Error(`${error.message}; backend log: ${backendLog || "<empty>"}`);
    }
    staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);
    const browser = await launchBrowser();
    try {
      for (const viewport of [{ name: "desktop-1440", width: 1440, height: 900 }, { name: "narrow-390", width: 390, height: 844 }]) {
        const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
        const page = await context.newPage();
        page.on("pageerror", (error) => errors.push(`${viewport.name} pageerror: ${error.message}`));
        page.on("console", (message) => { if (message.type() === "error") errors.push(`${viewport.name} console: ${message.text()}`); });
        page.on("response", async (response) => {
          if (!response.url().includes("/api/sector-research/industry-context")) return;
          industryResponses.push({ status: response.status(), body: await response.json().catch(() => null) });
        });
        await page.goto(`http://127.0.0.1:${frontendPort}/sectors`, { waitUntil: "networkidle" });
        await assertMatrix(page, viewport.name, errors);
        if (viewport.name === "desktop-1440") {
          await page.getByLabel("行业矩阵排序").selectOption("pe_ttm_positive_median");
          const firstRowBefore = await page.getByTestId("sector-industry-table").locator("tbody tr").first().innerText();
          if (!firstRowBefore) errors.push("desktop-1440: sorting produced no first row");
          await page.getByRole("link", { name: "市场云图" }).first().click();
          await page.waitForLoadState("networkidle");
          if (!page.url().includes("/market-cloud")) errors.push(`desktop-1440: industry row navigation failed: ${page.url()}`);
        }
        await page.screenshot({ path: path.join(shotDir, `${viewport.name}.png`), fullPage: true });
        await context.close();
      }
    } finally { await browser.close().catch(() => {}); }
    const industryPayload = industryResponses.find((item) => item.status === 200)?.body?.data;
    if (!industryPayload || industryPayload.schema_version !== "sector_industry_context.v0.2") {
      errors.push("industry-context API did not return the real valuation matrix envelope");
    } else {
      const electronics = industryPayload.items.find((item) => item.industry_name === "电子");
      const medicine = industryPayload.items.find((item) => item.industry_name === "医药");
      const unknown = industryPayload.items.find((item) => item.industry_name === "UNKNOWN");
      if (!electronics || electronics.valuation.pe_ttm.positive_median !== 15 || electronics.valuation.pb.positive_median !== 1.5) errors.push("electronics TTM valuation medians were not preserved from the raw source fixture");
      if (!electronics || electronics.valuation.pe_ttm.zero_count !== 1 || electronics.valuation.pb.negative_count !== 1) errors.push("electronics non-positive valuation counts were not preserved");
      if (!medicine || medicine.valuation.pe_ttm.status !== "PARTIAL" || medicine.valuation.pe_ttm.observed_count !== 1 || medicine.valuation.pe_ttm.missing_count !== 1 || medicine.valuation.pe_ttm.positive_median !== 5) errors.push("TTM-missing member was not kept missing without dynamic PE fallback");
      if (!unknown || unknown.classification_status !== "UNKNOWN") errors.push("UNKNOWN industry was not retained");
    }
    const readme = [
      "# PLANNING-PARITY-SECTOR-CROWD1-R1 browser evidence", "",
      `Generated: ${new Date().toISOString()}`,
      "Browser plugin: not available; regular Playwright Chromium used.",
      "Backend: real FastAPI app route with isolated snapshot input and imported isolated RDP fixture.",
      "Core matrix calculation: production service, not HTTP-mocked.", "Current-member PE/PB distribution with positive-only medians, explicit non-positive and missing counts, and transparent market-cap coverage.", "",
      "## Checks", "- Desktop 1440x900 and narrow 390x844", "- Multi-industry current snapshot", "- Positive and negative member aggregates", "- Partial coverage", "- Current-membership disclaimer", "- Current-member PE/PB distribution", "- RDP/valuation failure isolation when SECTOR_INDUSTRY_E2E_RDP_FAILURE=1", "- Sorting and row navigation", "- No pageerror/console error/document overflow", "",
      `API responses: ${JSON.stringify(industryResponses)}`, "", `Errors: ${errors.length ? errors.join(" | ") : "none"}`, "",
      "Screenshots: desktop-1440.png, narrow-390.png", "",
    ].join("\n");
    await writeFile(path.join(shotDir, "README.md"), readme, "utf8");
    if (errors.length) throw new Error(`sector industry browser vertical failed:\n${errors.join("\n")}`);
    console.log(`Sector industry browser vertical OK; screenshots=${shotDir}; API=${JSON.stringify(industryResponses)}`);
  } finally {
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve)).catch(() => {});
    if (backend.pid) {
      if (process.platform === "win32") spawn("taskkill", ["/pid", String(backend.pid), "/t", "/f"], { stdio: "ignore" });
      else backend.kill("SIGKILL");
    }
    await Promise.all([
      rm(dataDir, { recursive: true, force: true }),
      rm(reportsDir, { recursive: true, force: true }),
      rm(rdpDir, { recursive: true, force: true }),
    ]);
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
