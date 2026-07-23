/**
 * Sector research browser acceptance — REAL integration.
 *
 * Architecture:
 * - Playwright loads the Vite build from a Node static server
 * - Static server reverse-proxies /api/* to an isolated FastAPI process
 * - FastAPI is uvicorn harness_app:app loaded via PYTHONPATH
 *   (backend + frontend/tests/e2e); no copy into backend/, no worktree delete
 * - harness monkeypatches only external IO (discover / dynamic / PDF download)
 *   and directed cache miss for external_id ERR
 * - VR_DATA_DIR and VR_REPORTS_DIR are mkdtemp-isolated
 * - NO page.route for application APIs; NO production E2E endpoints
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import {
  mkdir,
  writeFile,
  mkdtemp,
  rm,
  readFile,
} from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import http, { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const shotDir = path.join(root, "docs", "screenshots", "sector-research-accept");
const harnessSrc = path.join(__dirname, "harness_app.py");
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

    // Reverse-proxy application APIs to isolated FastAPI (pipe request body).
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
    // Only serve real files with extensions; SPA client routes fall back to index.html
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

function createNetworkBag(errors, label) {
  const bag = {
    dataPcb: 0,
    reportsPcb: 0,
    importPost: 0,
    myreportsGet: 0,
    myreportsPatch: 0,
    badStatuses: [],
  };

  function onResponse(response) {
    const url = response.url();
    if (!url.includes("/api")) return;
    if (url.includes("/api/api")) {
      errors.push(`${label} double api path: ${url}`);
    }
    const status = response.status();
    // Intentional client errors (e.g. expired import 400) are allowed; hard failures are not.
    if (status === 404 || status === 422 || status >= 500) {
      bag.badStatuses.push(`${status} ${url}`);
      errors.push(`${label} unexpected HTTP ${status}: ${url}`);
    }
    try {
      const u = new URL(url);
      const p = u.pathname;
      const method = response.request().method();
      if (p.includes("/sector-research/data/pcb") && method === "GET") bag.dataPcb += 1;
      if (p.includes("/sector-research/reports/pcb") && method === "GET") bag.reportsPcb += 1;
      if (p.includes("/sector-research/import/pcb") && method === "POST") bag.importPost += 1;
      if (
        (p === "/api/myreports" || p === "/api/myreports/")
        && method === "GET"
      ) {
        bag.myreportsGet += 1;
      }
      if (p.startsWith("/api/myreports/") && method === "PATCH") bag.myreportsPatch += 1;
    } catch {
      /* ignore parse errors */
    }
  }

  return { bag, onResponse };
}

async function expectVisibleTexts(page, texts, label, errors) {
  for (const text of texts) {
    const ok = await page.getByText(text, { exact: false }).first().isVisible().catch(() => false);
    if (!ok) errors.push(`${label}: missing visible text ${text}`);
  }
}

async function assertNoHorizontalOverflow(page, label, errors) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
  );
  if (overflow) errors.push(`${label}: horizontal overflow`);
}

async function runDesktop(browser, errors, networkBag) {
  const label = "desktop";
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(`${label} pageerror: ${error.message}`));
  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error" && !(text.includes("Failed to load resource") && text.includes("400"))) {
      errors.push(`${label} console: ${text}`);
    }
  });
  page.on("response", networkBag.onResponse);

  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/pcb/overview`, {
    waitUntil: "networkidle",
  });
  await expectVisibleTexts(
    page,
    ["总览", "原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图"],
    label,
    errors,
  );
  await page.screenshot({
    path: path.join(shotDir, "desktop-pcb-overview.png"),
    fullPage: true,
  });
  await assertNoHorizontalOverflow(page, `${label} overview`, errors);

  // Switch all 6 tags
  for (const tag of ["原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图", "总览"]) {
    await page.getByRole("link", { name: tag }).click();
    await page.waitForLoadState("networkidle");
  }
  await page.goBack();
  await page.goForward();
  await page.reload({ waitUntil: "networkidle" });

  // Expand live data + refresh
  const dataBeforeExpand = networkBag.bag.dataPcb;
  const expand = page.getByRole("button", { name: /展开/ }).last();
  await expand.click();
  await page.waitForTimeout(1200);
  if (networkBag.bag.dataPcb !== dataBeforeExpand + 1) {
    errors.push(
      `${label}: first expand expected exactly one dynamic request; `
      + `before=${dataBeforeExpand}, after=${networkBag.bag.dataPcb}`,
    );
  }
  const bodyAfterExpand = await page.locator("body").innerText();
  if (!bodyAfterExpand.includes("机构数") || !bodyAfterExpand.includes("1.50")) {
    errors.push(
      `${label}: dynamic summary missing after expand; `
      + `text=${bodyAfterExpand.slice(0, 800).replace(/\s+/g, " ")}`,
    );
  }
  // Collapse then re-expand (cached — no extra requirement here beyond refresh)
  const collapse = page.getByRole("button", { name: /收起/ }).last();
  if (await collapse.isVisible().catch(() => false)) {
    await collapse.click();
    const dataBeforeReopen = networkBag.bag.dataPcb;
    await expand.click();
    await page.waitForTimeout(400);
    if (networkBag.bag.dataPcb !== dataBeforeReopen) {
      errors.push(`${label}: cached re-open issued another dynamic request`);
    }
  }
  const dataBeforeRefresh = networkBag.bag.dataPcb;
  await page.getByRole("button", { name: /刷新/ }).last().click();
  await page.waitForTimeout(800);
  if (networkBag.bag.dataPcb !== dataBeforeRefresh + 1) {
    errors.push(`${label}: refresh expected exactly one dynamic request`);
  }

  // Discovery scopes 行业 / 公司 / 全部
  const scopeSelect = page.locator("select").first();
  const daysInput = page.locator("input[type=number]").first();
  for (const [scopeValue, days] of [
    ["industry", "365"],
    ["company", "30"],
    ["all", "730"],
  ]) {
    await scopeSelect.selectOption(scopeValue);
    await daysInput.fill(days);
    await page.getByRole("button", { name: /开始发现/ }).click();
    await page.getByText("共发现 557 条").waitFor({ timeout: 15000 });
  }

  await page.screenshot({
    path: path.join(shotDir, "desktop-report-discovery.png"),
    fullPage: true,
  });
  await assertNoHorizontalOverflow(page, `${label} discovery`, errors);

  // Save first OK-* row (real cache → import_report_bytes)
  await page.getByRole("button", { name: /保存到我的研报/ }).first().click();
  await page.getByText(/已保存到我的研报|已存在/).waitFor({ timeout: 15000 });
  // ERR row: harness-directed cache miss → production import 400 → UI expiry copy
  // Avoid /过期|重新/ — title "PCB 过期缓存错误样本" also matches and breaks strict mode.
  await page.getByRole("button", { name: /保存到我的研报/ }).nth(1).click();
  await page.getByText("发现结果已过期，请重新点击“开始发现”").waitFor({ timeout: 15000 });

  // Navigate to my-reports (prefer in-page link)
  const archivedLink = page.getByRole("link", { name: /查看已归档研报/ }).first();
  if (await archivedLink.isVisible().catch(() => false)) {
    await archivedLink.click();
  } else {
    await page.goto(`http://127.0.0.1:${frontendPort}/my-reports`, {
      waitUntil: "networkidle",
    });
  }
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  await expectVisibleTexts(page, ["按时间", "按产业", "按机构"], label, errors);
  await page.getByRole("button", { name: "按时间" }).click();
  await page.getByRole("button", { name: "按产业" }).click();
  await page.getByRole("button", { name: "按机构" }).click();
  await assertNoHorizontalOverflow(page, `${label} my-reports before patch`, errors);

  // GET /api/myreports via page.evaluate fetch; find OK-*; PATCH institution ""; re-GET
  const list1 = await page.evaluate(async () => {
    const res = await fetch("/api/myreports");
    const json = await res.json();
    return { status: res.status, data: json.data ?? json };
  });
  if (list1.status !== 200) {
    errors.push(`${label}: GET /api/myreports status ${list1.status}`);
  }
  const rows = Array.isArray(list1.data) ? list1.data : [];
  const okRow = rows.find((r) => String(r.external_id || "").startsWith("OK-"));
  if (!okRow) {
    errors.push(`${label}: no OK-* external_id in myreports list`);
  } else {
    await page.goto(
      `http://127.0.0.1:${frontendPort}/my-reports?report=${encodeURIComponent(okRow.id)}`,
      { waitUntil: "networkidle" },
    );
    if (!page.url().includes(`report=${encodeURIComponent(okRow.id)}`)) {
      errors.push(`${label}: imported report query not preserved in URL`);
    }
    const patch = await page.evaluate(async (id) => {
      const res = await fetch(`/api/myreports/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ institution: "" }),
      });
      const json = await res.json().catch(() => ({}));
      return { status: res.status, data: json.data ?? json };
    }, okRow.id);
    if (patch.status !== 200) {
      errors.push(`${label}: PATCH institution failed status ${patch.status}`);
    }
    const list2 = await page.evaluate(async () => {
      const res = await fetch("/api/myreports");
      const json = await res.json();
      return { status: res.status, data: json.data ?? json };
    });
    const again = (Array.isArray(list2.data) ? list2.data : []).find((r) => r.id === okRow.id);
    if (!again || again.institution !== "") {
      errors.push(
        `${label}: institution not cleared after PATCH; got ${JSON.stringify(again?.institution)}`,
      );
    }
  }

  await page.reload({ waitUntil: "networkidle" });
  if (okRow && !page.url().includes(`report=${encodeURIComponent(okRow.id)}`)) {
    errors.push(`${label}: refresh lost report query`);
  }
  await page.screenshot({
    path: path.join(shotDir, "desktop-my-reports.png"),
    fullPage: true,
  });
  await assertNoHorizontalOverflow(page, `${label} my-reports`, errors);

  // POST import with NOT-IN-CACHE-XYZ → 400 containing 过期/重新
  const badImport = await page.evaluate(async () => {
    const res = await fetch("/api/sector-research/import/pcb", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ external_id: "NOT-IN-CACHE-XYZ" }),
    });
    const text = await res.text();
    return { status: res.status, text };
  });
  if (badImport.status !== 400) {
    errors.push(`${label}: NOT-IN-CACHE import expected 400, got ${badImport.status}`);
  } else if (!/过期|重新/.test(badImport.text)) {
    errors.push(`${label}: NOT-IN-CACHE body missing 过期/重新: ${badImport.text.slice(0, 200)}`);
  }

  await assertNoHorizontalOverflow(page, label, errors);
  await context.close();
}

async function runMobile(browser, errors, networkBag) {
  const label = "mobile-390";
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(`${label} pageerror: ${error.message}`));
  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error" && !(text.includes("Failed to load resource") && text.includes("400"))) {
      errors.push(`${label} console: ${text}`);
    }
  });
  page.on("response", networkBag.onResponse);

  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/pcb/overview`, {
    waitUntil: "networkidle",
  });
  await expectVisibleTexts(
    page,
    ["总览", "原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图"],
    label,
    errors,
  );
  await page.screenshot({
    path: path.join(shotDir, "mobile-pcb-overview-390.png"),
    fullPage: true,
  });
  await assertNoHorizontalOverflow(page, `${label} overview`, errors);

  for (const tag of ["原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图", "总览"]) {
    await page.getByRole("link", { name: tag }).click();
    await page.waitForLoadState("networkidle");
  }
  await page.goBack();
  await page.goForward();
  await page.reload({ waitUntil: "networkidle" });

  const dataBeforeExpand = networkBag.bag.dataPcb;
  const expand = page.getByRole("button", { name: /展开/ }).last();
  await expand.click();
  await page.waitForTimeout(1200);
  if (networkBag.bag.dataPcb !== dataBeforeExpand + 1) {
    errors.push(
      `${label}: first expand expected exactly one dynamic request; `
      + `before=${dataBeforeExpand}, after=${networkBag.bag.dataPcb}`,
    );
  }
  const bodyAfterExpand = await page.locator("body").innerText();
  if (!bodyAfterExpand.includes("机构数") || !bodyAfterExpand.includes("1.50")) {
    errors.push(
      `${label}: dynamic summary missing after expand; `
      + `text=${bodyAfterExpand.slice(0, 800).replace(/\s+/g, " ")}`,
    );
  }
  const collapse = page.getByRole("button", { name: /收起/ }).last();
  if (await collapse.isVisible().catch(() => false)) {
    await collapse.click();
    const dataBeforeReopen = networkBag.bag.dataPcb;
    await expand.click();
    await page.waitForTimeout(400);
    if (networkBag.bag.dataPcb !== dataBeforeReopen) {
      errors.push(`${label}: cached re-open issued another dynamic request`);
    }
  }
  const dataBeforeRefresh = networkBag.bag.dataPcb;
  await page.getByRole("button", { name: /刷新/ }).last().click();
  await page.waitForTimeout(800);
  if (networkBag.bag.dataPcb !== dataBeforeRefresh + 1) {
    errors.push(`${label}: refresh expected exactly one dynamic request`);
  }

  const scopeSelect = page.locator("select").first();
  const daysInput = page.locator("input[type=number]").first();
  for (const [scopeValue, days] of [
    ["industry", "365"],
    ["company", "30"],
    ["all", "730"],
  ]) {
    await scopeSelect.selectOption(scopeValue);
    await daysInput.fill(days);
    await page.getByRole("button", { name: /开始发现/ }).click();
    await page.getByText("共发现 557 条").waitFor({ timeout: 15000 });
  }
  await page.screenshot({
    path: path.join(shotDir, "mobile-report-discovery-390.png"),
    fullPage: true,
  });
  await assertNoHorizontalOverflow(page, `${label} discovery`, errors);

  await page.getByRole("button", { name: /保存到我的研报/ }).first().click();
  await page.getByText(/已保存到我的研报|已存在/).waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: /保存到我的研报/ }).nth(1).click();
  await page.getByText("发现结果已过期，请重新点击“开始发现”").waitFor({ timeout: 15000 });

  const archivedLink = page.getByRole("link", { name: /查看已归档研报/ }).first();
  if (await archivedLink.isVisible().catch(() => false)) {
    await archivedLink.click();
  } else {
    await page.goto(`http://127.0.0.1:${frontendPort}/my-reports`, {
      waitUntil: "networkidle",
    });
  }
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  await expectVisibleTexts(page, ["按时间", "按产业", "按机构"], label, errors);
  await page.getByRole("button", { name: "按时间" }).click();
  await page.getByRole("button", { name: "按产业" }).click();
  await page.getByRole("button", { name: "按机构" }).click();

  const list1 = await page.evaluate(async () => {
    const res = await fetch("/api/myreports");
    const json = await res.json();
    return { status: res.status, data: json.data ?? json };
  });
  const rows = Array.isArray(list1.data) ? list1.data : [];
  const okRow = rows.find((r) => String(r.external_id || "").startsWith("OK-"));
  if (!okRow) {
    errors.push(`${label}: no OK-* external_id in myreports list`);
  } else {
    await page.goto(
      `http://127.0.0.1:${frontendPort}/my-reports?report=${encodeURIComponent(okRow.id)}`,
      { waitUntil: "networkidle" },
    );
    const patch = await page.evaluate(async (id) => {
      const res = await fetch(`/api/myreports/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ institution: "" }),
      });
      const json = await res.json().catch(() => ({}));
      return { status: res.status, data: json.data ?? json };
    }, okRow.id);
    if (patch.status !== 200) {
      errors.push(`${label}: PATCH institution failed status ${patch.status}`);
    }
    await page.reload({ waitUntil: "networkidle" });
    if (!page.url().includes(`report=${encodeURIComponent(okRow.id)}`)) {
      errors.push(`${label}: refresh lost report query`);
    }
  }

  await page.screenshot({
    path: path.join(shotDir, "mobile-my-reports-390.png"),
    fullPage: true,
  });
  await assertNoHorizontalOverflow(page, `${label} my-reports`, errors);
  await context.close();
}

function assertNetworkBag(bag, errors) {
  if (bag.dataPcb < 1) errors.push(`network: data/pcb GET expected >=1, got ${bag.dataPcb}`);
  if (bag.reportsPcb < 3) errors.push(`network: reports/pcb GET expected >=3, got ${bag.reportsPcb}`);
  if (bag.importPost < 1) errors.push(`network: import POST expected >=1, got ${bag.importPost}`);
  if (bag.myreportsGet < 1) errors.push(`network: myreports GET expected >=1, got ${bag.myreportsGet}`);
  if (bag.myreportsPatch < 1) errors.push(`network: myreports PATCH expected >=1, got ${bag.myreportsPatch}`);
}

async function assertReportsDir(reportsDir, errors) {
  const indexPath = path.join(reportsDir, "index.json");
  if (!existsSync(indexPath)) {
    errors.push("reportsDir/index.json missing after browser flow");
    return;
  }
  const index = JSON.parse(await readFile(indexPath, "utf8"));
  const items = Array.isArray(index) ? index : index.reports || index.items || [];
  const okItems = items.filter((r) => String(r.external_id || "").startsWith("OK-"));
  if (okItems.length < 1) {
    errors.push(`expected >=1 OK-* report in index.json, got ${items.length} total`);
    return;
  }
  const report = okItems[0];
  if (!Array.isArray(report.sector_keys) || !report.sector_keys.includes("pcb")) {
    errors.push(`OK-* sector_keys missing pcb: ${JSON.stringify(report.sector_keys)}`);
  }
  if (report.source_provider !== "eastmoney") {
    errors.push(`OK-* source_provider expected eastmoney, got ${report.source_provider}`);
  }
  if (report.institution !== "") {
    errors.push(`OK-* institution expected "", got ${JSON.stringify(report.institution)}`);
  }
  const pdfPath = path.join(reportsDir, `${report.id}.pdf`);
  const altPdf = path.join(reportsDir, report.name || "");
  const pdfFile = existsSync(pdfPath) ? pdfPath : (existsSync(altPdf) ? altPdf : null);
  if (!pdfFile) {
    // try any ${id}.*
    const candidate = path.join(reportsDir, `${report.id}${report.ext || ".pdf"}`);
    if (existsSync(candidate)) {
      const head = await readFile(candidate);
      if (!head.slice(0, 4).toString("utf8").startsWith("%PDF")) {
        errors.push(`PDF magic missing in ${candidate}`);
      }
    } else {
      errors.push(`PDF file missing for report id ${report.id}`);
    }
  } else {
    const head = await readFile(pdfFile);
    if (!head.slice(0, 4).toString("utf8").startsWith("%PDF")) {
      errors.push(`PDF magic missing in ${pdfFile}`);
    }
  }
}

function buildPythonPath() {
  const sep = process.platform === "win32" ? ";" : ":";
  const existing = process.env.PYTHONPATH || "";
  // backend first (app, sector_research_data), then e2e (harness_app)
  const parts = [backendDir, e2eDir];
  if (existing) parts.push(existing);
  return parts.join(sep);
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error("frontend/dist missing; run npm run build first");
  }
  if (!existsSync(harnessSrc)) {
    throw new Error(`harness missing: ${harnessSrc}`);
  }
  // Guard: never write harness into backend/
  const forbiddenHarness = path.join(backendDir, "harness_app.py");
  if (existsSync(forbiddenHarness)) {
    throw new Error(
      `backend/harness_app.py must not exist in the worktree before E2E `
      + `(found ${forbiddenHarness}); remove it and re-run`,
    );
  }

  await mkdir(shotDir, { recursive: true });

  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-e2e-data-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-e2e-reports-"));
  backendPort = await getFreePort();
  frontendPort = await getFreePort();

  const python = resolvePython();
  let backendExited = false;
  let backendCode = null;
  // Load harness from frontend/tests/e2e via PYTHONPATH; import production modules from backend/.
  // cwd = repo root so relative paths and imports resolve without copying into backend/.
  const backend = spawn(
    python,
    [
      "-m",
      "uvicorn",
      "harness_app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(backendPort),
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: buildPythonPath(),
        VR_DATA_DIR: dataDir,
        VR_REPORTS_DIR: reportsDir,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let backendLog = "";
  backend.stdout.on("data", (d) => {
    backendLog += d.toString();
  });
  backend.stderr.on("data", (d) => {
    const s = d.toString();
    backendLog += s;
    process.stderr.write(s);
  });
  backend.on("exit", (code) => {
    backendExited = true;
    backendCode = code;
  });

  const staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
  const errors = [];
  const networkBag = createNetworkBag(errors, "net");

  try {
    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    if (backendExited) {
      throw new Error(`isolated backend exited before ready (code=${backendCode})\n${backendLog.slice(-2000)}`);
    }
    if (existsSync(forbiddenHarness)) {
      throw new Error("E2E must not create backend/harness_app.py");
    }
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);

    const browser = await launchBrowser();
    try {
      await runDesktop(browser, errors, networkBag);
      await runMobile(browser, errors, networkBag);
    } finally {
      await browser.close().catch(() => {});
    }

    assertNetworkBag(networkBag.bag, errors);
    await assertReportsDir(reportsDir, errors);

    if (existsSync(forbiddenHarness)) {
      errors.push("backend/harness_app.py was created during E2E (forbidden)");
    }

    // README: record acceptance evidence without full temp paths or private data.
    const readme = [
      "# Sector research browser acceptance",
      "",
      `Date: ${new Date().toISOString()}`,
      `Browser: ${browserLabel}`,
      "Isolated VR_DATA_DIR used: yes",
      "Isolated VR_REPORTS_DIR used: yes",
      "",
      "## Transport",
      "API transport: real reverse proxy",
      "FastAPI routes: production routes",
      "External IO: test harness stubs",
      "Expired-cache case: harness-directed cache miss for ERR",
      "Worktree files created/deleted: none",
      "Harness load: PYTHONPATH=backend + frontend/tests/e2e; uvicorn harness_app:app (cwd=repo root)",
      "",
      "## Covered",
      "- 板块中心进入 PCB",
      "- 六个 Tag",
      "- 动态数据展开与刷新",
      "- 研报行业/公司/全部发现",
      "- 自定义 days",
      "- 截断数量提示",
      "- 缓存导入与导入错误反馈（ERR 可见行 → harness 定向 miss → 生产 import 400 → 重新发现提示）",
      "- 我的研报定位",
      "- 按时间/产业/机构分类",
      "- 元数据清空",
      "- 前进后退与刷新恢复",
      "- 桌面 1440px 与移动 390px 无整体横向滚动",
      "",
      "## Screenshots",
      "- desktop-pcb-overview.png",
      "- desktop-report-discovery.png",
      "- desktop-my-reports.png",
      "- mobile-pcb-overview-390.png",
      "- mobile-report-discovery-390.png",
      "- mobile-my-reports-390.png",
      "",
      "## Errors",
      errors.length ? errors.map((error) => `- ${error}`).join("\n") : "- none",
      "",
    ].join("\n");
    await writeFile(path.join(shotDir, "README.md"), readme, "utf8");

    if (errors.length) {
      throw new Error(`browser acceptance failed:\n${errors.join("\n")}`);
    }
    console.log(`Browser acceptance OK; screenshots in ${shotDir}; browser=${browserLabel}`);
  } finally {
    staticServer.close();
    if (!backendExited) {
      try {
        backend.kill("SIGTERM");
      } catch {
        /* ignore */
      }
      // Windows fallback
      if (process.platform === "win32" && backend.pid) {
        try {
          spawn("taskkill", ["/pid", String(backend.pid), "/t", "/f"], {
            stdio: "ignore",
            windowsHide: true,
          });
        } catch {
          /* ignore */
        }
      }
    }
    await sleep(300);
    // Only remove mkdtemp dirs — never delete or overwrite worktree files.
    await rm(dataDir, { recursive: true, force: true }).catch(() => {});
    await rm(reportsDir, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
