// QA-RACE-01: synthetic frontend navigation only; never contacts a market/model backend.
import assert from "node:assert/strict";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dist = fileURLToPath(new URL("../../dist/", import.meta.url));
assert.ok(existsSync(resolve(dist, "index.html")), "Build frontend/dist before running this check");
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
const server = createServer((request, response) => {
  let target = resolve(dist, `.${new URL(request.url, "http://localhost").pathname}`);
  if (!target.startsWith(resolve(dist) + sep)) { response.writeHead(403).end(); return; }
  if (!existsSync(target) || !extname(target)) target = resolve(dist, "index.html");
  response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
  createReadStream(target).pipe(response);
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const base = `http://127.0.0.1:${server.address().port}`;
let browser;
const counts = new Map();
let delayNextA = false;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const stages = [];
try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
  });
  const context = await browser.newContext();
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== base) { await route.abort(); return; }
    if (!url.pathname.startsWith("/api/")) { await route.continue(); return; }
    const code = url.searchParams.get("code") || url.searchParams.get("symbol");
    const key = `${url.pathname}:${code}`;
    counts.set(key, (counts.get(key) || 0) + 1);
    if (url.pathname === "/api/valuation") {
      if (code === "000001" && delayNextA) { delayNextA = false; await sleep(650); }
      await route.fulfill({ json: { code, name: `Synthetic ${code}`, price: 10,
        pe_ttm: 10, pb: 1, mcap_yi: 1, analyst_count: 0 } });
    } else if (url.pathname === "/api/global/stock") {
      await route.fulfill({ json: { code, name: `Synthetic ${code}`,
        market: code === "00700" ? "HK" : code.endsWith(".KS") ? "KR" : "US",
        quote: { price: 10, change_pct: 0, mcap: null, amount: null }, metrics: null } });
    } else {
      await route.fulfill({ status: 503, json: { detail: "Synthetic optional source unavailable" } });
    }
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const count = (code) => counts.get(`${/^\d{6}$/.test(code) ? "/api/valuation" : "/api/global/stock"}:${code}`) || 0;
  const input = page.getByPlaceholder("A 股 6 位代码", { exact: false });
  const state = async (code) => {
    await page.waitForFunction((expected) => document.querySelector("[data-active-code]")?.getAttribute("data-active-code") === expected, code);
    await page.getByRole("heading", { name: `Synthetic ${code}`, exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("code"), code);
    assert.equal(await input.inputValue(), code);
  };
  const query = async (code) => {
    await input.fill(code);
    const path = /^\d{6}$/.test(code) ? "/api/valuation" : "/api/global/stock";
    await Promise.all([
      page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === path && (url.searchParams.get("code") || url.searchParams.get("symbol")) === code;
      }),
      input.press("Enter"),
    ]);
    await state(code);
  };
  const returnTo = "/screener?scope=synthetic";
  const entry = `${base}/stock-data?return_to=${encodeURIComponent(returnTo)}&qa=keep#synthetic`;
  await page.goto(entry);
  await input.waitFor();
  await query("000001");
  assert.equal(count("000001"), 1);
  await input.fill("000002");
  assert.equal(new URL(page.url()).searchParams.get("code"), "000001");
  await input.press("Enter");
  await state("000002");
  assert.equal(count("000002"), 1, "URL effect must not duplicate submitted query");
  assert.equal(new URL(page.url()).searchParams.get("return_to"), returnTo);
  assert.equal(new URL(page.url()).searchParams.get("qa"), "keep");
  assert.equal(new URL(page.url()).hash, "#synthetic");
  stages.push("query binding, one request, safe return/context/hash");

  await page.goBack(); await state("000001");
  await page.goForward(); await state("000002");
  const historyLength = await page.evaluate(() => history.length);
  const beforeRetry = count("000002");
  await query("000002");
  await page.waitForFunction(() => !!document.querySelector("h2"));
  assert.equal(count("000002"), beforeRetry + 1);
  assert.equal(await page.evaluate(() => history.length), historyLength);
  stages.push("Back/Forward and same-code retry history policy");

  await page.reload(); await state("000002");
  await page.getByTestId("stock-data-candidate-entry").click();
  await page.waitForURL("**/candidates/000002?**");
  await page.goBack(); await state("000002");
  assert.equal(new URL(page.url()).searchParams.get("return_to"), returnTo);
  stages.push("reload and candidate Back restore B");

  for (const code of ["AAPL", "00700", "005930.KS"]) {
    const before = count(code);
    await query(code);
    assert.equal(count(code), before + 1);
    await page.reload(); await state(code);
    assert.equal(count(code), before + 2);
  }
  stages.push("US/HK/KR submitted symbols and URL reload");

  delayNextA = true;
  await input.fill("000001"); await input.press("Enter");
  await page.waitForFunction(() => document.querySelector("[data-active-code]")?.getAttribute("data-active-code") === "000001");
  await query("000002");
  await sleep(800); await state("000002");
  await page.goBack(); await state("000001");
  await page.goForward(); await state("000002");
  stages.push("delayed A cannot overwrite B; Back/Forward after race");

  await page.goto(entry);
  await input.waitFor();
  delayNextA = true;
  await input.fill("000001"); await input.press("Enter");
  await page.waitForFunction(() => !!document.querySelector("[data-active-code]"));
  await page.goBack();
  await page.waitForFunction(() => !document.querySelector("[data-active-code]"));
  await sleep(800);
  assert.equal(await page.getByRole("heading", { name: "Synthetic 000001", exact: true }).count(), 0);
  assert.equal(await input.inputValue(), "");
  stages.push("Back to empty query invalidates pending A");

  for (let cycle = 0; cycle < 8; cycle++) {
    await query("000001"); await query("000002");
    await page.goBack(); await state("000001");
    await page.goForward(); await state("000002");
  }
  stages.push("8 bounded A/B/Back/Forward cycles");
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ result: "PASS", browser: browser.version(), stages, counts: Object.fromEntries(counts) }));
} finally {
  if (browser) await browser.close();
  await new Promise((done) => server.close(done));
}
