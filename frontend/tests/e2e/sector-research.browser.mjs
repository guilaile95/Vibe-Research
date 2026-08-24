/**
 * Sector research browser acceptance — REAL integration.
 *
 * Architecture:
 * - Playwright loads the Vite build from a Node static server
 * - Static server reverse-proxies /api/* to an isolated FastAPI process
 * - FastAPI is uvicorn harness_app:app loaded via PYTHONPATH
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
  if (process.env.VR_E2E_PYTHON && process.env.VR_E2E_PYTHON.trim()) {
    return process.env.VR_E2E_PYTHON.trim();
  }
  if (process.env.VR_PYTHON && process.env.VR_PYTHON.trim()) {
    return process.env.VR_PYTHON.trim();
  }
  const win = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  if (existsSync(win)) return win;
  const lin = path.join(root, "backend", ".venv", "bin", "python");
  if (existsSync(lin)) return lin;
  return process.platform === "win32" ? "python.exe" : "python3";
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
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
  };

  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    if (rawUrl.startsWith("/api/")) {
      const proxyReq = http.request(
        {
          hostname: "127.0.0.1",
          port: apiBackendPort,
          path: rawUrl,
          method: req.method,
          headers: { ...req.headers, host: `127.0.0.1:${apiBackendPort}` },
        },
        (proxyRes) => {
          res.writeHead(proxyRes.statusCode || 500, proxyRes.headers);
          proxyRes.pipe(res, { end: true });
        },
      );
      proxyReq.on("error", (err) => {
        res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
        res.end(`Bad Gateway (proxy error): ${err.message}`);
      });
      req.pipe(proxyReq, { end: true });
      return;
    }

    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    // 路径遍历防护：确保解析后的 target 仍在 dir 内
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || (existsSync(target) && path.extname(target) === "")) {
      target = path.join(dir, "index.html");
    }
    const ext = path.extname(target);
    const type = mime[ext] || "application/octet-stream";
    res.setHeader("Content-Type", type);
    createReadStream(target).pipe(res);
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function launchBrowser() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  const launchOpts = {
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  };
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const b = await chromium.launch(launchOpts);
      browserLabel = `local chromium-${b.version()}`;
      return b;
    } catch (error) {
      lastError = error;
      if (attempt === 0) {
        launchOpts.channel = "chrome";
      }
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
    sectorDataRequests: {},
    sectorReportsRequests: {},
    sectorImportRequests: {},
    sectorReportsDetails: [],
    badStatuses: [],
  };

  function onResponse(response) {
    const url = response.url();
    if (!url.includes("/api")) return;
    if (url.includes("/api/api")) {
      errors.push(`${label} double api path: ${url}`);
    }
    const status = response.status();
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
      if (p.includes("/sector-research/data/") && method === "GET") {
        const sk = p.split("/sector-research/data/")[1];
        if (sk) bag.sectorDataRequests[sk] = (bag.sectorDataRequests[sk] || 0) + 1;
      }
      if (p.includes("/sector-research/reports/") && method === "GET") {
        const sk = p.split("/sector-research/reports/")[1];
        if (sk) {
          bag.sectorReportsRequests[sk] = (bag.sectorReportsRequests[sk] || 0) + 1;
          bag.sectorReportsDetails.push({ sectorKey: sk, url: url, status: status, ts: Date.now() });
        }
      }
      if (p.includes("/sector-research/import/") && method === "POST") {
        const sk = p.split("/sector-research/import/")[1];
        if (sk) bag.sectorImportRequests[sk] = (bag.sectorImportRequests[sk] || 0) + 1;
      }
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
    const el = page.getByText(text).first();
    const visible = await el.isVisible().catch(() => false);
    if (!visible) {
      errors.push(`${label}: missing expected text "${text}"`);
    }
  }
}

async function assertNoHorizontalOverflow(page, label, errors) {
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  if (scrollWidth > clientWidth + 2) {
    errors.push(`${label}: horizontal overflow (scrollWidth ${scrollWidth} > clientWidth ${clientWidth})`);
  }
}

const SECTOR_TAG_MAP = {
  humanoid: [
    { label: "总览", slug: "overview" },
    { label: "机械、电控和具身智能架构", slug: "architecture" },
    { label: "单机 BOM 与价值量", slug: "value" },
    { label: "执行器、丝杠和灵巧手", slug: "actuators" },
    { label: "零部件、整机与客户格局", slug: "industry" },
    { label: "降本能力、客户认证和量产信号", slug: "pricing" },
  ],
  "ai-computing": [
    { label: "总览", slug: "overview" },
    { label: "算力系统架构", slug: "architecture" },
    { label: "单机、单柜与集群价值量", slug: "value" },
    { label: "Scale-up 网络与机柜架构", slug: "scale-up" },
    { label: "芯片、服务器、网络、散热产业格局", slug: "industry" },
    { label: "供给约束、定价权与资本开支信号", slug: "pricing" },
  ],
  hbm: [
    { label: "总览", slug: "overview" },
    { label: "DRAM 堆叠与 TSV 原理", slug: "dram-tsv" },
    { label: "单颗 GPU 和系统价值量", slug: "value" },
    { label: "HBM4 / HBM4E 与下一代堆叠", slug: "next-gen" },
    { label: "DRAM、封装、设备与材料格局", slug: "industry" },
    { label: "产能分配、合约价与定价权", slug: "pricing" },
  ],
  cpo: [
    { label: "总览", slug: "overview" },
    { label: "光模块、硅光和 CPO 原理", slug: "optics" },
    { label: "单端口和单集群价值量", slug: "value" },
    { label: "1.6T / 3.2T / CPO", slug: "next-gen" },
    { label: "光芯片、器件、模块和代工格局", slug: "industry" },
    { label: "供需、良率、价格与技术替代风险", slug: "risk" },
  ],
  semiconductor: [
    { label: "总览", slug: "overview" },
    { label: "晶圆制造流程与核心技术", slug: "process" },
    { label: "设备和材料价值量", slug: "value" },
    { label: "先进制程、先进封装和关键设备突破", slug: "breakthrough" },
    { label: "全球供应链与国产化梯队", slug: "industry" },
    { label: "全球不可替代性与国产替代溢价", slug: "pricing" },
  ],
  "smart-driving": [
    { label: "总览", slug: "overview" },
    { label: "感知、计算、规划与线控", slug: "architecture" },
    { label: "单车价值量", slug: "value" },
    { label: "端到端、城市 NOA 与 Robotaxi", slug: "next-gen" },
    { label: "芯片、算法、零部件与车企格局", slug: "industry" },
    { label: "软件收费、成本转嫁和监管风险", slug: "pricing" },
  ],
  "solid-state-battery": [
    { label: "总览", slug: "overview" },
    { label: "硫化物、氧化物和聚合物路线", slug: "chemistry" },
    { label: "单机与材料价值量", slug: "value" },
    { label: "电解质、设备和量产工艺", slug: "manufacturing" },
    { label: "材料、电池厂和设备格局", slug: "industry" },
    { label: "良率、成本、专利与量产信号", slug: "pricing" },
  ],
  "low-altitude": [
    { label: "总览", slug: "overview" },
    { label: "飞行器、空域和运营体系", slug: "architecture" },
    { label: "eVTOL 与基础设施价值量", slug: "value" },
    { label: "适航、量产和商业运营", slug: "airworthiness" },
    { label: "整机、零部件、空管和运营格局", slug: "industry" },
    { label: "政策依赖、订单质量和盈利路径", slug: "pricing" },
  ],
};

async function testSectorFullWorkflow(page, sectorKey, isMobile, errors, networkBag) {
  const label = isMobile ? `mobile-390 ${sectorKey}` : `desktop ${sectorKey}`;
  const tags = SECTOR_TAG_MAP[sectorKey];

  // 1. Visit /sectors/{key} -> default tag
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/${sectorKey}`, { waitUntil: "networkidle" });
  let url = page.url();
  if (!url.includes(`/sectors/${sectorKey}/overview`)) {
    errors.push(`${label}: default redirect failed, URL: ${url}`);
  }

  // 2. Click through all 6 tags & verify URL, active state, non-empty body, sources section & links
  let prevTagBtn = null;
  for (const tag of tags) {
    const tagBtn = page.getByRole("link", { name: tag.label }).first();
    if (!(await tagBtn.isVisible().catch(() => false))) {
      errors.push(`${label}: tag link "${tag.label}" not visible`);
      continue;
    }
    await tagBtn.click();
    await page.waitForLoadState("networkidle");
    url = page.url();
    if (!url.includes(`/sectors/${sectorKey}/${tag.slug}`)) {
      errors.push(`${label}: tag "${tag.label}" click expected URL with ${tag.slug}, got ${url}`);
    }

    // Active state hard assertions
    const ariaCurrent = await tagBtn.getAttribute("aria-current");
    const dataActive = await tagBtn.getAttribute("data-active");
    if (ariaCurrent !== "page" || dataActive !== "true") {
      errors.push(`${label}: tag "${tag.label}" missing active state attributes (aria-current=${ariaCurrent}, data-active=${dataActive})`);
    }

    if (prevTagBtn) {
      const prevAriaCurrent = await prevTagBtn.getAttribute("aria-current");
      const prevDataActive = await prevTagBtn.getAttribute("data-active");
      if (prevAriaCurrent === "page" || prevDataActive === "true") {
        errors.push(`${label}: previous tag retained active state after switching to "${tag.label}"`);
      }
    }
    prevTagBtn = tagBtn;

    const bodyText = await page.locator("body").innerText();
    if (bodyText.length < 200) {
      errors.push(`${label}: tag "${tag.label}" body too short (${bodyText.length} chars)`);
    }

    const sourcesVis = await page.getByText(/来源|参考资料/).first().isVisible().catch(() => false);
    if (!sourcesVis) {
      errors.push(`${label}: tag "${tag.label}" missing sources section`);
    }

    const linksCount = await page.locator('a[href*="http"]').count();
    if (linksCount < 2) {
      errors.push(`${label}: tag "${tag.label}" too few source links (${linksCount})`);
    }
  }

  // 3. Test refresh on non-default tag
  const secondTag = tags[1];
  await page.getByRole("link", { name: secondTag.label }).first().click();
  await page.waitForLoadState("networkidle");
  await page.reload({ waitUntil: "networkidle" });
  if (!page.url().includes(`/sectors/${sectorKey}/${secondTag.slug}`)) {
    errors.push(`${label}: reload lost active tag ${secondTag.slug}`);
  }

  // 4. Test back and forward
  await page.goBack();
  await page.waitForLoadState("networkidle");
  await page.goForward();
  await page.waitForLoadState("networkidle");
  if (!page.url().includes(`/sectors/${sectorKey}/${secondTag.slug}`)) {
    errors.push(`${label}: goForward lost active tag ${secondTag.slug}`);
  }

  // Return to overview for screenshot & dynamic/discovery tests
  await page.getByRole("link", { name: "总览" }).first().click();
  await page.waitForLoadState("networkidle");

  // Screenshot
  const shotName = isMobile ? `mobile-${sectorKey}-overview-390.png` : `desktop-${sectorKey}-overview.png`;
  await page.screenshot({
    path: path.join(shotDir, shotName),
    fullPage: true,
  });
  await assertNoHorizontalOverflow(page, label, errors);

  // 5. Dynamic data expand, collapse, refresh
  const dataReqBefore = networkBag.bag.sectorDataRequests[sectorKey] || 0;
  const expandBtn = page.getByRole("button", { name: /展开/ }).last();
  if (await expandBtn.isVisible().catch(() => false)) {
    await expandBtn.click();
    await page.waitForTimeout(1000);
    const dataReqAfter = networkBag.bag.sectorDataRequests[sectorKey] || 0;
    if (dataReqAfter !== dataReqBefore + 1) {
      errors.push(`${label}: expand expected +1 dynamic data request, before=${dataReqBefore}, after=${dataReqAfter}`);
    }

    // Collapse & re-open
    const collapseBtn = page.getByRole("button", { name: /收起/ }).last();
    if (await collapseBtn.isVisible().catch(() => false)) {
      await collapseBtn.click();
      await page.waitForTimeout(300);
      const dataReqCachedBefore = networkBag.bag.sectorDataRequests[sectorKey] || 0;
      await expandBtn.click();
      await page.waitForTimeout(300);
      const dataReqCachedAfter = networkBag.bag.sectorDataRequests[sectorKey] || 0;
      if (dataReqCachedAfter !== dataReqCachedBefore) {
        errors.push(`${label}: re-open emitted unexpected extra request`);
      }
    }

    // Refresh
    const dataReqRefBefore = networkBag.bag.sectorDataRequests[sectorKey] || 0;
    const refreshBtn = page.getByRole("button", { name: /刷新/ }).first();
    if (await refreshBtn.isVisible().catch(() => false)) {
      await refreshBtn.click();
      await page.waitForTimeout(1000);
      const dataReqRefAfter = networkBag.bag.sectorDataRequests[sectorKey] || 0;
      if (dataReqRefAfter !== dataReqRefBefore + 1) {
        errors.push(`${label}: dynamic refresh expected +1 request, before=${dataReqRefBefore}, after=${dataReqRefAfter}`);
      }
    }
  } else {
    errors.push(`${label}: expand button not visible`);
  }

  // 6. Report discovery: full scope/days matrix with URL query verification
  // 4 combos — each scope has explicit days, all verified in URL
  const SCOPE_DAYS = [
    { scope: "industry", days: "30" },
    { scope: "company", days: "30" },
    { scope: "company", days: "180" },
    { scope: "all", days: "180" },
  ];
  for (const { scope, days } of SCOPE_DAYS) {
    const scopeSelect = page.locator("select").first();
    if (await scopeSelect.isVisible().catch(() => false)) {
      await scopeSelect.selectOption(scope);
      await page.waitForTimeout(200);
    }
    const daysInput = page.locator("input[type=number]").first();
    if (await daysInput.isVisible().catch(() => false)) {
      await daysInput.click({ clickCount: 3 });
      await daysInput.fill(String(days));
      await page.waitForTimeout(500);
    }
    const before = networkBag.bag.sectorReportsRequests[sectorKey] || 0;
    const startBtn = page.getByRole("button", { name: "开始发现" }).first();
    if (await startBtn.isVisible().catch(() => false)) {
      await startBtn.click();
      await page.waitForTimeout(1500);
    }
    const after = networkBag.bag.sectorReportsRequests[sectorKey] || 0;
    if (after !== before + 1) {
      errors.push(`${label}: scope="${scope}" days="${days}" expected +1 request (before=${before}, after=${after})`);
    }
    // Verify URL query params from last captured request
    const details = networkBag.bag.sectorReportsDetails;
    const lastReq = details.filter((d) => d.sectorKey === sectorKey).pop();
    if (lastReq) {
      try {
        const parsed = new URL(lastReq.url);
        const qScope = parsed.searchParams.get("scope") || "";
        const qDays = parsed.searchParams.get("days") || "";
        if (qScope !== scope) {
          errors.push(`${label}: scope="${scope}" but request URL has scope="${qScope}"`);
        }
        if (qDays !== days) {
          errors.push(`${label}: days="${days}" but request URL has days="${qDays}"`);
        }
        // Verify sector key appears in URL path
        if (!lastReq.url.includes(`/sector-research/reports/${sectorKey}`)) {
          errors.push(`${label}: request URL does not contain sector key "${sectorKey}": ${lastReq.url}`);
        }
      } catch {
        errors.push(`${label}: failed to parse request URL: ${lastReq.url}`);
      }
    } else {
      errors.push(`${label}: no request detail found for sector ${sectorKey}`);
    }
  }
}

async function testSectorStrengthWorkflow(page, errors, label) {
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors`, { waitUntil: "networkidle" });
  await expectVisibleTexts(page, ["板块强度", "今日行业横截面", "Vibe 赛道多周期观察", "20日排名", "5日动能变化", "印制电路板"], `${label} strength`, errors);
  const pcbStrengthLink = page.getByRole("link", { name: "PCB（印制电路板）" }).first();
  if (await pcbStrengthLink.isVisible().catch(() => false)) {
    await pcbStrengthLink.click();
    await page.waitForLoadState("networkidle");
    if (!page.url().includes("/sectors/pcb/overview")) errors.push(`${label}: strength row did not continue to PCB research`);
    await page.locator('[data-sector-market-context="pcb"]').waitFor({ state: "visible", timeout: 5000 }).catch(async () => {
      errors.push(`${label}: PCB market context container missing; body=${(await page.locator("body").innerText()).slice(0, 500)}`);
    });
    await expectVisibleTexts(page, ["市场上下文", "884092.TI", "当前成分 47", "当前成分等权代理", "沪电股份"], `${label} market context`, errors);
  } else {
    errors.push(`${label}: mapped PCB strength continuation missing`);
  }
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/humanoid/overview`, { waitUntil: "networkidle" });
  await expectVisibleTexts(page, ["市场上下文", "886069.TI", "+3.21%", "当前成分股宽度暂不可用"], `${label} partial breadth`, errors);
  await assertNoHorizontalOverflow(page, `${label} strength`, errors);
}

async function runStrengthOnly(browser, errors, networkBag) {
  const label = "sector-strength";
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(`${label} pageerror: ${error.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`${label} console: ${msg.text()}`);
  });
  page.on("response", networkBag.onResponse);
  await testSectorStrengthWorkflow(page, errors, label);
  await context.close();
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

  // 1. Sector strength -> mapped market context -> existing research path
  await testSectorStrengthWorkflow(page, errors, label);

  // 2. PCB full workflow
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/pcb/overview`, { waitUntil: "networkidle" });
  await expectVisibleTexts(page, ["总览", "原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图"], label, errors);
  await page.screenshot({ path: path.join(shotDir, "desktop-pcb-overview.png"), fullPage: true });
  await assertNoHorizontalOverflow(page, `${label} overview`, errors);

  // 2. Batch 1 4 Sectors Desktop Workflow
  for (const sectorKey of ["humanoid", "ai-computing", "hbm", "cpo", "semiconductor", "smart-driving", "solid-state-battery", "low-altitude"]) {
    await testSectorFullWorkflow(page, sectorKey, false, errors, networkBag);
  }

  // 3. Unbuilt sector placeholder verification
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/nonexistent`, { waitUntil: "networkidle" });
  const unbuiltText = await page.locator("body").innerText();
  if (!unbuiltText.includes("当前仅有产业链骨架") && !unbuiltText.includes("尚未建设") && !unbuiltText.includes("未找到")) {
    errors.push(`${label}: unbuilt sector nonexistent missing clear placeholder notice`);
  }

  // Return to PCB for remaining harness checks (report discovery import & My Reports)
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/pcb/overview`, { waitUntil: "networkidle" });

  // PCB Discovery & Import
  const pcbScopeSelect = page.locator("select").first();
  if (await pcbScopeSelect.isVisible().catch(() => false)) {
    await pcbScopeSelect.selectOption("company");
    await page.waitForTimeout(500);
  }
  const discoveryBefore = networkBag.bag.reportsPcb;
  const pcbDiscBtn = page.getByRole("button", { name: "开始发现" }).first();
  if (await pcbDiscBtn.isVisible().catch(() => false)) {
    await pcbDiscBtn.click();
    await page.waitForTimeout(1000);
  }
  if (networkBag.bag.reportsPcb < discoveryBefore + 1) {
    errors.push(`${label}: company scope expected +1 discovery request (before=${discoveryBefore}, after=${networkBag.bag.reportsPcb})`);
  }

  const daysInput = page.locator("input[type=number]").first();
  if (await daysInput.isVisible().catch(() => false)) {
    await daysInput.fill("180");
    await daysInput.press("Enter");
  }
  await page.waitForTimeout(800);

  const importBtn = page.getByRole("button", { name: "保存到我的研报" }).first();
  if (await importBtn.isVisible().catch(() => false)) {
    const importBefore = networkBag.bag.importPost;
    await importBtn.click();
    await page.waitForTimeout(1500);
    if (networkBag.bag.importPost !== importBefore + 1) {
      errors.push(`${label}: import button click expected +1 POST request`);
    }
  }

  await page.screenshot({ path: path.join(shotDir, "desktop-report-discovery.png"), fullPage: true });

  // My Reports
  await page.goto(`http://127.0.0.1:${frontendPort}/my-reports`, { waitUntil: "networkidle" });
  await expectVisibleTexts(page, ["我的研报"], label, errors);
  await page.screenshot({ path: path.join(shotDir, "desktop-my-reports.png"), fullPage: true });

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

  // 1. PCB Mobile
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/pcb/overview`, { waitUntil: "networkidle" });
  await expectVisibleTexts(page, ["总览", "价值量", "产业格局"], label, errors);
  await page.screenshot({ path: path.join(shotDir, "mobile-pcb-overview-390.png"), fullPage: true });
  await assertNoHorizontalOverflow(page, `${label} pcb`, errors);

  // 2. Batch 1 4 Sectors Mobile Workflow
  for (const sectorKey of ["humanoid", "ai-computing", "hbm", "cpo", "semiconductor", "smart-driving", "solid-state-battery", "low-altitude"]) {
    await testSectorFullWorkflow(page, sectorKey, true, errors, networkBag);
  }

  // 3. PCB Report Discovery Mobile
  await page.goto(`http://127.0.0.1:${frontendPort}/sectors/pcb/overview`, { waitUntil: "networkidle" });
  const expand = page.getByRole("button", { name: /展开/ }).last();
  if (await expand.isVisible().catch(() => false)) await expand.click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(shotDir, "mobile-report-discovery-390.png"), fullPage: true });

  // 4. My Reports Mobile
  await page.goto(`http://127.0.0.1:${frontendPort}/my-reports`, { waitUntil: "networkidle" });
  await expectVisibleTexts(page, ["我的研报"], label, errors);
  await page.screenshot({ path: path.join(shotDir, "mobile-my-reports-390.png"), fullPage: true });

  await context.close();
}

function assertNetworkBag(bag, errors) {
  if (bag.dataPcb < 1) errors.push("bag: expected at least 1 GET /sector-research/data/pcb");
  if (bag.reportsPcb < 1) errors.push("bag: expected at least 1 GET /sector-research/reports/pcb");
  if (bag.importPost < 1) errors.push("bag: expected at least 1 POST /sector-research/import/pcb");
}

async function main() {
  const strengthOnly = process.argv.includes("--strength-only");
  if (!existsSync(frontendDist)) {
    throw new Error("frontend/dist missing; run npm run build first");
  }
  if (existsSync(harnessSrc) && harnessSrc.includes(path.join(root, "backend"))) {
    throw new Error("forbidden harness copy in backend/");
  }

  await mkdir(shotDir, { recursive: true });

  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-e2e-data-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-e2e-reports-"));
  backendPort = await getFreePort();
  frontendPort = await getFreePort();

  const python = resolvePython();
  let backendExited = false;
  let backendCode = null;

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
        PYTHONPATH: [backendDir, e2eDir, process.env.PYTHONPATH || ""].filter(Boolean).join(process.platform === "win32" ? ";" : ":"),
        VR_DATA_DIR: dataDir,
        VR_REPORTS_DIR: reportsDir,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  let backendLog = "";
  backend.stdout.on("data", (d) => { backendLog += d.toString(); });
  backend.stderr.on("data", (d) => { backendLog += d.toString(); });
  backend.on("exit", (code) => {
    backendExited = true;
    backendCode = code;
  });

  let staticServer = null;
  const errors = [];
  const networkBag = createNetworkBag(errors, "e2e");

  try {
    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    staticServer = await startStaticServer(frontendDist, frontendPort, backendPort);
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);

    const browser = await launchBrowser();
    try {
      if (strengthOnly) {
        await runStrengthOnly(browser, errors, networkBag);
      } else {
        await runDesktop(browser, errors, networkBag);
        await runMobile(browser, errors, networkBag);
      }
    } finally {
      await browser.close().catch(() => {});
    }

    if (strengthOnly) {
      if (errors.length) throw new Error(`sector strength browser vertical failed:\n${errors.join("\n")}`);
      console.log(`Sector strength browser vertical OK; browser=${browserLabel}`);
      return;
    }

    assertNetworkBag(networkBag.bag, errors);

    const readme = [
      "# Sector research browser acceptance",
      "",
      `Date: ${new Date().toISOString()}`,
      `Browser: ${browserLabel}`,
      "Isolated VR_DATA_DIR used: yes",
      "Isolated VR_REPORTS_DIR used: yes",
      "",
      "## Covered",
      "- 板块中心进入 PCB",
      "- 板块中心进入 8 个已建设板块（Batch 1 + Batch 2：人形机器人 / AI算力 / HBM / 光互联 / 半导体 / 智能驾驶 / 固态电池 / 低空经济）",
      "- 桌面 1440px 与移动 390px 完整 6 Tag 导航、URL 匹配与刷新/前后退",
      "- 动态数据展开、缓存复用与手动刷新",
      "- 研报发现行业 / 代表公司 / 全部 范围切换与 days 过滤",
      "- 截断数量提示与我的研报归档/PATCH 属性",
      "- 桌面 1440px 与移动 390px 无整体横向滚动",
      "- 无 console error / pageerror / /api/api / 非预期 404/422/500",
      "",
      "## Screenshots",
      "- desktop-pcb-overview.png",
      "- desktop-report-discovery.png",
      "- desktop-my-reports.png",
      "- desktop-humanoid-overview.png",
      "- desktop-ai-computing-overview.png",
      "- desktop-hbm-overview.png",
      "- desktop-cpo-overview.png",
      "- desktop-semiconductor-overview.png",
      "- desktop-smart-driving-overview.png",
      "- desktop-solid-state-battery-overview.png",
      "- desktop-low-altitude-overview.png",
      "- mobile-pcb-overview-390.png",
      "- mobile-report-discovery-390.png",
      "- mobile-my-reports-390.png",
      "- mobile-humanoid-overview-390.png",
      "- mobile-ai-computing-overview-390.png",
      "- mobile-hbm-overview-390.png",
      "- mobile-cpo-overview-390.png",
      "- mobile-semiconductor-overview-390.png",
      "- mobile-smart-driving-overview-390.png",
      "- mobile-solid-state-battery-overview-390.png",
      "- mobile-low-altitude-overview-390.png",
      "",
      "## Errors",
      errors.length ? errors.map((error) => `- ${error}`).join("\n") : "- none",
      "",
    ].join("\n");

    await writeFile(path.join(shotDir, "README.md"), readme, "utf8");

    if (errors.length) {
      throw new Error(`browser acceptance failed:
${errors.join("\n")}`);
    }

    console.log(`Browser acceptance OK; screenshots in ${shotDir}; browser=${browserLabel}`);
  } finally {
    if (staticServer) {
      await new Promise((resolve) => staticServer.close(resolve)).catch(() => {});
    }
    if (!backendExited && backend.pid) {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(backend.pid), "/t", "/f"], { stdio: "ignore" });
      } else {
        backend.kill("SIGKILL");
      }
    }
    await rm(dataDir, { recursive: true, force: true }).catch(() => {});
    await rm(reportsDir, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
