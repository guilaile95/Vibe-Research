/**
 * Candidate signal screener v0.1 — Playwright browser E2E (mock API).
 */

import { chromium } from "playwright";
import { createServer } from "node:http";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
  };
  const server = createServer((req, res) => {
    let pn = (req.url || "/").split("?")[0];
    if (pn === "/") pn = "/index.html";
    let target = path.join(dir, pn);
    const rd = path.resolve(dir);
    const rt = path.resolve(target);
    if (!rt.startsWith(rd + path.sep) && rt !== rd) {
      res.writeHead(403);
      res.end("forbidden");
      return;
    }
    if (!existsSync(target)) target = path.join(dir, "index.html");
    const ext = path.extname(target);
    res.setHeader("Content-Type", mime[ext] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function findChromium() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of candidates) {
    if (!base || !existsSync(base)) continue;
    try {
      for (const d of readdirSync(base)) {
        if (d.startsWith("chromium-") && !d.includes("headless")) {
          const exe = join(base, d, "chrome-win64", "chrome.exe");
          if (existsSync(exe)) return exe;
        }
      }
    } catch { /* ignore */ }
  }
  return undefined;
}

function sampleResult() {
  return {
    status: "partial",
    evaluated_at: "2026-07-31T12:00:00.000000Z",
    logic: "AND",
    matched: [
      {
        code: "000001",
        bucket: "matched",
        matched: true,
        technical_status: "normal",
        trade_date: "2026-07-30",
        condition_results: [
          {
            id: "price_gt_sma20",
            evaluable: true,
            passed: true,
            evidence: { close: 12.5, sma20: 11.8 },
          },
        ],
        limitations: [],
      },
    ],
    rejected: [
      {
        code: "600519",
        bucket: "rejected",
        matched: false,
        technical_status: "normal",
        trade_date: "2026-07-30",
        condition_results: [
          {
            id: "price_gt_sma20",
            evaluable: true,
            passed: false,
            evidence: { close: 10, sma20: 11 },
          },
        ],
        limitations: [],
      },
    ],
    unavailable: [
      {
        code: "000002",
        bucket: "unavailable",
        matched: null,
        technical_status: "unavailable",
        trade_date: null,
        condition_results: [],
        limitations: ["K 线数据不可用"],
      },
    ],
    limitations: [],
    schema_version: "screener-v0.1",
  };
}

async function main() {
  console.log("=== Screener E2E ===");
  if (!existsSync(frontendDist)) {
    throw new Error("frontend/dist missing — run npm run build first");
  }

  const port = await getFreePort();
  const server = await startStaticServer(frontendDist, port);
  const browser = await chromium.launch({ headless: true, executablePath: findChromium() });
  const page = await browser.newPage();

  let postCount = 0;
  let failOnce = false;

  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = req.url();
    if (url.includes("/api/screener/evaluate") && req.method() === "POST") {
      postCount++;
      if (failOnce) {
        failOnce = false;
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "筛选服务暂时不可用" }),
        });
        return;
      }
      // slight delay so double-click can race
      await sleep(80);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sampleResult()),
      });
      return;
    }
    if (url.includes("/api/watchlist")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { status: "valid", data: { codes: ["000001"], updated_at: "t" }, etag: "e" } }),
      });
      return;
    }
    if (url.includes("/api/portfolio")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { holdings: [{ code: "600519", shares: 100, cost: 1 }] } }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  try {
    await page.goto(`http://127.0.0.1:${port}/screener`);
    await page.waitForSelector("text=信号筛选");

    // Enter codes
    await page.locator("textarea").fill("000001 600519 000002");
    // default condition price_gt_sma20 already present
    await page.locator("button:has-text('运行筛选')").click();

    await page.waitForSelector("text=命中");
    await page.waitForSelector("text=000001");
    await page.waitForSelector("text=600519");
    await page.waitForSelector("text=000002");
    console.log("✓ multi-code three buckets visible");

    // Expand evidence
    await page.locator("button:has-text('000001')").first().click();
    await page.waitForSelector("text=sma20");
    console.log("✓ condition evidence expand");

    // Double click single-flight
    const before = postCount;
    await page.locator("button:has-text('运行筛选')").evaluate((el) => {
      el.click();
      el.click();
    });
    await sleep(400);
    if (postCount !== before + 1) {
      throw new Error(`expected single POST on double-click, got delta ${postCount - before}`);
    }
    console.log("✓ double-click single POST");

    // Partial already shown other stocks — re-assert groups
    await page.waitForSelector("text=不可评估");
    console.log("✓ partial response shows other stocks");

    // 500 preserves draft
    failOnce = true;
    const codeBefore = await page.locator("textarea").inputValue();
    await page.locator("button:has-text('运行筛选')").click();
    await page.waitForSelector("text=筛选服务暂时不可用");
    const codeAfter = await page.locator("textarea").inputValue();
    if (codeAfter !== codeBefore) {
      throw new Error("codes draft lost after 500");
    }
    // condition row still present
    await page.waitForSelector("text=价格 > SMA20");
    console.log("✓ 500 preserves codes and conditions");

    console.log("=== Screener E2E passed ===");
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((err) => {
  console.error("Screener E2E Failed:", err);
  process.exit(1);
});
