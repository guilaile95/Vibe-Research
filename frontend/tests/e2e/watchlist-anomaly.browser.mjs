import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = join(fileURLToPath(import.meta.url), "..");
const dist = join(here, "../../dist");

function chromiumPath() {
  const roots = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  const candidates = [];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    for (const item of readdirSync(base)) {
      if (!/^chromium(_headless_shell)?-\d+$/.test(item)) continue;
      candidates.push(
        join(base, item, "chrome-win64", "chrome.exe"),
        join(base, item, "chrome-win", "chrome.exe"),
        join(base, item, "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
      );
    }
  }
  return candidates.filter((candidate) => existsSync(candidate)).sort().at(-1);
}

async function launchBrowser() {
  const executablePath = chromiumPath();
  try {
    return await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  } catch {
    return chromium.launch({ headless: true, channel: "chrome" });
  }
}

async function freePort() {
  const server = createServer();
  const port = await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function staticServer(directory, port) {
  const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" };
  const server = createServer((request, response) => {
    let pathname = decodeURIComponent((request.url || "/").split("?")[0]);
    if (pathname === "/") pathname = "/index.html";
    let target = join(directory, pathname);
    if (!existsSync(target) || extname(target) === "") target = join(directory, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

let server;
let browser;
try {
  assert.ok(existsSync(join(dist, "index.html")), "dist/index.html missing; run npm run build");
  const port = await freePort();
  server = await staticServer(dist, port);
  browser = await launchBrowser();
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/native-intel/watchlist-context") {
      return route.fulfill({ json: { data: {
        status: "partial",
        retrieved_at: "2026-08-27T16:00:00Z",
        authority_ref: "vibe:native_intel:v0.1",
        usage_boundary: "observation_only_not_an_investment_authority",
        watchlist_status: "valid",
        codes: ["600519", "000001", "837023"],
        degraded: [{ code: "837023", error: "mapping_partial" }],
        securities: [
          {
            code: "600519", company_name: "贵州茅台", mention_count: 1, source_count: 1,
            first_seen_at: "2026-08-27T09:00:00Z", last_seen_at: "2026-08-27T09:30:00Z",
            items: [{ item_id: 1, title: "白酒行业公开资讯", url: "https://example.test/news", source_id: "official-rss", source_name: "官方 RSS", hint: "a-share", first_seen_at: "2026-08-27T09:00:00Z", last_seen_at: "2026-08-27T09:30:00Z", observation_count: 1 }],
          },
          {
            code: "000001", company_name: "平安银行", mention_count: 0, source_count: 0, items: [],
          },
          {
            code: "837023", company_name: null, mention_count: 0, source_count: 0, items: [],
          },
        ],
      } } });
    }
    if (path === "/api/watchlist/anomalies") {
      return route.fulfill({ json: { data: {
        provider_id: "hithink_financial_api",
        provider_contract: "hithink-watchlist-anomalies-v0.1",
        as_of_ms: 1787529600000,
        unavailable_codes: ["837023"],
        items: [{
          code: "600519", provider_symbol: "600519.SH", name: "贵州茅台",
          type: "大幅上涨", reason: "成交活跃且价格快速上行", keywords: ["白酒"],
        }, {
          code: "600519", provider_symbol: "600519.SH", name: "贵州茅台",
          type: "快速反弹", reason: "盘中价格快速回升", keywords: [],
        }],
      } } });
    }
    if (path === "/api/watchlist") {
      return route.fulfill({ json: { data: {
        status: "valid", data: { codes: ["600519", "000001", "837023"], updated_at: "2026-08-24 09:30:00" }, etag: "e2e",
      } } });
    }
    if (path === "/api/quote") {
      return route.fulfill({ json: { data: {
        "600519": { name: "贵州茅台", price: 1300, change_pct: 2.5, amount_wan: 20_000 },
        "000001": { name: "平安银行", price: 11, change_pct: -1, amount_wan: 30_000 },
      } } });
    }
    return route.fulfill({ status: 503, json: { detail: "offline e2e fixture" } });
  });

  await page.goto(`http://127.0.0.1:${port}/watchlist`, { waitUntil: "networkidle" });
  await page.getByTestId("native-intel-watchlist-context").waitFor();
  await page.getByText("1 条 / 1 源", { exact: true }).waitFor();
  await page.getByText("0 条 / 0 源", { exact: true }).first().waitFor();
  assert.equal(await page.locator('[data-watchlist-intel-code="600519"]').count(), 1);
  assert.equal(await page.getByText("不修改自选、论点或决策", { exact: false }).count(), 1);
  await page.getByText("成交活跃且价格快速上行", { exact: true }).waitFor();
  await page.getByText("盘中价格快速回升", { exact: true }).waitFor();
  assert.equal(await page.getByText("当前数据源未返回异动记录", { exact: true }).count(), 1);
  assert.equal(await page.getByText("当前数据源未覆盖该标的异动查询", { exact: true }).count(), 1);
  await page.getByLabel("仅看有异动").check();
  assert.equal(await page.locator("tbody tr").count(), 1);
  await page.getByRole("link", { name: "600519", exact: true }).click();
  await page.waitForURL("**/stock-data?code=600519");
  await page.locator('[data-active-code="600519"]').waitFor();
  assert.deepEqual(pageErrors, []);
  console.log("watchlist anomaly browser vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
