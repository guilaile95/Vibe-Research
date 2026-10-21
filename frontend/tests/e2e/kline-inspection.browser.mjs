/** Synthetic component acceptance, not live-provider or cross-chart evidence.
 * Run: node tests/e2e/kline-inspection.browser.mjs
 * --build-only validates the fixture without opening sockets or launching a browser.
 */
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build, preview } from "vite";
import { chromium } from "playwright";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const outDir = await mkdtemp(path.join(tmpdir(), "kline-inspection-"));
await build({ root, build: { outDir, rollupOptions: { input: path.join(root, "tests/e2e/fixtures/kline-inspection.html") } } });
if (!process.argv.includes("--build-only")) {
  let browser;
  let server;
  try {
    server = await preview({ root, build: { outDir }, preview: { host: "127.0.0.1", port: 0, strictPort: false } });
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.route("**/api/research-events?**", (route) => route.fulfill({ json: { events: [], status: "NORMAL", limitations: [] } }));
    await page.route("**/api/evidence?**", (route) => route.fulfill({ json: { total: 1, items: [{ id: "fixture-missing", subject_type: "stock", subject_id: "000001", source_title: "Missing original day", source_date: "2026-01-11", classification: "FACT" }] } }));
    const address = server.httpServer.address();
    await page.goto(`http://127.0.0.1:${address.port}/tests/e2e/fixtures/kline-inspection.html`);
    const control = page.getByTestId("kline-inspection-control");
    const status = page.getByTestId("kline-inspection-status");
    await control.focus();
    await page.keyboard.press("Home");
    assert.match(await status.innerText(), /2026-01-05/);
    for (let i = 0; i < 70; i++) await page.keyboard.press("ArrowRight");
    assert.match(await status.innerText(), /2026-03-06/);
    assert.match(await status.innerText(), /未知 \/ 无效/);
    assert.equal(await control.evaluate((el) => el === document.activeElement), true);
    assert.equal(await page.getByTestId("kline-inspection-crosshair").count(), 1);
    await page.keyboard.press("Escape");
    assert.match(await status.innerText(), /尚未选择/);
    await page.keyboard.press("Tab");
    assert.equal(await control.evaluate((el) => el === document.activeElement), false);
    await page.getByText("查看可访问的 OHLCV 数据表", { exact: false }).click();
    await page.getByRole("button", { name: "2026-01-05", exact: true }).click();
    assert.match(await status.innerText(), /2026-01-05/);
    await page.getByRole("button", { name: "显示研究事件", exact: true }).click();
    await page.getByRole("button", { name: "检查原日期 2026-01-11", exact: true }).click();
    assert.match(await status.innerText(), /2026-01-11.*没有此日期/);
    assert.equal(await page.getByTestId("kline-inspection-crosshair").count(), 0);
    assert.match(await page.getByTestId("kline-selected-research").innerText(), /1 条精确日期匹配/);
    await page.getByRole("button", { name: "Correct data", exact: true }).click();
    assert.match(await status.innerText(), /尚未选择/);
    await control.click();
    await page.getByRole("button", { name: "Switch stock", exact: true }).click();
    assert.match(await status.innerText(), /尚未选择/);
    await page.getByRole("button", { name: "Switch period", exact: true }).click();
    assert.equal(await control.count(), 0);
    assert.match(await page.locator("main").innerText(), /仅支持日 K 线/);
    await page.getByRole("button", { name: "Switch period", exact: true }).click();
    await page.setViewportSize({ width: 375, height: 800 });
    await page.getByText("查看可访问的 OHLCV 数据表", { exact: false }).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole("button", { name: "Empty data", exact: true }).click();
    assert.equal(await control.count(), 0);
    assert.match(await page.locator("main").innerText(), /无有效 K 线数据/);
    console.log("PASS: synthetic chart keyboard, focus, context reset, OHLCV, mobile and empty acceptance");
  } finally {
    await browser?.close();
    await new Promise((resolve) => server ? server.httpServer.close(resolve) : resolve());
  }
}
