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
import { dayA, dayB, sealReply, validSealQuery, observeSealReads } from "./seal-quality.fixture.mjs";

const frontend = fileURLToPath(new URL("../../", import.meta.url));
const output = process.env.SEAL_QUALITY_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), "seal-quality-dom-"));
mkdirSync(output, { recursive: true });
const dist = join(output, "component-dist");
process.chdir(frontend);
await build({ configFile: false, mode: "production", root: join(frontend, "tests/e2e/seal-quality-adapter"),
  plugins: [react()], resolve: { alias: { "@": join(frontend, "src") } }, css: { postcss: frontend },
  build: { outDir: dist, emptyOutDir: true },
});
if (process.argv.includes("--build-only")) {
  console.log("Seal-quality production component adapter built; browser NOT_RUN");
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
    await context.addInitScript(observeSealReads);
    await context.routeWebSocket("**/*", socket => { audit.external.push(`WebSocket ${socket.url()}`); socket.close(); });
    let mode = "normal", hold = null, readIndex = 0;
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== origin) { audit.external.push(request.url()); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      audit.reads.push(`${request.method()} ${url.pathname}${url.search}`);
      if (!validSealQuery(request.method(), url.pathname, url.search)) {
        audit.unexpected.push(request.url()); return route.fulfill({ status: 400, json: { detail: "UNEXPECTED_SYNTHETIC_READ" } });
      }
      const index = readIndex++, date = url.searchParams.get("trade_date");
      const reply = sealReply(mode === "wrong-date" ? dayA : date, mode);
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
    const card = page.getByTestId("seal-quality-card");
    await card.getByText("字段完整", { exact: false }).waitFor();
    assert.equal(await card.getByTestId("seal-never_broken_ratio").innerText(), "50.0%");
    await card.getByText("查看来源身份与样本明细", { exact: true }).click();
    await card.getByText("选择方式：LOCAL_LATEST", { exact: false }).waitFor();
    assert.ok((await card.innerText()).includes("09:30:00"));
    assert.ok((await card.innerText()).includes("不是全市场炸板率"));
    results.push({ width, check: "qualified archive identity, decimal ratio, exact times, authority disclosure" });

    mode = "unconnected";
    await card.getByRole("button", { name: "重新读取归档" }).click();
    await card.getByText("封板质量归档证据未连接", { exact: false }).waitFor();
    assert.equal(await card.getByTestId("seal-never_broken_ratio").count(), 0);
    results.push({ width, check: "archive disconnected is not provider failure and hides old metrics" });

    mode = "partial";
    await card.getByRole("button", { name: "重新读取归档" }).click();
    await card.getByText("部分字段缺失", { exact: false }).waitFor();
    assert.equal(await card.getByTestId("seal-never_broken_ratio").innerText(), "—");
    await card.getByText("开板次数：已知 1 / 缺失或无效 1", { exact: false }).waitFor();
    results.push({ width, check: "missing count stays null and denominator coverage is explicit" });

    mode = "normal";
    const late = { date: dayA, started: deferred(), gate: deferred(), index: -1 }; hold = late;
    await card.getByRole("button", { name: "重新读取归档" }).click();
    await bounded(late.started.promise);
    await page.getByRole("button", { name: dayB, exact: true }).click();
    await card.getByText(`交易日：${dayB}`, { exact: false }).waitFor();
    await card.getByText("字段完整", { exact: false }).waitFor();
    late.gate.release();
    await page.waitForFunction(index => window.__sealReads[index]?.parsed, late.index);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(index => window.__sealReads[index].aborted, late.index), true);
    await card.getByText("字段完整", { exact: false }).waitFor();
    assert.equal(await card.getByTestId("seal-never_broken_ratio").innerText(), "50.0%");
    await card.getByText("查看来源身份与样本明细", { exact: true }).click();
    assert.ok((await card.innerText()).includes(dayB));
    assert.ok(!(await card.innerText()).includes(dayA));
    results.push({ width, check: "superseded parsed response cannot replace selected date; abort actually observed" });

    mode = "wrong-date";
    await card.getByRole("button", { name: "重新读取归档" }).click();
    await card.getByRole("alert").waitFor();
    assert.equal(await card.getByTestId("seal-never_broken_ratio").count(), 0);
    results.push({ width, check: "wrong-date response is hidden, not relabeled" });
    await page.getByRole("button", { name: "清空日期" }).click();
    await card.getByText("等待页面交易日", { exact: false }).waitFor();
    const readCount = readIndex;
    await page.getByRole("button", { name: "切换显示" }).click();
    await page.getByRole("button", { name: "切换显示" }).click();
    await card.getByText("等待页面交易日", { exact: false }).waitFor();
    assert.equal(readIndex, readCount);
    results.push({ width, check: "empty date and remount perform no invented-date read" });
    mode = "normal";
    await page.getByRole("button", { name: dayA, exact: true }).click();
    await card.getByText("字段完整", { exact: false }).waitFor();
    await page.screenshot({ path: join(output, `seal-quality-${width}.png`), fullPage: true });
    await context.close();
  }
  assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, []); assert.deepEqual(audit.errors, []);
  assert.equal(results.length, 12);
  status = "PASS";
} finally {
  writeFileSync(join(output, "result.json"), JSON.stringify({ status, scope: "production component + API client under synthetic date parent; no backend/browser-local claim", backend_processes_started: 0, provider_requests: 0, results, audit }, null, 2));
  await browser?.close(); await new Promise(resolve => server.close(resolve));
}
console.log(JSON.stringify({ status, results: results.length, output }));
