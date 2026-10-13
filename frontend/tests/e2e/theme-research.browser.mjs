// Real production React component and API client under a synthetic date parent.
// No backend process, provider calls, credentials or production archive access.
// Run browser only in the authorized CI lane; --build-only never starts one.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "playwright";
import { dayA, dayB, themeReply, validThemeQuery, observeThemeReads } from "./theme-research.fixture.mjs";

const frontend = fileURLToPath(new URL("../../", import.meta.url));
const output = process.env.THEME_RESEARCH_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), "theme-research-dom-"));
mkdirSync(output, { recursive: true });
const dist = join(output, "component-dist");
process.chdir(frontend);
await build({ configFile: false, mode: "production", root: join(frontend, "tests/e2e/theme-research-adapter"),
  plugins: [react()], resolve: { alias: { "@": join(frontend, "src") } }, css: { postcss: frontend },
  build: { outDir: dist, emptyOutDir: true },
});
if (process.argv.includes("--build-only")) {
  console.log("Theme-research production component adapter built; browser NOT_RUN");
  process.exit(0);
}

const audit = { external: [], unexpected: [], reads: [], errors: [] };
const server = createServer((request, response) => {
  const pathname = new URL(request.url, "http://local").pathname;
  if (pathname === "/favicon.ico") { response.writeHead(204).end(); return; }
  const target = pathname === "/" ? join(dist, "index.html") : resolve(dist, "." + decodeURIComponent(pathname));
  if (request.method !== "GET" || !target.startsWith(resolve(dist) + sep) || !existsSync(target)
    || ![".html", ".js", ".css"].includes(extname(target))) {
    audit.unexpected.push(`static ${request.method} ${pathname}`); response.writeHead(404).end(); return;
  }
  response.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[extname(target)]);
  createReadStream(target).pipe(response);
});
const deferred = () => { let release; const promise = new Promise(resolve => { release = resolve; }); return { promise, release }; };
const bounded = async promise => {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error("Expected synthetic read did not arrive")), 10000); })]); }
  finally { clearTimeout(timer); }
};
const results = [];
let browser, status = "FAIL";
try {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: "block" });
    await context.addInitScript(observeThemeReads);
    await context.routeWebSocket("**/*", socket => { audit.external.push(`WebSocket ${socket.url()}`); socket.close(); });
    let mode = "normal", hold = null, readIndex = 0;
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== origin) { audit.external.push(request.url()); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      audit.reads.push(`${request.method()} ${url.pathname}${url.search}`);
      if (!validThemeQuery(request.method(), url.pathname, url.search)) {
        audit.unexpected.push(request.url()); return route.fulfill({ status: 400, json: { detail: "UNEXPECTED_SYNTHETIC_READ" } });
      }
      const index = readIndex++, date = url.searchParams.get("trade_date");
      const reply = themeReply(mode === "wrong-date" ? dayA : date, mode);
      if (hold && hold.date === date) {
        const selected = hold; hold = null; selected.index = index; selected.started.release();
        await selected.gate.promise;
      }
      return route.fulfill({ json: { data: reply } });
    });
    const page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => audit.errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") audit.errors.push(message.text()); });
    await page.goto(origin);
    const card = page.getByTestId("theme-research-card");
    await card.getByText("合成测试数据；未进行真实市场验收", { exact: true }).waitFor();
    assert.ok((await card.innerText()).includes("昨日题材"));
    await card.getByText("龙头谱系", { exact: false }).last().click();
    await card.getByText("至所选日 40.00%", { exact: false }).waitFor();
    await page.screenshot({ path: join(output, `theme-data-${width}.png`), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    results.push({ width, check: "actual API golden, fixed dates, disappeared theme and lineage" });
    for (const malformed of ["bad-source-date", "bad-seal", "bad-basis", "bad-name"]) {
      mode = malformed;
      await card.getByRole("button", { name: "重新读取题材归档" }).click();
      await card.getByRole("alert").waitFor();
      assert.equal(await card.locator("table").count(), 0);
    }
    mode = "normal";
    await card.getByRole("button", { name: "重新读取题材归档" }).click();
    await card.getByText("合成测试数据；未进行真实市场验收", { exact: true }).waitFor();
    results.push({ width, check: "malformed provenance rendered operands fail closed then recover without React crash" });
    mode = "partial";
    await card.getByRole("button", { name: "重新读取题材归档" }).click();
    await card.getByText("缺数", { exact: true }).waitFor();
    assert.ok((await card.innerText()).includes("未知"));
    results.push({ width, check: "missing session remains unknown, not zero" });
    mode = "unconnected";
    await card.getByRole("button", { name: "重新读取题材归档" }).click();
    await card.getByText("题材归档未连接", { exact: true }).waitFor();
    assert.equal(await card.locator("table").count(), 0);
    mode = "normal";
    await page.getByRole("button", { name: dayB, exact: true }).click();
    await card.getByText("合成测试数据；未进行真实市场验收", { exact: true }).waitFor();
    mode = "wrong-date";
    await card.getByRole("button", { name: "重新读取题材归档" }).click();
    await card.getByRole("alert").waitFor();
    assert.equal(await card.locator("table").count(), 0);
    results.push({ width, check: "unconnected and wrong-date responses hide old data" });
    mode = "normal";
    const pending = { date: dayA, started: deferred(), gate: deferred() };
    hold = pending;
    await page.getByRole("button", { name: dayA, exact: true }).click();
    await bounded(pending.started.promise);
    await page.getByRole("button", { name: dayB, exact: true }).click();
    await card.getByText("合成测试数据；未进行真实市场验收", { exact: true }).waitFor();
    pending.gate.release();
    await page.waitForFunction(i => window.__themeReads[i]?.parsed, pending.index);
    assert.equal(await page.evaluate(i => window.__themeReads[i].aborted, pending.index), true);
    assert.ok((await card.innerText()).includes(`交易日：${dayB}`));
    assert.ok(!(await card.innerText()).includes(`交易日：${dayA}`));
    await page.getByRole("button", { name: "清空日期" }).click();
    await card.getByText("等待页面交易日，未以今天代替", { exact: true }).waitFor();
    assert.equal(await card.locator("table").count(), 0);
    await page.getByRole("button", { name: "切换显示" }).click();
    assert.equal(await page.getByTestId("theme-research-card").count(), 0);
    results.push({ width, check: "late parsed response, abort, clear-date and unmount" });
    await page.screenshot({ path: join(output, `theme-${width}.png`), fullPage: true });
    await context.close();
  }
  assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, []); assert.deepEqual(audit.errors, []);
  assert.equal(results.length, 10); status = "PASS";
} finally {
  await browser?.close(); await new Promise(resolve => server.close(resolve));
  writeFileSync(join(output, "result.json"), JSON.stringify({ status, results, audit }, null, 2));
}
