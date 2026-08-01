/**
 * Northbound turnover history chart E2E — pure frontend + Playwright page.route mocks.
 *
 * Architecture:
 * - Playwright loads the Vite build from a Node static server (frontend/dist only)
 * - ALL /api/* traffic is intercepted via page.route (NO real backend / NO Python)
 * - Asserts DailyReview chart title, SVG points, tooltips, and request contract
 */
import { chromium } from "playwright";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

let frontendPort = 0;
let browserLabel = "unknown";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

function startStaticServer(dir, port) {
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
      res.writeHead(404, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ detail: "use page.route mocks" }));
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

function jsonOk(body) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data: body }),
  };
}

/** 20 consecutive valid trading-day-like dates for fixture. */
const HISTORY_DATES = [
  "2026-07-03", "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09",
  "2026-07-10", "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16",
  "2026-07-17", "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
  "2026-07-24", "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30",
];

function historyEnvelope() {
  const series = HISTORY_DATES.map((d, i) => ({
    trade_date: d,
    total_turnover_mn: 100000 + i * 1234.5,
    trade_count: 10_000_000 + i * 1000,
    etf_turnover_mn: 1000 + i * 10.25,
  }));
  return {
    schema_version: "northbound-history-v0.1",
    source: "HKEX Stock Connect Daily Statistics",
    source_tier: "authoritative",
    status: "normal",
    fetched_at: "2026-08-01T00:00:00+00:00",
    requested_days: 20,
    returned_points: 20,
    limitations: [
      {
        field: "series[].net_buy_mn",
        reason_code: "UNVERIFIED_SOURCE_SEMANTICS",
        detail:
          "HKEX payload 可能包含 Buy/Sell Turnover，但本版本未验证其历史单位与口径一致性，因此北向成交历史接口不提供净买入字段。",
      },
    ],
    series,
  };
}

function dailyReviewMinimal() {
  return {
    trade_date: "2026-07-30",
    market_snapshot: [],
    board_rankings: { industry: [], concept: [], region: [] },
    highlights: {},
    high_turnover: [],
    notes: "",
  };
}

function northboundDailyMinimal() {
  return {
    schema_version: "northbound-capital-flow-v0.1",
    source: "HKEX Stock Connect Daily Statistics",
    source_tier: "authoritative",
    trade_date: "2026-07-30",
    fetched_at: "2026-08-01T00:00:00+00:00",
    status: "normal",
    is_stale: false,
    currency: "CNY",
    amount_unit: "million",
    warnings: [],
    limitations: [],
    data: {
      northbound: {
        total_turnover_mn: 300000,
        trade_count: 1000,
        etf_turnover_mn: 100,
        net_buy_mn: null,
      },
      shanghai_connect: {
        market: "SSE",
        total_turnover_mn: 150000,
        trade_count: 500,
        etf_turnover_mn: 50,
        daily_quota_balance_mn: null,
        net_buy_mn: null,
      },
      shenzhen_connect: {
        market: "SZSE",
        total_turnover_mn: 150000,
        trade_count: 500,
        etf_turnover_mn: 50,
        daily_quota_balance_mn: null,
        net_buy_mn: null,
      },
      active_stocks: [],
    },
  };
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error("frontend/dist missing; run npm run build first");
  }

  frontendPort = await getFreePort();
  const staticServer = await startStaticServer(frontendDist, frontendPort);
  const errors = [];
  let historyCalls = 0;
  let historyDays = null;

  try {
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);
    const browser = await launchBrowser();
    try {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const page = await context.newPage();
      page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

      await page.route("**/api/**", async (route) => {
        const req = route.request();
        const url = req.url();
        let pathname = "/";
        let search = "";
        try {
          const u = new URL(url);
          pathname = u.pathname;
          search = u.search;
        } catch {
          /* ignore */
        }

        if (pathname.includes("/market/northbound/history")) {
          historyCalls += 1;
          const q = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
          historyDays = q.get("days");
          await route.fulfill(jsonOk(historyEnvelope()));
          return;
        }
        if (pathname.endsWith("/market/northbound") || pathname.includes("/market/northbound?")) {
          await route.fulfill(jsonOk(northboundDailyMinimal()));
          return;
        }
        if (pathname.includes("/daily-review/history")) {
          await route.fulfill(jsonOk({ items: [], total: 0, offset: 0, limit: 20 }));
          return;
        }
        if (pathname.includes("/daily-review")) {
          await route.fulfill(
            jsonOk({
              data: dailyReviewMinimal(),
              cache_meta: { stale: false, refresh_failed: false },
            }),
          );
          return;
        }
        if (pathname.includes("/watchlist")) {
          await route.fulfill(
            jsonOk({ codes: [], etag: "e0" }),
          );
          return;
        }
        if (pathname.includes("/quote")) {
          await route.fulfill(jsonOk({}));
          return;
        }
        // Stable default for any other DailyReview bootstrap calls.
        await route.fulfill(jsonOk({}));
      });

      await page.goto(`http://127.0.0.1:${frontendPort}/daily-review`, {
        waitUntil: "networkidle",
      });

      // Title / subtitle / disclaimer
      const title = page.getByText("北向成交额历史", { exact: true }).first();
      if (!(await title.isVisible().catch(() => false))) {
        errors.push("missing title 北向成交额历史");
      }
      const subtitle = page.getByText("近 20 个有效交易日 · HKEX 沪深股通成交额合计").first();
      if (!(await subtitle.isVisible().catch(() => false))) {
        errors.push("missing subtitle");
      }
      const disclaimer = page.getByText("成交额不代表净买入或净流入。").first();
      if (!(await disclaimer.isVisible().catch(() => false))) {
        errors.push("missing disclaimer");
      }

      const svg = page.locator('svg[aria-label="北向成交额历史折线图"]').first();
      if (!(await svg.isVisible().catch(() => false))) {
        errors.push("SVG role=img chart not visible");
      }

      const points = page.locator('[data-testid="northbound-turnover-point"]');
      const count = await points.count();
      if (count !== 20) {
        errors.push(`expected 20 points, got ${count}`);
      }

      if (count > 0) {
        const firstDate = await points.nth(0).getAttribute("data-date");
        const lastDate = await points.nth(count - 1).getAttribute("data-date");
        if (firstDate !== HISTORY_DATES[0]) {
          errors.push(`first data-date expected ${HISTORY_DATES[0]}, got ${firstDate}`);
        }
        if (lastDate !== HISTORY_DATES[HISTORY_DATES.length - 1]) {
          errors.push(`last data-date expected ${HISTORY_DATES[HISTORY_DATES.length - 1]}, got ${lastDate}`);
        }

        const firstTitle = (await points.nth(0).locator("title").textContent().catch(() => "")) || "";
        const lastTitle = (await points.nth(count - 1).locator("title").textContent().catch(() => "")) || "";
        for (const [label, tip, date] of [
          ["first", firstTitle, HISTORY_DATES[0]],
          ["last", lastTitle, HISTORY_DATES[HISTORY_DATES.length - 1]],
        ]) {
          if (!tip.includes(date) || !tip.includes("北向成交额") || !tip.includes("成交笔数") || !tip.includes("ETF 成交额")) {
            errors.push(`${label} tooltip missing required fields: ${JSON.stringify(tip)}`);
          }
        }
      }

      const bodyText = await page.locator("body").innerText();
      if (bodyText.includes("北向净买入历史")) {
        errors.push("forbidden label 北向净买入历史 present");
      }
      if (bodyText.includes("北向净流入历史")) {
        errors.push("forbidden label 北向净流入历史 present");
      }

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      if (scrollWidth > clientWidth + 2) {
        errors.push(`horizontal overflow scrollWidth=${scrollWidth} clientWidth=${clientWidth}`);
      }

      if (historyCalls !== 1) {
        errors.push(`history endpoint calls expected 1, got ${historyCalls}`);
      }
      if (historyDays !== "20") {
        errors.push(`history days expected 20, got ${historyDays}`);
      }

      await context.close();
    } finally {
      await browser.close().catch(() => {});
    }

    if (errors.length) {
      throw new Error(`northbound history e2e failed:\n${errors.join("\n")}`);
    }
    console.log(`PASS northbound history chart E2E (${browserLabel}) port=${frontendPort}`);
  } finally {
    await new Promise((resolve) => staticServer.close(resolve)).catch(() => {});
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
