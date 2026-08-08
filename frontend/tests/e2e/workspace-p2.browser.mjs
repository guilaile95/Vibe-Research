import { chromium } from "playwright";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

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

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  };

  const server = createServer((req, res) => {
    let pathname = (req.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403);
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || path.extname(target) === "") {
      target = path.join(dir, "index.html");
    }
    res.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

const json = (body, wrap = true, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(wrap ? { data: body } : body),
});

function overviewFixture() {
  return {
    trade_date: "2026-08-08",
    market_short: { status: "normal", warnings: [], data: { breadth: null, emotion: null } },
    account_funding: { configured: false, status: "not_configured", data: null },
    advice: null,
    current_plan: null,
    candidate_pool: [],
    warnings: [],
  };
}

function todayActionsFixture() {
  return {
    trade_date: "2026-08-08",
    as_of: "2026-08-08 17:30:00",
    plan: null,
    plan_note: "测试环境",
    holdings: [
      {
        code: "001896",
        name: "豫能控股",
        shares: 1000,
        price: 8.2,
        change_pct: 3.1,
        pnl_pct: 6.8,
        plan_signals_summary: "已有计划信号",
        advice_action: "减仓检查",
        advice_qty: null,
        flags: ["风险信号升高"],
      },
      {
        code: "601991",
        name: "大唐发电",
        shares: 2000,
        price: 3.4,
        change_pct: -0.8,
        pnl_pct: 2.1,
        plan_signals_summary: null,
        advice_action: "持有",
        advice_qty: null,
        flags: ["板块波动扩大"],
      },
    ],
    watchlist_movers: [
      {
        code: "600519",
        name: "贵州茅台",
        price: 1518,
        change_pct: 1.2,
        flag: "估值分位变化",
      },
    ],
    warnings: [],
  };
}

async function installApiMocks(page) {
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;

    if (p.includes("/decision-cockpit/overview")) {
      await route.fulfill(json(overviewFixture()));
      return;
    }
    if (p.includes("/decision-cockpit/tomorrow-plan/current")) {
      await route.fulfill(json(null));
      return;
    }
    if (p.includes("/decision-cockpit/today-actions")) {
      await route.fulfill(json(todayActionsFixture()));
      return;
    }
    if (p.endsWith("/watchlist")) {
      await route.fulfill(json({ status: "valid", data: { codes: [], updated_at: "2026-08-08T09:00:00Z" }, etag: "e1" }, false));
      return;
    }

    if (p.endsWith("/valuation")) {
      await route.fulfill(json({
        code: "600519",
        name: "贵州茅台",
        price: 1518,
        pe_ttm: 25.4,
        pb: 8.1,
        mcap_yi: 19000,
        eps_26e: 75,
        pe_26e: 20.2,
        peg: 1.4,
        digest_years: 2,
        analyst_count: 18,
        forecast_note: null,
      }));
      return;
    }
    if (p.includes("percentile")) {
      await route.fulfill(json(null));
      return;
    }
    if (p.includes("financial")) {
      await route.fulfill(json({
        period: "2026Q2",
        revenue: "890.2亿",
        revenue_yoy: "+10.2%",
        net_profit: "451.0亿",
        net_profit_yoy: "+8.6%",
        eps: "35.91",
        roe: "20.1%",
        gross_margin: "91.4%",
        net_margin: "50.7%",
        bvps: "210.1",
        op_cf_ps: "31.8",
      }));
      return;
    }
    if (p.includes("reports")) {
      await route.fulfill(json([{
        publishDate: "2026-08-07",
        orgSName: "示例机构",
        title: "经营质量保持稳定",
        pdfUrl: "",
        emRatingName: "增持",
      }]));
      return;
    }
    if (p.includes("announcements")) {
      await route.fulfill(json([{
        date: "2026-08-07",
        type: "公告",
        title: "贵州茅台：示例公告",
        url: "",
      }]));
      return;
    }
    if (p.includes("news")) {
      await route.fulfill(json([]));
      return;
    }
    if (p.includes("margin")) {
      await route.fulfill(json([{ date: "2026-08-07", rzye: 1200000000, rqye: 10000000 }]));
      return;
    }
    if (p.includes("holder")) {
      await route.fulfill(json([{ holder_num: 168000, change_ratio: -1.2 }]));
      return;
    }
    if (p.includes("fund") && p.includes("flow")) {
      await route.fulfill(json([{ date: "2026-08-07", main_net: 180000000 }]));
      return;
    }
    if (p.includes("dragon")) {
      await route.fulfill(json({ records: [], seats: { buy: [], sell: [] } }));
      return;
    }
    if (p.includes("lockup")) {
      await route.fulfill(json({ upcoming: [], history: [] }));
      return;
    }
    if (p.includes("blocks")) {
      await route.fulfill(json({ concept_tags: ["白酒", "高股息"] }));
      return;
    }
    if (p.includes("top-risk") || p.includes("technical-indicators")) {
      await route.fulfill(json({ detail: "测试环境不提供该数据" }, false, 501));
      return;
    }
    if (p.includes("portfolio")) {
      await route.fulfill(json({ holdings: [] }));
      return;
    }

    await route.fulfill(json([]));
  });
}

async function assertNoHorizontalOverflow(page, label) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  if (scrollWidth > clientWidth + 2) {
    throw new Error(`${label}: horizontal overflow ${scrollWidth} > ${clientWidth}`);
  }
}

async function assertViewportScrollLocked(page, label) {
  const metrics = await page.evaluate(() => {
    const scrolling = document.scrollingElement || document.documentElement;
    return {
      scrollHeight: scrolling.scrollHeight,
      clientHeight: scrolling.clientHeight,
      scrollY: window.scrollY,
    };
  });
  if (metrics.scrollHeight > metrics.clientHeight + 2 || metrics.scrollY !== 0) {
    throw new Error(
      `${label}: document escaped viewport (${metrics.scrollHeight}/${metrics.clientHeight}, scrollY=${metrics.scrollY})`,
    );
  }
}

async function assertSidebarBehavior(page) {
  const sidebarNav = page.locator('nav[aria-label="主导航"]');
  await sidebarNav.waitFor();

  if ((await sidebarNav.getByText("复盘", { exact: true }).count()) !== 1) {
    throw new Error("primary navigation did not rename 今天 to 复盘");
  }
  if ((await sidebarNav.getByText("今天", { exact: true }).count()) !== 0) {
    throw new Error("legacy 今天 label is still present in primary navigation");
  }

  for (const label of ["资料", "分析"]) {
    const toggle = sidebarNav.getByRole("button", { name: label, exact: true });
    if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  }

  await sidebarNav.evaluate((node) => {
    node.scrollTop = node.scrollHeight;
  });
  const box = await sidebarNav.boundingBox();
  if (!box) throw new Error("sidebar navigation has no layout box");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, 5000);
  await page.waitForTimeout(50);
  await assertViewportScrollLocked(page, "sidebar scroll containment");
}

async function runStockWorkspace(page, baseUrl) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/stock-data`, { waitUntil: "networkidle" });

  const workflow = page.locator('nav[aria-label="研究链路"]');
  await workflow.waitFor();
  for (const label of ["研究", "筛选", "逻辑", "依据", "持仓", "复盘"]) {
    if ((await workflow.getByText(label, { exact: true }).count()) !== 1) {
      throw new Error(`research workflow missing ${label}`);
    }
  }

  await assertSidebarBehavior(page);

  const privacy = page.getByRole("button", { name: "开启隐私模式" });
  await privacy.click();
  const privacyState = await page.locator("html").getAttribute("data-privacy-mode");
  if (privacyState !== "true") throw new Error("privacy mode did not enable");
  const inputFilter = await page.locator('input[placeholder*="A 股"]').evaluate((el) => getComputedStyle(el).filter);
  if (!inputFilter.includes("blur")) throw new Error(`privacy mode did not mask input: ${inputFilter}`);
  await page.getByRole("button", { name: "关闭隐私模式" }).click();

  const input = page.locator('input[placeholder*="A 股"]');
  await input.fill("600519");
  await page.getByRole("button", { name: "查询" }).click();
  await page.locator('[data-active-code="600519"]').waitFor();

  const rail = page.locator('aside[aria-label="股票工作区导航"]');
  await rail.waitFor();
  for (const label of ["概览", "基本面", "研究", "资金", "逻辑"]) {
    if ((await rail.getByRole("button", { name: label, exact: true }).count()) !== 1) {
      throw new Error(`stock workspace missing ${label}`);
    }
  }

  await rail.getByRole("button", { name: "研究", exact: true }).click();
  if ((await page.evaluate(() => window.location.hash)) !== "#research") {
    throw new Error("stock workspace did not persist section hash");
  }
  await assertNoHorizontalOverflow(page, "stock desktop");
  await assertViewportScrollLocked(page, "stock desktop shell");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "networkidle" });
  await page.locator('input[placeholder*="A 股"]').fill("600519");
  await page.getByRole("button", { name: "查询" }).click();
  await page.locator('aside[aria-label="股票工作区导航"]').waitFor();
  await assertNoHorizontalOverflow(page, "stock mobile");
  await assertViewportScrollLocked(page, "stock mobile shell");
}

async function runScreener(page, baseUrl) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${baseUrl}/screener`, { waitUntil: "networkidle" });
  const workflow = page.locator('nav[aria-label="研究链路"]');
  await workflow.waitFor();
  const current = workflow.locator('[aria-current="page"]');
  if ((await current.textContent())?.trim() !== "筛选") throw new Error("screener workflow context lost");
  await assertNoHorizontalOverflow(page, "screener desktop");
  await assertViewportScrollLocked(page, "screener desktop shell");
}

async function runDecisionWorkspace(page, baseUrl) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/cockpit`, { waitUntil: "networkidle" });

  const rail = page.locator('aside[aria-label="今日优先事项"]');
  await rail.waitFor();
  await rail.getByText("豫能控股", { exact: true }).waitFor();
  await rail.getByText("大唐发电", { exact: true }).waitFor();
  await rail.getByText("贵州茅台", { exact: true }).waitFor();
  if ((await rail.getByText("只排列后端已有 action / flag，不生成新的交易建议。", { exact: true }).count()) !== 1) {
    throw new Error("priority rail disclaimer missing");
  }
  await assertNoHorizontalOverflow(page, "cockpit desktop");
  await assertViewportScrollLocked(page, "cockpit desktop shell");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "networkidle" });
  await page.locator('aside[aria-label="今日优先事项"]').waitFor();
  await assertNoHorizontalOverflow(page, "cockpit mobile");
  await assertViewportScrollLocked(page, "cockpit mobile shell");
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error("frontend/dist missing — run npm run build first");
  }

  const port = await getFreePort();
  const server = await startStaticServer(frontendDist, port);
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await installApiMocks(page);

  try {
    const baseUrl = `http://127.0.0.1:${port}`;
    await runStockWorkspace(page, baseUrl);
    await runScreener(page, baseUrl);
    await runDecisionWorkspace(page, baseUrl);
    if (pageErrors.length) {
      throw new Error(`page errors:\n${pageErrors.join("\n")}`);
    }
    console.log("PASS P2 workspace browser acceptance: sidebar/stock/screener/cockpit desktop+mobile");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
