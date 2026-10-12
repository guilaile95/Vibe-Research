// CI-only actual production React view, synthetic raw-replay golden API. No backend.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFileSync, createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "playwright";
const frontend = fileURLToPath(new URL("../../", import.meta.url));
const output = process.env.SHORTLINE_RESEARCH_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), "shortline-research-dom-"));
mkdirSync(output, { recursive: true });
const dist = join(output, "component-dist");
const golden = JSON.parse(readFileSync(new URL("../fixtures/shortline-research.golden.json", import.meta.url)));
process.chdir(frontend);
await build({ configFile: false, mode: "production", root: join(frontend, "tests/e2e/shortline-research-adapter"),
  plugins: [react()], resolve: { alias: { "@": join(frontend, "src") } }, css: { postcss: frontend }, build: { outDir: dist, emptyOutDir: true } });
if (process.argv.includes("--build-only")) { console.log("Shortline research production component built; browser NOT_RUN"); process.exit(0); }
const audit = { external: [], unexpected: [], errors: [], reads: [] };
const staticAllowed = (method, path, search) => method === "GET" && !search && (["/", "/index.html", "/favicon.ico"].includes(path) || /^\/assets\/[\w.-]+\.(js|css)$/.test(path));
let origin, browser;
const server = createServer((req, res) => {
  const url = new URL(req.url, origin);
  if (req.headers.host !== new URL(origin).host || !staticAllowed(req.method, url.pathname, url.search)) { audit.unexpected.push(req.url); res.writeHead(403).end(); return; }
  if (url.pathname === "/favicon.ico") { res.writeHead(204).end(); return; }
  const target = url.pathname === "/" ? join(dist, "index.html") : resolve(dist, "." + url.pathname);
  if (!target.startsWith(resolve(dist) + sep) || !existsSync(target)) { res.writeHead(404).end(); return; }
  res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[extname(target)]);
  createReadStream(target).pipe(res);
});
const cases = [];
try {
  await new Promise(done => server.listen(0, "127.0.0.1", done)); origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ["--disable-background-networking", "--dns-prefetch-disable"], ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: "block" });
    await context.routeWebSocket("**/*", ws => { audit.external.push(ws.url()); ws.close(); });
    let mode = "normal", release, admitted, allowNoteSave = false, noteSaves = 0;
    await context.route("**/*", async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== origin) { audit.external.push(req.url()); return route.abort(); }
      if (staticAllowed(req.method(), url.pathname, url.search)) return route.continue();
      if (allowNoteSave && req.method() === "POST" && url.pathname === "/api/market/shortline-research/regime-events" && !url.search) {
        const body = req.postDataJSON();
        assert.equal(body.title, "Synthetic manual event"); assert.equal(body.effective_date, "2026-12-01");
        assert.equal(body.source_url, "https://example.com/synthetic-rule");
        assert.match(body.idempotency_key, /^[a-f0-9-]{36}$/); noteSaves++;
        return route.fulfill({ json: { data: { id: "regime-synthetic", created_at: "2026-10-12T12:00:00Z", authority: "USER_AUTHORED_UNVERIFIED" } } });
      }
      if (req.method() !== "GET" || url.pathname !== "/api/market/shortline-research" || !/^\?trade_date=2026-07-(30|31)$/.test(url.search)) {
        audit.unexpected.push(req.url()); return route.fulfill({ status: 400, json: { detail: "UNEXPECTED_REQUEST" } });
      }
      audit.reads.push(url.search);
      const day = url.searchParams.get("trade_date"), selectedMode = mode;
      if (selectedMode === "hold") { admitted?.(); await new Promise(done => { release = done; }); }
      let data = structuredClone(golden);
      if (day === "2026-07-31" || selectedMode === "unavailable") data = { ...data, trade_date: day, previous_trade_date: "2026-07-30", status: "unavailable", reason_codes: ["RESEARCH_RECEIPTS_MISSING"], message: "缺少所选日期原始回执", projection: null, evidence: [] };
      if (selectedMode === "wrong") data.trade_date = "2026-07-29";
      if (selectedMode === "authority") data.point_in_time_claim = "KNOWN";
      if (selectedMode === "failed") return route.fulfill({ status: 503, json: { detail: "synthetic" } });
      return route.fulfill({ json: { data } });
    });
    const page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", e => audit.errors.push(e.message));
    await page.clock.setFixedTime(new Date("2026-10-12T12:00:00Z"));
    await page.goto(origin);
    const card = page.getByTestId("shortline-research-card");
    await card.getByText("合成案例，非真实市场采集", { exact: true }).waitFor(); cases.push({ width, case: "source-to-view" });
    for (const label of ["完整昨日反馈", "历史分位", "涨停样本", "结构与字段", "今日事实"]) {
      await card.getByRole("tab", { name: label, exact: true }).click();
      await card.getByRole("tabpanel").waitFor(); cases.push({ width, case: label });
    }
    await card.getByRole("tab", { name: "完整昨日反馈", exact: true }).click();
    assert.equal(await card.getByTestId("shortline-cohort-table").locator("tbody tr").count(), 3);
    const populatedLayout = await page.evaluate(() => ({ documentWidth: document.documentElement.scrollWidth, viewport: innerWidth }));
    assert.ok(populatedLayout.documentWidth <= populatedLayout.viewport + 1);
    await page.screenshot({ path: join(output, `${width}-cohort.png`), fullPage: true });
    await page.getByRole("button", { name: "2026-07-31", exact: true }).click();
    await card.getByText("缺少所选日期原始回执", { exact: true }).waitFor(); assert.equal(await card.locator("tbody tr").count(), 0); cases.push({ width, case: "date-clear" });
    await page.getByRole("button", { name: "2026-07-30", exact: true }).click();
    await card.getByTestId("shortline-cohort-table").waitFor();
    await card.getByText("人工登记制度事件（未经核验）", { exact: true }).click();
    await card.getByLabel("记录生效日", { exact: true }).fill("2026-12-01");
    await card.getByLabel("制度事件标题", { exact: true }).fill("Synthetic manual event");
    await card.getByLabel("制度事件来源链接", { exact: true }).fill("https://example.com/synthetic-rule");
    allowNoteSave = true;
    await card.getByRole("button", { name: "保存人工记录", exact: true }).click();
    await card.getByText("已保存人工记录；原记录不可变，未升级为官方规则证据", { exact: true }).waitFor();
    assert.equal(noteSaves, 1); allowNoteSave = false; cases.push({ width, case: "explicit-unverified-note-save" });
    await card.getByTestId("shortline-cohort-table").waitFor();
    const retry = card.getByRole("button", { name: "重新读取研究归档", exact: true });
    for (const error of ["wrong", "authority", "failed"]) {
      mode = error; await retry.click(); await card.getByRole("alert").filter({ hasText: "读取或合同核验失败" }).waitFor();
      assert.equal(await card.locator("tbody tr").count(), 0); cases.push({ width, case: error });
      mode = "normal"; await retry.click(); await card.getByTestId("shortline-cohort-table").waitFor();
    }
    mode = "hold"; const started = new Promise(done => { admitted = done; }); await retry.click(); await started;
    mode = "normal"; await page.getByRole("button", { name: "2026-07-31", exact: true }).click();
    // The held request owns an old generation and is aborted by date cleanup.
    release(); await card.getByText("缺少所选日期原始回执", { exact: true }).waitFor();
    assert.equal(await card.locator("tbody tr").count(), 0); cases.push({ width, case: "late-old-date" });
    await page.getByRole("button", { name: "清空日期", exact: true }).click(); await card.getByText("等待页面交易日，未使用今天代替", { exact: true }).waitFor();
    await page.getByRole("button", { name: "切换显示", exact: true }).click(); assert.equal(await page.getByTestId("shortline-research-card").count(), 0);
    await page.getByRole("button", { name: "切换显示", exact: true }).click(); cases.push({ width, case: "clear-unmount-remount" });
    const layout = await page.evaluate(() => ({ documentWidth: document.documentElement.scrollWidth, viewport: innerWidth }));
    assert.ok(layout.documentWidth <= layout.viewport + 1);
    await page.screenshot({ path: join(output, `${width}.png`), fullPage: true });
    await context.close();
  }
  assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, []); assert.deepEqual(audit.errors, []);
  writeFileSync(join(output, "result.json"), JSON.stringify({ status: "PASS", cases, audit }, null, 2));
} finally { await browser?.close(); await new Promise(done => server.close(done)); }
