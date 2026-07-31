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
  let sectorRepsFail = false;

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
    if (url.includes("/api/screener/sources/sector-representatives")) {
      if (sectorRepsFail) {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "读取板块代表公司失败" }),
        });
        return;
      }
      // Mock authoritative backend list (not frontend text scrape)
      const codes = Array.from({ length: 103 }, (_, i) => String(i + 1).padStart(6, "0"));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          codes,
          count: codes.length,
          schema_version: "screener-sources-v0.1",
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  try {
    await page.goto(`http://127.0.0.1:${port}/screener`);
    await page.waitForSelector("text=信号筛选");

    // --- Overflow: 31 unique codes must block run (no silent truncate) ---
    const thirtyOne = Array.from({ length: 31 }, (_, i) => String(i + 1).padStart(6, "0")).join(" ");
    await page.locator("textarea").fill(thirtyOne);
    await page.waitForSelector("text=已解析 31/30");
    await page.waitForSelector("text=最多 30 个代码");
    const runBtn = page.locator("button:has-text('运行筛选')");
    if (await runBtn.isEnabled()) {
      throw new Error("Run must be disabled when 31 unique codes present");
    }
    const postsBeforeOverflow = postCount;
    // force click even if disabled shouldn't fire — use evaluate only when enabled
    console.log("✓ 31 unique shows 31/30, error, run disabled");

    // 31 raw / 30 unique → allowed
    const thirtyRawDup = Array.from({ length: 30 }, (_, i) => String(i + 1).padStart(6, "0")).join(" ") + " 000001";
    await page.locator("textarea").fill(thirtyRawDup);
    await page.waitForSelector("text=已解析 30/30");
    if (!(await runBtn.isEnabled())) {
      throw new Error("Run must be enabled when 31 raw / 30 unique");
    }
    console.log("✓ 31 raw / 30 unique shows 30/30 and enables run");

    // --- Load-hint lifecycle: sector load → truncate hint → clear on edit/run ---
    await page.locator("button:has-text('从板块代表载入')").click();
    await page.waitForSelector("text=来源共有 103 个代码，本次载入前 30 个");
    console.log("✓ sector load shows truncate hint");

    await page.locator("textarea").fill("000001 600519");
    await sleep(100);
    if ((await page.locator("text=来源共有 103 个代码").count()) !== 0) {
      throw new Error("load hint must clear after manual code edit");
    }
    console.log("✓ manual edit clears load hint");

    await page.locator("button:has-text('从板块代表载入')").click();
    await page.waitForSelector("text=来源共有 103 个代码，本次载入前 30 个");
    await page.locator("button:has-text('添加条件')").click();
    await sleep(100);
    if ((await page.locator("text=来源共有 103 个代码").count()) !== 0) {
      throw new Error("load hint must clear after add condition");
    }
    console.log("✓ add condition clears load hint");

    // Remove extra condition if added (rsi_between) so default stays simple
    const trashBtns = page.locator("button[aria-label^='删除条件']");
    if ((await trashBtns.count()) > 1) {
      await trashBtns.last().click();
    }

    await page.locator("button:has-text('从板块代表载入')").click();
    await page.waitForSelector("text=来源共有 103 个代码，本次载入前 30 个");
    // Sector fail must not wipe codes
    const codesBeforeFail = await page.locator("textarea").inputValue();
    sectorRepsFail = true;
    await page.locator("button:has-text('从板块代表载入')").click();
    await page.waitForSelector("text=载入板块代表失败");
    const codesAfterFail = await page.locator("textarea").inputValue();
    if (codesAfterFail !== codesBeforeFail) {
      throw new Error("codes draft must be preserved on sector load failure");
    }
    sectorRepsFail = false;
    console.log("✓ sector load failure keeps codes and shows fixed error");

    // Reload success then clear on run
    await page.locator("button:has-text('从板块代表载入')").click();
    await page.waitForSelector("text=来源共有 103 个代码，本次载入前 30 个");
    // Use three codes for main flow
    await page.locator("textarea").fill("000001 600519 000002");
    // Enter codes for main flow
    // default condition price_gt_sma20 already present
    await page.locator("button:has-text('运行筛选')").click();
    await sleep(150);
    if ((await page.locator("text=来源共有 103 个代码").count()) !== 0) {
      throw new Error("load hint must clear after run");
    }
    console.log("✓ run clears load hint");

    await page.waitForSelector("text=命中");
    await page.waitForSelector("text=000001");
    await page.waitForSelector("text=600519");
    await page.waitForSelector("text=000002");
    if (postCount === postsBeforeOverflow) {
      throw new Error("expected POST after valid run");
    }
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
