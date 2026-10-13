// MARKET-02: production build, synthetic API only. Browser plugin not available.
// Flow: /stock-data -> overseas quote/financials -> initial guidance disappears;
// loading, failures, retry, missing metrics and history retain their own states.
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dist = fileURLToPath(new URL("../../dist/", import.meta.url));
assert.ok(existsSync(join(dist, "index.html")), "Build frontend/dist first");
const evidence = process.env.MARKET02_EVIDENCE_DIR;
if (evidence) mkdirSync(evidence, { recursive: true });
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
const server = createServer((request, response) => {
  let path = resolve(dist, `.${new URL(request.url, "http://localhost").pathname}`);
  if (!path.startsWith(resolve(dist) + sep)) return response.writeHead(403).end();
  if (!existsSync(path) || !extname(path)) path = join(dist, "index.html");
  response.setHeader("Content-Type", mime[extname(path)] || "application/octet-stream");
  createReadStream(path).pipe(response);
});
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function bounded(promise) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Held request did not start")), 10000); })]); }
  finally { clearTimeout(timer); }
}
const globalStock = (code, missing = false) => ({ code, name: `Synthetic ${code}`,
  market: code === "00700" ? "HK" : code.endsWith(".KS") ? "KR" : "US",
  quote: { price: 10, change_pct: 0, mcap: null, amount: null },
  metrics: missing ? null : { report_date: "2026-06-30", revenue: 1000000, net_profit: 0, eps: 0, roe: null } });
const results = [];
let browser;
try {
  await new Promise(done => server.listen(0, "127.0.0.1", done));
  const base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 950 }, serviceWorkers: "block" });
    const errors = [], unexpected = [], holds = [], checks = [];
    let nextHold = null, missingMetrics = false;
    const hold = fail => { const h = { fail, started: deferred(), release: deferred() }; holds.push(h); nextHold = h; return h; };
    await context.routeWebSocket("**/*", socket => { unexpected.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
      if (url.origin !== base) { unexpected.push(url.origin); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      assert.equal(request.method(), "GET", "This test must never write business state");
      const code = url.searchParams.get("code") || url.searchParams.get("symbol");
      if (url.pathname === "/api/global/stock") {
        const h = nextHold; nextHold = null;
        if (h) { h.started.resolve(); await h.release.promise; }
        return route.fulfill(h?.fail ? { status: 503, json: { detail: "MARKET02_SYNTHETIC_FAILURE" } } : { json: globalStock(code, missingMetrics) });
      }
      if (url.pathname === "/api/valuation") return route.fulfill({ json: { code, name: `Synthetic ${code}`, price: 10, pe_ttm: 10, pb: 1, mcap_yi: 1, analyst_count: 0 } });
      return route.fulfill({ status: 503, json: { detail: "Synthetic optional source unavailable" } });
    });
    const page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => errors.push(error.message));
    const input = page.getByPlaceholder("A 股 6 位代码", { exact: false });
    const prompt = page.getByText("输入一个 6 位股票代码，拉取它的行情、估值、研报与新闻。", { exact: false });
    const absent = async () => assert.equal(await prompt.count(), 0, "Initial guidance must be absent after a query starts or succeeds");
    const initial = async () => { await prompt.waitFor(); assert.equal(await input.inputValue(), ""); assert.equal(await page.locator("[data-active-code]").count(), 0); };
    const submit = async code => { await input.fill(code); await input.press("Enter"); };
    const loaded = async code => { await page.getByRole("heading", { name: `Synthetic ${code}`, exact: true }).waitFor(); assert.equal(new URL(page.url()).searchParams.get("code"), code); await absent(); };
    const settle = async h => {
      const response = page.waitForResponse(r => new URL(r.url()).pathname === "/api/global/stock");
      h.release.resolve(); await (await response).finished();
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    };
    try {
      // The original reproduction is first, so the unpatched build fails here.
      for (const code of ["AAPL", "00700", "005930.KS"]) {
        await page.goto(`${base}/stock-data?code=${code}`);
        await page.getByRole("heading", { name: `Synthetic ${code}`, exact: true }).waitFor();
        await page.getByRole("tab", { name: "财务与估值", exact: true }).click();
        await page.getByRole("heading", { name: /关键财务指标.*2026-06-30/ }).waitFor();
        if (evidence) await page.screenshot({ path: join(evidence, `${code}-${width}.png`) });
        await loaded(code);
        await page.reload(); await loaded(code);
        checks.push(`${code}: populated financials and reload suppress initial guidance`);
      }
      await page.goto(`${base}/stock-data`); await initial();
      const pending = hold(false); await submit("AAPL"); await bounded(pending.started.promise);
      assert.equal(await page.getByRole("button", { name: "查询", exact: true }).isDisabled(), true); await absent();
      await settle(pending); await loaded("AAPL");
      await page.goBack(); await initial(); await page.goForward(); await loaded("AAPL");
      checks.push("initial, loading, success, Back to entry and Forward");

      const failed = hold(true); await submit("AAPL"); await bounded(failed.started.promise); await absent();
      await settle(failed); await page.getByText("MARKET02_SYNTHETIC_FAILURE", { exact: true }).waitFor(); await absent();
      const historyLength = await page.evaluate(() => history.length);
      await submit("AAPL"); await loaded("AAPL");
      assert.equal(await page.evaluate(() => history.length), historyLength);
      checks.push("failure remains an error, same-code retry succeeds without extra history");

      missingMetrics = true; await submit("00700"); await loaded("00700");
      await page.getByRole("tab", { name: "财务与估值", exact: true }).click();
      await page.getByText("该页签当前没有可展示的数据。", { exact: true }).waitFor(); await absent();
      missingMetrics = false;
      await submit("000001"); await loaded("000001"); await submit("005930.KS"); await loaded("005930.KS");
      checks.push("missing metrics preserves quote and local empty panel; A-share/global transitions");

      for (const fail of [false, true]) {
        await page.goto(`${base}/stock-data`); await initial();
        const stale = hold(fail); await submit("AAPL"); await bounded(stale.started.promise); await absent();
        await page.goBack(); await initial(); await settle(stale); await initial();
        assert.equal(await page.getByRole("heading", { name: "Synthetic AAPL", exact: true }).count(), 0);
        assert.equal(await page.getByText("MARKET02_SYNTHETIC_FAILURE", { exact: true }).count(), 0);
        checks.push(`Back to empty invalidates stale ${fail ? "error" : "success"}`);
      }
      assert.equal(await page.locator("vite-error-overlay").count(), 0);
      assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
      results.push({ width, status: "PASS", checks, pageErrors: errors, externalRequests: unexpected });
    } catch (error) {
      results.push({ width, status: "FAIL", checks, error: error.message, pageErrors: errors, externalRequests: unexpected });
      if (evidence) await page.screenshot({ path: join(evidence, `failure-${width}.png`) });
      throw error;
    } finally {
      for (const h of holds) h.release.resolve();
      await context.close();
    }
  }
  console.log(JSON.stringify({ result: "PASS", browser: browser.version(), results }));
} finally {
  if (evidence) writeFileSync(join(evidence, "results.json"), JSON.stringify({ head: process.env.MARKET02_PR_HEAD || null, results }, null, 2));
  if (browser) await browser.close();
  await new Promise(done => server.close(done));
}
