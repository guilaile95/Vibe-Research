/**
 * Sector research browser acceptance.
 *
 * Uses real Playwright Chromium and isolated backend process. External-heavy
 * sector-research/myreports API responses are fulfilled in the browser route
 * layer so the UI flow is deterministic and never writes real user data.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir, writeFile, mkdtemp, rm } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const shotDir = path.join(root, "docs", "screenshots", "sector-research-accept");

let backendPort = 0;
let frontendPort = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitHttp(url, attempts = 60) {
  for (let i = 0; i < attempts; i++) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      /* retry */
    }
    await sleep(500);
  }
  throw new Error(`timeout waiting ${url}`);
}

function startStaticServer(dir, port) {
  const mime = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
  };
  const server = createServer((req, res) => {
    let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    if (urlPath === "/") urlPath = "/index.html";
    const file = path.join(dir, urlPath);
    if (!file.startsWith(dir) || !existsSync(file)) {
      const index = path.join(dir, "index.html");
      res.writeHead(200, { "Content-Type": "text/html" });
      createReadStream(index).pipe(res);
      return;
    }
    res.writeHead(200, { "Content-Type": mime[path.extname(file)] || "application/octet-stream" });
    createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
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

function jsonResponse(route, payload, status = 200) {
  return route.fulfill({
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(payload),
  });
}

function makeDiscovery(scope, days) {
  const common = {
    source_provider: "eastmoney",
    info_code: null,
    institution: "中信证券",
    publish_date: "2026-07-20",
    industry_name: "电子",
    company_code: null,
    company_name: null,
    pdf_url: "https://pdf.dfcfw.com/pdf/H3_AP202607200001_1.pdf",
    report_type: "brokerage",
    matched_keywords: ["PCB"],
    rating: "买入",
    date_unknown: false,
  };
  const suffix = `${scope}-${days}`;
  return [
    {
      ...common,
      external_id: `OK-${suffix}`,
      info_code: `OK-${suffix}`,
      title: `PCB ${scope} ${days}天 研究`,
      report_scope: scope === "company" ? "company" : "industry",
      relevance_score: 21,
    },
    {
      ...common,
      external_id: "ERR",
      info_code: "ERR",
      title: "PCB 过期缓存错误样本",
      report_scope: scope === "company" ? "company" : "industry",
      relevance_score: 18,
    },
  ];
}

function makeApiFixture() {
  const reports = [
    {
      id: "seed-report",
      name: "seed.pdf",
      industry: "PCB",
      size: 2048,
      ext: ".pdf",
      ts: 1784678400000,
      title: "既有PCB归档研报",
      institution: "华泰证券",
      publish_date: "2026-07-19",
      sector_keys: ["pcb"],
      source_url: "https://example.com/seed.pdf",
      source_kind: "report",
      imported_at: "2026-07-20T10:00:00+08:00",
      source_provider: "eastmoney",
      external_id: "SEED",
      info_code: "SEED",
      report_scope: "industry",
      report_type: "brokerage",
    },
  ];

  const discoveryRequests = [];
  const importRequests = [];
  const patchRequests = [];
  let liveDataRequests = 0;

  async function handle(route) {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.includes("/api/api")) {
      throw new Error(`double api path: ${url.href}`);
    }

    if (url.pathname === "/api/sector-research/data/pcb") {
      liveDataRequests += 1;
      return jsonResponse(route, {
        data: {
          sector_key: "pcb",
          source: "a-stock-data",
          fetched_at: "2026-07-24T08:30:00Z",
          status: "partial",
          warnings: ["002463 一致预期：依赖未安装"],
          companies: [
            {
              code: "002463",
              name: "沪电股份",
              panels: {
                individual_info: {
                  status: "ok",
                  summary: { name: "沪电股份", industry: "电子", market_cap: "1000亿" },
                  error: null,
                },
                profit_forecast: {
                  status: "ok",
                  summary: { year: "2027", eps: "1.50", coverage: "15", record_count: 2 },
                  error: null,
                },
                announcements: {
                  status: "error",
                  summary: {},
                  error: "依赖未安装",
                },
              },
            },
          ],
        },
      });
    }

    if (url.pathname === "/api/sector-research/reports/pcb") {
      const scope = url.searchParams.get("scope") || "industry";
      const days = url.searchParams.get("days") || "365";
      discoveryRequests.push({ scope, days });
      const rows = makeDiscovery(scope, days);
      return jsonResponse(route, {
        data: {
          sector_key: "pcb",
          discovered: rows,
          filtered: rows,
          error: null,
          total_discovered: 557,
          returned: rows.length,
          truncated: true,
        },
      });
    }

    if (url.pathname === "/api/sector-research/import/pcb") {
      const body = JSON.parse(request.postData() || "{}");
      importRequests.push(body);
      if (body.external_id === "ERR") {
        return jsonResponse(route, { detail: "发现结果已过期，请重新点击“开始发现”" }, 400);
      }
      const saved = {
        id: "imported-report",
        name: "imported.pdf",
        industry: "PCB",
        size: 4096,
        ext: ".pdf",
        ts: 1784764800000,
        title: "PCB 导入成功研报",
        institution: "中信证券",
        publish_date: "2026-07-20",
        sector_keys: ["pcb"],
        source_url: "https://pdf.dfcfw.com/pdf/H3_IMPORTED_1.pdf",
        source_kind: "report",
        imported_at: "2026-07-21T10:00:00+08:00",
        source_provider: "eastmoney",
        external_id: body.external_id,
        info_code: body.external_id,
        report_scope: "industry",
        report_type: "brokerage",
      };
      if (!reports.some((item) => item.id === saved.id)) reports.unshift(saved);
      return jsonResponse(route, { data: saved });
    }

    if (url.pathname === "/api/myreports" && request.method() === "GET") {
      return jsonResponse(route, { data: reports });
    }

    if (url.pathname.startsWith("/api/myreports/") && request.method() === "PATCH") {
      const id = url.pathname.split("/").pop();
      const body = JSON.parse(request.postData() || "{}");
      patchRequests.push({ id, body });
      const found = reports.find((item) => item.id === id);
      if (!found) return jsonResponse(route, { detail: "研报不存在" }, 404);
      Object.assign(found, body);
      return jsonResponse(route, { data: found });
    }

    if (url.pathname === "/api/myreports/search") {
      return jsonResponse(route, { data: reports });
    }

    return route.continue();
  }

  return {
    handle,
    stats: {
      get discoveryRequests() {
        return discoveryRequests;
      },
      get importRequests() {
        return importRequests;
      },
      get patchRequests() {
        return patchRequests;
      },
      get liveDataRequests() {
        return liveDataRequests;
      },
    },
  };
}

async function assertNoHorizontalOverflow(page, label, errors) {
  const overflow = await page.evaluate(() => (
    document.documentElement.scrollWidth > document.documentElement.clientWidth + 2
  ));
  if (overflow) errors.push(`${label}: horizontal overflow`);
}

async function runViewport(browser, name, width, height, errors) {
  const fixture = makeApiFixture();
  const context = await browser.newContext({ viewport: { width, height } });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(`${name} pageerror: ${error.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`${name} console: ${msg.text()}`);
  });
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/api")) errors.push(`${name} double api: ${url}`);
    if (response.status() >= 400 && !url.includes("/api/sector-research/import/pcb")) {
      errors.push(`${name} unexpected HTTP ${response.status()}: ${url}`);
    }
  });
  await page.route("**/api/**", fixture.handle);

  await page.goto(`http://127.0.0.1:${frontendPort}/sectors`, { waitUntil: "networkidle" });
  await page.getByText("PCB", { exact: false }).first().click({ timeout: 15000 }).catch(async () => {
    await page.goto(`http://127.0.0.1:${FRONT_PORT}/sectors/pcb/overview`, { waitUntil: "networkidle" });
  });
  if (!page.url().includes("/sectors/pcb")) {
    await page.goto(`http://127.0.0.1:${FRONT_PORT}/sectors/pcb/overview`, { waitUntil: "networkidle" });
  }
  await page.waitForLoadState("networkidle");
  await expectText(page, ["总览", "原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图"], name, errors);
  await page.screenshot({ path: path.join(shotDir, `${name}-pcb-overview.png`), fullPage: true });

  for (const tag of ["原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图", "总览"]) {
    await page.getByRole("link", { name: tag }).click();
    await page.waitForLoadState("networkidle");
  }
  await page.goBack();
  await page.goForward();
  await page.reload({ waitUntil: "networkidle" });

  const expand = page.getByRole("button", { name: /展开/ }).last();
  await expand.click();
  await page.getByText("沪电股份").waitFor({ timeout: 5000 });
  if (fixture.stats.liveDataRequests !== 1) {
    errors.push(`${name}: expected one live data request on first expand, got ${fixture.stats.liveDataRequests}`);
  }
  await page.getByRole("button", { name: /收起/ }).last().click();
  await expand.click();
  if (fixture.stats.liveDataRequests !== 1) {
    errors.push(`${name}: reopening with cached data requested again`);
  }
  await page.getByRole("button", { name: /刷新/ }).last().click();
  await page.waitForTimeout(250);
  if (fixture.stats.liveDataRequests !== 2) {
    errors.push(`${name}: refresh did not issue exactly one live data request`);
  }

  const scope = page.locator("select").first();
  const daysInput = page.locator("input[type=number]").first();
  for (const [scopeValue, days] of [["industry", "365"], ["company", "30"], ["all", "730"]]) {
    await scope.selectOption(scopeValue);
    await daysInput.fill(days);
    await page.getByRole("button", { name: /开始发现/ }).click();
    await page.getByText("共发现 557 条").waitFor({ timeout: 5000 });
  }
  const seen = fixture.stats.discoveryRequests.map((item) => `${item.scope}:${item.days}`);
  for (const expected of ["industry:365", "company:30", "all:730"]) {
    if (!seen.includes(expected)) errors.push(`${name}: missing discovery request ${expected}`);
  }

  await page.getByRole("button", { name: /保存到我的研报/ }).first().click();
  await page.getByText("已保存到我的研报").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: /保存到我的研报/ }).nth(1).click();
  await page.getByText("发现结果已过期").waitFor({ timeout: 5000 });
  if (!fixture.stats.importRequests.some((body) => body.external_id && !("title" in body))) {
    errors.push(`${name}: import body was not external_id-only`);
  }
  await page.screenshot({ path: path.join(shotDir, `${name}-report-discovery.png`), fullPage: true });

  await page.getByRole("link", { name: /查看已归档研报/ }).first().click();
  await page.waitForLoadState("networkidle");
  if (!page.url().includes("/my-reports?report=imported-report")) {
    errors.push(`${name}: imported report link did not preserve report query`);
  }
  await expectText(page, ["按时间", "按产业", "按机构", "PCB 导入成功研报"], name, errors);
  await page.getByRole("button", { name: "按时间" }).click();
  await page.getByRole("button", { name: "按产业" }).click();
  await page.getByRole("button", { name: "按机构" }).click();
  await page.reload({ waitUntil: "networkidle" });
  if (!page.url().includes("report=imported-report")) {
    errors.push(`${name}: refresh lost report query`);
  }
  await page.getByRole("button", { name: "编辑" }).first().click();
  await page.locator('input[placeholder="未确认机构"]').fill("");
  await page.getByRole("button", { name: /保存/ }).first().click();
  await page.waitForTimeout(500);
  if (!fixture.stats.patchRequests.some((entry) => entry.body.institution === "")) {
    errors.push(`${name}: metadata clear did not send empty institution`);
  }
  await page.screenshot({ path: path.join(shotDir, `${name}-my-reports.png`), fullPage: true });

  await assertNoHorizontalOverflow(page, name, errors);
  await context.close();
}

async function expectText(page, texts, label, errors) {
  for (const text of texts) {
    if (!(await page.getByText(text, { exact: false }).first().isVisible().catch(() => false))) {
      errors.push(`${label}: missing visible text ${text}`);
    }
  }
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error("frontend/dist missing; run npm run build first");
  }
  await mkdir(shotDir, { recursive: true });

  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-e2e-data-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-e2e-reports-"));
  backendPort = await getFreePort();
  frontendPort = await getFreePort();
  let backendExited = false;
  const backend = spawn(
    path.join(root, "backend", ".venv", "Scripts", "python.exe"),
    ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
    {
      cwd: path.join(root, "backend"),
      env: { ...process.env, VR_DATA_DIR: dataDir, VR_REPORTS_DIR: reportsDir },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  backend.stderr.on("data", (data) => process.stderr.write(data));
  backend.on("exit", () => {
    backendExited = true;
  });

  const staticServer = await startStaticServer(frontendDist, frontendPort);
  const errors = [];

  try {
    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    if (backendExited) throw new Error("isolated backend exited before acceptance");
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);
    const browser = await chromium.launch({ headless: true });
    await runViewport(browser, "desktop", 1440, 900, errors);
    await runViewport(browser, "mobile-390", 390, 844, errors);
    await browser.close();

    const readme = `# Sector research browser acceptance

Date: ${new Date().toISOString()}
Backend: http://127.0.0.1:${backendPort}
Frontend: http://127.0.0.1:${frontendPort}
VR_DATA_DIR: ${dataDir}
VR_REPORTS_DIR: ${reportsDir}

## Covered
- 板块中心进入 PCB
- 六个 Tag
- 动态数据展开与刷新
- 研报行业/公司/全部发现
- 自定义 days
- 截断数量提示
- 缓存导入与导入错误反馈
- 我的研报定位
- 按时间/产业/机构分类
- 元数据清空
- 前进后退与刷新恢复
- 桌面 1440px 与移动 390px 无整体横向滚动

## Screenshots
- desktop-pcb-overview.png
- desktop-report-discovery.png
- desktop-my-reports.png
- mobile-390-pcb-overview.png
- mobile-390-report-discovery.png
- mobile-390-my-reports.png

## Errors
${errors.length ? errors.map((error) => `- ${error}`).join("\n") : "- none"}
`;
    await writeFile(path.join(shotDir, "README.md"), readme, "utf8");
    if (errors.length) {
      throw new Error(`browser acceptance failed:\n${errors.join("\n")}`);
    }
    console.log(`Browser acceptance OK; screenshots in ${shotDir}`);
  } finally {
    staticServer.close();
    backend.kill("SIGTERM");
    await rm(dataDir, { recursive: true, force: true }).catch(() => {});
    await rm(reportsDir, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
