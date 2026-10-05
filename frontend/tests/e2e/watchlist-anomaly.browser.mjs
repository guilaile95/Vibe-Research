import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
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
  const externalRequests = [];
  const saveRequests = [];
  let watchCodes = ["600519", "000001", "837023"];
  let watchEtag = "e2e";
  let failSave = false;
  let anomalyMode = "normal";
  let releaseAnomalies;
  const screenshots = process.env.WATCHLIST_SCREENSHOT_DIR;
  if (screenshots) mkdirSync(screenshots, { recursive: true });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !/Failed to load resource.*(?:409|503)/.test(message.text())) pageErrors.push(message.text());
  });
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin === `http://127.0.0.1:${port}`) return route.continue();
    externalRequests.push(url.origin);
    // Keep the fixture offline without a font stylesheet abort polluting console health.
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ status: 200, contentType: "text/css", body: "" });
    return route.abort();
  });
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
      if (anomalyMode === "loading") await new Promise((resolve) => { releaseAnomalies = resolve; });
      if (anomalyMode === "error") return route.fulfill({ status: 503, json: { detail: "synthetic anomaly unavailable" } });
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
          type: "快速反弹", reason: anomalyMode === "missing-reason" ? "" : "盘中价格快速回升", keywords: [],
        }],
      } } });
    }
    if (path === "/api/watchlist") {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON();
        saveRequests.push(body);
        assert.equal(body.expected_etag, watchEtag, "save must use the authoritative ETag");
        if (failSave) return route.fulfill({ status: 409, json: { detail: "synthetic version conflict" } });
        watchCodes = body.codes;
        watchEtag = "e2e-saved";
        return route.fulfill({ json: { data: { codes: watchCodes, etag: watchEtag } } });
      }
      return route.fulfill({ json: { data: {
        status: "valid", data: { codes: watchCodes, updated_at: "2026-08-24 09:30:00" }, etag: watchEtag,
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
  const table = page.getByTestId("watchlist-anomaly-table");
  const layoutEvidence = [];
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    assert.equal(await table.count(), 1, "one shared table for every viewport");
    assert.equal(await table.getByRole("columnheader").count(), 6);
    assert.equal(await table.locator("tbody tr").count(), 3);
    for (const code of watchCodes) {
      const row = table.locator(`[data-watchlist-code="${code}"]`);
      assert.equal(await row.getByRole("cell").count(), 6);
      for (const [index, field] of ["stock", "price", "change", "amount", "anomaly", "action"].entries()) {
        assert.equal(await row.getByRole("cell").nth(index).getAttribute("headers"), `watchlist-${field}`);
      }
      for (const control of [row.getByRole("link", { name: code, exact: true }), row.getByTestId(`watchlist-candidate-${code}`), row.getByRole("button", { name: new RegExp(`移除 .*${code}`) })]) {
        const bounds = await control.boundingBox();
        assert.ok(bounds && bounds.height >= 44, `44px row touch target ${code} at ${viewport.width}px`);
        if (viewport.width < 768) assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= viewport.width, "row actions stay inside viewport");
      }
      if (viewport.width < 768) {
        for (const label of ["最新价", "涨跌幅", "成交额", "当日异动事实"]) assert.equal(await row.getByText(label, { exact: true }).isVisible(), true);
      }
    }
    const values = await table.locator('[data-watchlist-code="600519"] td').allTextContents();
    assert.match(values[1], /1300/);
    assert.match(values[2], /\+2.5%/);
    assert.match(values[3], /2.00 亿/);
    assert.match((await table.locator('[data-watchlist-code="000001"] td').allTextContents())[2], /-1%/);
    assert.equal(await table.locator('[data-watchlist-code="837023"] td').nth(1).innerText(), viewport.width < 768 ? "最新价\n—" : "—");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no page horizontal overflow");
    assert.ok(await page.getByRole("main").evaluate((element) => element.scrollWidth <= element.clientWidth), "no main horizontal overflow");
    const geometry = await table.evaluate((element) => ({ tableWidth: element.getBoundingClientRect().width, containerWidth: element.parentElement.clientWidth, containerScrollWidth: element.parentElement.scrollWidth }));
    assert.ok(geometry.containerScrollWidth <= geometry.containerWidth, "no table horizontal scrolling");
    layoutEvidence.push({ viewport, ...geometry, values });
    if (screenshots) {
      await page.getByRole("main").evaluate((element) => element.scrollTo(0, 0));
      await page.screenshot({ path: join(screenshots, `watchlist-after-${viewport.width}.png`), fullPage: true });
      await table.screenshot({ path: join(screenshots, `watchlist-records-after-${viewport.width}.png`) });
      if (viewport.width < 768) {
        // main owns scrolling: capture each complete record rather than a clipped whole table.
        for (const code of ["600519", "837023"]) {
          const row = table.locator(`[data-watchlist-code="${code}"]`);
          await row.evaluate((element) => element.scrollIntoView({ block: "center" }));
          await row.screenshot({ path: join(screenshots, `watchlist-row-${code}-after-${viewport.width}.png`) });
          await page.screenshot({ path: join(screenshots, `watchlist-row-${code}-viewport-after-${viewport.width}.png`) });
        }
      }
    }
  }
  await page.getByLabel("仅看有异动").check();
  assert.equal(await page.locator("tbody tr").count(), 1);
  await page.getByRole("link", { name: "600519", exact: true }).click();
  await page.waitForURL("**/stock-data?code=600519");
  await page.locator('[data-active-code="600519"]').waitFor();
  // Missing reasons, initial loading and unavailable data retain their distinct meanings.
  anomalyMode = "missing-reason";
  await page.goto(`http://127.0.0.1:${port}/watchlist`, { waitUntil: "networkidle" });
  await page.getByText("当前数据源未提供原因", { exact: true }).waitFor();
  anomalyMode = "loading";
  await page.reload({ waitUntil: "domcontentloaded" });
  await table.getByText("读取中…", { exact: true }).first().waitFor();
  assert.equal(await page.getByLabel("仅看有异动").isDisabled(), true);
  anomalyMode = "normal";
  releaseAnomalies();
  await table.getByText("盘中价格快速回升", { exact: true }).waitFor();
  anomalyMode = "error";
  await page.getByLabel("刷新行情与异动", { exact: true }).click();
  await table.getByText("异动数据暂不可用", { exact: true }).first().waitFor();
  assert.equal(await table.locator("tbody tr").count(), 3);
  assert.equal(await page.getByLabel("仅看有异动").isDisabled(), true);
  if (screenshots) await table.screenshot({ path: join(screenshots, "watchlist-unavailable-after-320.png") });

  // Successful and conflicting saves both return keyboard focus to the stable heading.
  anomalyMode = "normal";
  await page.getByLabel("刷新行情与异动", { exact: true }).click();
  await table.getByText("盘中价格快速回升", { exact: true }).waitFor();
  await table.getByRole("button", { name: "移除 平安银行（000001）", exact: true }).click();
  await table.locator('[data-watchlist-code="000001"]').waitFor({ state: "detached" });
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-testid") === "watchlist-list-heading");
  await page.getByRole("status").getByText("已移除 000001（后端权威）", { exact: true }).waitFor();
  failSave = true;
  await table.getByRole("button", { name: "移除 股票（837023）", exact: true }).click();
  await page.getByRole("status").getByText(/synthetic version conflict/).waitFor();
  await table.locator('[data-watchlist-code="837023"]').waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-testid") === "watchlist-list-heading");
  assert.deepEqual(watchCodes, ["600519", "837023"], "failed save reloads the authoritative list");
  assert.equal(saveRequests.length, 2);
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-watchlist")), null);
  assert.ok(externalRequests.every((origin) => origin === "https://fonts.googleapis.com"), "only known font stylesheet requests may be fulfilled locally; all external requests are intercepted");
  if (screenshots) {
    await page.screenshot({ path: join(screenshots, "watchlist-remove-conflict-after-320.png"), fullPage: true });
    writeFileSync(join(screenshots, "watchlist-after-layout.json"), JSON.stringify({ layoutEvidence, saveRequests, focus: await page.getByTestId("watchlist-list-heading").evaluate((element) => document.activeElement === element), pageErrors, externalRequests }, null, 2));
  }
  assert.deepEqual(pageErrors, []);
  console.log("watchlist anomaly browser vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
