/** Chromium -> actual report routes -> isolated SQLite. No report response mocks. */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const isolated = mkdtempSync(path.join(tmpdir(), "vr-wave4-"));
const dist = path.join(root, "frontend/dist");
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function freePort() {
  const socket = createServer();
  socket.listen(0, "127.0.0.1"); await once(socket, "listening");
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  return port;
}
const port = await freePort();
const api = "http://127.0.0.1:" + port;
const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
const args = !process.env.PYTHON && process.platform === "win32" ? ["-3"] : [];
const backend = spawn(python, [...args, "-m", "uvicorn", "wave4_reporting_harness_app:app",
  "--app-dir", path.join(root, "frontend/tests/e2e"), "--host", "127.0.0.1", "--port", String(port)], {
  cwd: path.join(root, "backend"), windowsHide: true,
  env: { ...process.env, VIBE_NATIVE_INTEL_DB: path.join(isolated, "native_intel.sqlite3") },
  stdio: ["ignore", "pipe", "pipe"],
});
let logs = "";
backend.stderr.on("data", chunk => { logs += chunk; });
backend.stdout.on("data", chunk => { logs += chunk; });
let browser, server;
try {
  assert.ok(existsSync(path.join(dist, "index.html")), "npm run build first");
  let ready = false;
  for (let i = 0; i < 120; i++) {
    try { ready = (await fetch(api + "/healthz")).ok; } catch {}
    if (ready) break;
    if (backend.exitCode != null) throw new Error(logs);
    await sleep(250);
  }
  assert.ok(ready, logs);
  server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname.startsWith("/api/")) {
      try {
        const chunks = []; for await (const chunk of req) chunks.push(chunk);
        const response = await fetch(api + url.pathname + url.search, {
          method: req.method, headers: { "content-type": "application/json" },
          body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks),
        });
        res.writeHead(response.status, { "content-type": response.headers.get("content-type") || "application/json" });
        res.end(Buffer.from(await response.arrayBuffer()));
      } catch (error) { res.writeHead(502); res.end(String(error)); }
      return;
    }
    let file = path.join(dist, url.pathname);
    if (!existsSync(file) || url.pathname === "/") file = path.join(dist, "index.html");
    const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
    res.writeHead(200, { "content-type": mime[path.extname(file)] || "application/octet-stream" });
    createReadStream(file).pipe(res);
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const base = "http://127.0.0.1:" + server.address().port;
  try { browser = await chromium.launch({ headless: true }); }
  catch { browser = await chromium.launch({ headless: true, channel: "chrome" }); }
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], failedIntel = [], consoleErrors = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("response", r => { if (r.url().includes("/api/native-intel/") && r.status() >= 400) failedIntel.push(r.url() + " " + r.status()); });
  await page.goto(base + "/intel");
  assert.equal(new URL(page.url()).pathname, "/intel");
  await page.getByRole("button", { name: "报告", exact: true }).click();
  const result = page.getByTestId("intel-report-result");
  await result.waitFor();
  assert.match(await result.innerText(), /当前报告/);
  await page.getByLabel("报告模式").selectOption("DAILY");
  await page.waitForFunction(() => document.querySelector('[data-testid="intel-report-result"]')?.textContent.includes("今日报告"));
  await page.getByLabel("报告模式").selectOption("INCREMENTAL");
  await page.waitForFunction(() => document.querySelector('[data-testid="intel-report-result"]')?.textContent.includes("增量报告"));
  async function generate() {
    const response = page.waitForResponse(r => r.url().includes("/native-intel/report?") && r.request().method() === "POST");
    await page.getByRole("button", { name: "生成报告", exact: true }).click();
    const data = await (await response).json();
    await page.getByRole("button", { name: "生成报告", exact: true }).waitFor();
    assert.equal(data.cursor_advanced, true);
    return data;
  }
  assert.ok((await generate()).total > 0);
  assert.equal((await generate()).total, 0);
  assert.match(await result.innerText(), /没有符合当前范围的新变化/);
  assert.ok((await fetch(api + "/__test/new-observation", { method: "POST" })).ok);
  const delta = await generate();
  assert.equal(delta.total, 1);
  assert.equal(delta.sections[0].items[0].title, "基线后的唯一机器人新增");
  await result.getByText("基线后的唯一机器人新增", { exact: true }).waitFor();
  console.log("REPORT_CURRENT_DAILY_INCREMENTAL_AND_CURSOR = PASS");

  await page.getByRole("button", { name: "趋势分析", exact: true }).click();
  await page.getByTestId("topic-trend").waitFor();
  assert.equal(await page.getByLabel("分析话题").inputValue(), "机器人");
  for (const id of ["topic-lifecycle", "topic-viral", "topic-prediction", "platform-comparison", "keyword-cooccurrence"]) {
    await page.getByTestId(id).waitFor();
    assert.ok((await page.getByTestId(id).innerText()).length > 10);
  }
  const weibo = page.getByTestId("rank-trajectory-weibo").filter({ hasText: "机器人芯片获得新订单" });
  const baidu = page.getByTestId("rank-trajectory-baidu");
  assert.match(await weibo.innerText(), /#18/); assert.match(await weibo.innerText(), /#4/);
  assert.match(await baidu.innerText(), /#9/); assert.match(await baidu.innerText(), /#3/);
  assert.equal(await page.getByTestId("rank-trajectory-rss-a").count(), 0);
  await page.getByTestId("rank-timeline-chart").locator("canvas").waitFor();
  assert.match(await page.getByTestId("platform-comparison").innerText(), /RSS 分组/);
  assert.match(await page.getByTestId("keyword-cooccurrence").innerText(), /机器人.*芯片|芯片.*机器人/);
  assert.match(await page.getByTestId("keyword-cooccurrence").innerText(), /按 Native Intel 条目身份计数/);
  assert.match(await page.getByText(/汇总行不可与单源行再次求和/).innerText(), /RSS/);
  const shot = path.join(isolated, "analytics.png");
  await page.screenshot({ path: shot, fullPage: true });
  await page.getByTestId("rank-timeline-chart").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(isolated, "rank-timeline.png") });
  console.log("TOPIC_RANK_LIFECYCLE_VIRAL_PREDICTION_PLATFORMS_COOCCURRENCE = PASS");
  console.log("SCREENSHOT = " + shot);

  await page.getByRole("button", { name: "实时热榜", exact: true }).click();
  const news = page.getByTestId("display-region-new_items");
  await news.getByTestId("badge-NEW_ON_LIST").first().waitFor();
  await news.getByTestId("badge-NEWLY_OBSERVED").first().waitFor();
  assert.match(await news.innerText(), /首次本地采集/);
  assert.match(await news.innerText(), /新见榜/);
  assert.equal(await page.getByTestId("display-region-rss").count(), 0);
  assert.deepEqual(failedIntel, []);
  assert.deepEqual(errors, []);
  assert.deepEqual(consoleErrors, []);
  console.log("NEW_ITEMS_DISTINCT_BADGES = PASS");
  console.log("PAGE_IDENTITY = " + page.url() + " / " + await page.title());
  console.log("CONSOLE_ERRORS = " + JSON.stringify(consoleErrors));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(isolated, "new-items-mobile.png"), fullPage: true });
  console.log("MOBILE_SCREENSHOT = " + path.join(isolated, "new-items-mobile.png"));
  assert.ok((await fetch(api + "/__test/source-failure", { method: "POST" })).ok);
  await page.getByRole("button", { name: "报告", exact: true }).click();
  await result.waitFor();
  assert.doesNotMatch(await result.innerText(), /基线后的唯一机器人新增/);
  await page.getByLabel("报告模式").selectOption("DAILY");
  await page.waitForFunction(() => document.querySelector('[data-testid="intel-report-result"]')?.textContent.includes("今日报告"));
  await result.getByText("基线后的唯一机器人新增", { exact: true }).waitFor();
  assert.ok(await result.getByText("来源最近抓取：FAILED", { exact: true }).count());
  assert.ok(await result.getByText("当前榜单状态：UNKNOWN", { exact: true }).count());
  assert.deepEqual(failedIntel, []); assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []);
  console.log("DAILY_FACT_WITH_FAILED_SOURCE_AND_CURRENT_EXCLUSION = PASS");
  console.log("WAVE4_BROWSER_E2E = PASS");
} catch (error) {
  console.error(logs);
  throw error;
} finally {
  if (browser) await browser.close();
  if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  backend.kill();
}
