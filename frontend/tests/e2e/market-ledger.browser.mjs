// Original MARKET-01, LEDGER-01 and LEDGER-02 on unchanged production dist.
// Per-sector async imports are bundled together in production; no artificial
// production chunk race is claimed. Existing component ownership tests are separate.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { research, industry, contextFor, marketReply, rows, failure, oldDetail, ledgerFixture, observeLedgerReads } from "./market-ledger.fixture.mjs";
const frontend = fileURLToPath(new URL("../../", import.meta.url));
const dist = join(frontend, "dist");
async function bounded(promise) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Expected synthetic request did not arrive")), 10000); })]); }
  finally { clearTimeout(timer); }
}
async function staticServer() {
  const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
  const server = createServer((request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname === "/__storage_probe") {
      response.setHeader("Content-Type", "text/html");
      response.end("<!doctype html><title>Isolated storage probe</title>");
      return;
    }
    let target = resolve(dist, `.${decodeURIComponent(pathname)}`);
    if (!target.startsWith(dist + sep)) target = join(dist, "index.html");
    if (!existsSync(target) || !extname(target)) target = join(dist, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  await new Promise((done, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", done);
  });
  return server;
}


async function runScenario(browser, baseURL, width, scenario, evidenceDir) {
  let context, page;
  const fixture = ledgerFixture(), errors = [], external = [], unexpected = [], marketRequests = [], checks = [];
  try {
    context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
    await context.addInitScript(observeLedgerReads);
    await context.routeWebSocket("**/*", socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
      if (url.origin !== baseURL) { external.push(url.origin); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (scenario === "market-columns") {
        marketRequests.push(`${request.method()} ${url.pathname}${url.search}`);
        const reply = marketReply(request.method(), url.pathname, url.search);
        if (reply !== null) return route.fulfill({ json: reply });
      } else if (url.pathname === "/api/signal-ledger" || url.pathname === "/api/signal-ledger/run/dr_synthetic_old") {
        return route.fulfill(await fixture.reply(request.method(), url.href));
      }
      unexpected.push(`${request.method()} ${url.pathname}${url.search}`);
      return route.fulfill(failure("UNEXPECTED_SYNTHETIC_REQUEST"));
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    const settle = async slot => {
      slot.release();
      await page.waitForFunction(index => window.__ledgerReads[index]?.parsed, fixture.all.indexOf(slot));
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    };
    if (scenario === "market-columns") {
      await page.goto("/sectors/ai-computing/industry");
      const nav = page.getByRole("navigation", { name: "研究栏目", exact: true });
      const verify = async tag => {
        assert.equal(new URL(page.url()).pathname, `/sectors/ai-computing/${tag.slug}`);
        await page.getByRole("heading", { name: research.fullName, exact: true }).waitFor();
        const title = page.getByRole("heading", { name: tag.title, exact: true });
        await title.waitFor();
        const card = title.locator("..").locator("..");
        await card.getByText("草稿", { exact: true }).waitFor();
        assert.equal(await card.getByText("已发布", { exact: true }).count(), 0);
        assert.deepEqual(await nav.locator("a").allTextContents(), research.tags.map(t => t.label));
        assert.equal(await nav.locator(`a[href="/sectors/ai-computing/${tag.slug}"]`).getAttribute("aria-current"), "page");
        const marker = tag.blocks.find(block => block.type === "paragraph").text;
        assert.ok((await card.innerText()).includes(marker), "rendered body comes from the actual selected source column");
        await page.getByRole("button", { name: "问 AI", exact: true }).click();
        const panel = page.locator('aside[aria-label="Vibe AI 对话"]');
        await panel.getByRole("heading", { name: "接入你的 AI", exact: true }).waitFor();
        assert.equal(await panel.locator("pre").innerText(), contextFor(tag));
        assert.doesNotMatch(await panel.locator("pre").innerText(), /DRAM、封装、设备与材料格局|内容状态：ready/);
        await panel.getByRole("button", { name: "关闭", exact: true }).click();
        checks.push(`actual loaded ${tag.slug}: heading/body/draft/context`);
      };
      await verify(industry); // Exact original DRAM-vs-chip/server mismatch first.
      for (const tag of research.tags) {
        await nav.locator(`a[href="/sectors/ai-computing/${tag.slug}"]`).click();
        await verify(tag);
      }
      await page.goBack(); await verify(industry);
      await page.goForward(); await verify(research.tags.at(-1));
      await page.reload(); await verify(research.tags.at(-1));
      checks.push("native Back/Forward and reload retain current content identity");
      assert.equal(await page.evaluate(() => localStorage.getItem("vr-llm")), null);
      assert.ok(marketRequests.length >= 2);
      await page.getByRole("heading", { name: research.tags.at(-1).title, exact: true }).scrollIntoViewIfNeeded();
    } else {
      const stage = page.locator("form select").nth(0), severity = page.locator("form select").nth(1);
      const code = page.getByPlaceholder("6位代码", { exact: true });
      const run = page.getByPlaceholder("e.g. dr_...", { exact: true });
      const query = page.getByRole("button", { name: "查询信号", exact: true });
      const reset = page.getByRole("button", { name: "重置", exact: true });
      const loading = page.getByText("正在加载信号流水...", { exact: true });
      const visible = marker => page.getByText(marker, { exact: true }).waitFor();
      const mainText = () => page.locator("main").innerText();
      const cleared = async () => {
        assert.equal(await code.inputValue(), ""); assert.equal(await run.inputValue(), "");
        assert.equal(await stage.inputValue(), ""); assert.equal(await severity.inputValue(), "");
        assert.equal(new URL(page.url()).search, "");
        assert.equal(await page.getByText("股票代码必须是 6 位数字", { exact: true }).count(), 0);
        await page.getByRole("heading", { name: "阶段流水时间线 (0 条信号)", exact: true }).waitFor();
      };
      if (scenario.startsWith("ledger-reset-old")) {
        const old = fixture.expect("/api/signal-ledger/run/dr_synthetic_old", scenario.endsWith("error") ? failure("SYNTHETIC_OBSOLETE_FAILURE") : oldDetail());
        await page.goto("/signal-ledger?decision_run_id=dr_synthetic_old"); await bounded(old.started);
        await code.fill("bad"); await query.click();
        await page.getByText("股票代码必须是 6 位数字", { exact: true }).waitFor();
        assert.equal(fixture.requests.length, 1, "invalid submit issues no request");
        const current = fixture.expect("/api/signal-ledger?limit=100", rows("SYNTHETIC_RESET_CURRENT", "execution"));
        await reset.click(); await bounded(current.started); await cleared();
        await settle(old); await loading.waitFor();
        assert.doesNotMatch(await mainText(), /SYNTHETIC_OLD_RUN|SYNTHETIC_OLD_DETAIL|SYNTHETIC_OLD_OUTCOME|SYNTHETIC_OBSOLETE_FAILURE|暂无信号记录/);
        await settle(current); await visible("SYNTHETIC_RESET_CURRENT");
        assert.doesNotMatch(await mainText(), /SYNTHETIC_OLD_RUN|SYNTHETIC_OLD_DETAIL|SYNTHETIC_OLD_OUTCOME/);
        checks.push("invalid submit → reset clears run/filters; stale detail cannot stop current loading or restore old state");
      } else {
        const initial = fixture.expect("/api/signal-ledger?limit=100", rows("SYNTHETIC_INITIAL")); initial.release();
        await page.goto("/signal-ledger"); await visible("SYNTHETIC_INITIAL");
        if (scenario === "ledger-reset-retry") {
          await stage.selectOption("execution"); await severity.selectOption("error"); await code.fill("bad"); await query.click();
          await page.getByText("股票代码必须是 6 位数字", { exact: true }).waitFor();
          assert.equal(fixture.requests.length, 1);
          const current = fixture.expect("/api/signal-ledger?limit=100", failure("SYNTHETIC_RESET_FAILED"));
          await reset.click(); await bounded(current.started); await cleared(); await loading.waitFor();
          assert.doesNotMatch(await mainText(), /SYNTHETIC_INITIAL/);
          await settle(current); await visible("SYNTHETIC_RESET_FAILED");
          assert.equal(await page.getByText("暂无信号记录", { exact: true }).count(), 0, "failed read is not empty success");
          assert.doesNotMatch(await mainText(), /SYNTHETIC_INITIAL|股票代码必须/);
          await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-error.png`), fullPage: true });
          const retry = fixture.expect("/api/signal-ledger?limit=100", rows(null));
          await page.getByRole("button", { name: "重试", exact: true }).click(); await bounded(retry.started); await settle(retry);
          await page.getByText("暂无信号记录", { exact: true }).waitFor(); await cleared();
          assert.doesNotMatch(await mainText(), /SYNTHETIC_RESET_FAILED|SYNTHETIC_INITIAL|股票代码必须/);
          checks.push("invalid code → reset clears validation/old rows before response; failure is not empty; retry reaches empty success");
        } else {
          const staleReply = round => scenario.endsWith("error") ? failure(`SYNTHETIC_OLD_ERROR_${round}`) : rows(`SYNTHETIC_OLD_SCHEMA_${round}`);
          for (const round of [1, 2]) {
            const old = fixture.expect("/api/signal-ledger?stage=schema&limit=100", staleReply(round));
            await stage.selectOption("schema"); await query.click(); await bounded(old.started);
            const current = fixture.expect("/api/signal-ledger?stage=execution&limit=100", rows(`SYNTHETIC_EXECUTION_${round}`, "execution"));
            await stage.selectOption("execution"); await query.click(); await bounded(current.started);
            if (round === 1) { await settle(current); await visible("SYNTHETIC_EXECUTION_1"); }
            await settle(old);
            assert.equal(await stage.inputValue(), "execution");
            assert.doesNotMatch(await mainText(), /SYNTHETIC_OLD_SCHEMA|SYNTHETIC_OLD_ERROR/);
            if (round === 2) {
              await loading.waitFor();
              assert.equal(await page.getByText("暂无信号记录", { exact: true }).count(), 0);
              await settle(current); await visible("SYNTHETIC_EXECUTION_2");
            } else await visible("SYNTHETIC_EXECUTION_1");
          }
          checks.push("schema old → execution current; old success/error cannot replace new rows or finish pending current load");
        }
      }
    }
    assert.equal(fixture.queue.length, 0); assert.deepEqual(fixture.unexpected, []); assert.deepEqual(unexpected, []); assert.deepEqual(external, []);
    const expectedErrors = errors.filter(error => /Failed to load resource.*503/.test(error));
    assert.equal(expectedErrors.length, fixture.failures, "only fixture HTTP failures may create console errors");
    assert.deepEqual(errors.filter(error => !/Failed to load resource.*503/.test(error)), []);
    assert.equal(await page.locator("vite-error-overlay").count(), 0); assert.ok((await page.title()).trim());
    const reads = await page.evaluate(() => window.__ledgerReads);
    assert.ok(reads.every(row => row.parsed), "late replies reached actual JSON parsing");
    await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-pass.png`), fullPage: true });
    return { scenario, width, status: "PASS", checks, requests: scenario === "market-columns" ? marketRequests : fixture.requests, reads,
      boundary: scenario === "market-columns" ? "Untouched production dist; actual source-backed content/context; per-sector import races remain separately offline-tested" : "Production UI; exact planned synthetic GET replies; no live backend" };
  } catch (error) {
    await page?.screenshot({ path: join(evidenceDir, `${scenario}-${width}-failure.png`), fullPage: true }).catch(() => {});
    throw new Error(`${scenario} ${width}px: ${error.message}; ${JSON.stringify({ errors, external, unexpected, requests: fixture.requests, marketRequests })}`, { cause: error });
  } finally { fixture.cleanup(); await context?.close(); }
}
async function main() {
  const evidenceDir = process.env.MARKET_LEDGER_EVIDENCE_DIR || mkdtempSync(join(tmpdir(), "vr-market-ledger-evidence-")); mkdirSync(evidenceDir, { recursive: true });
  const git = arg => execFileSync("git", ["rev-parse", arg], { cwd: frontend, encoding: "utf8" }).trim();
  const result = { checkoutHead: git("HEAD"), checkoutTree: git("HEAD^{tree}"), frontendSourceTree: git("HEAD:frontend/src"), pullRequestHead: process.env.MARKET_LEDGER_PR_HEAD || null, results: [] };
  let browser, server;
  try {
    assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first");
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) }); server = await staticServer();
    const baseURL = `http://127.0.0.1:${server.address().port}`;
    for (const width of [1440, 390]) for (const scenario of ["market-columns", "ledger-late-success", "ledger-late-error", "ledger-reset-retry", "ledger-reset-old-success", "ledger-reset-old-error"]) {
      try { result.results.push(await runScenario(browser, baseURL, width, scenario, evidenceDir)); console.log(`[MARKET-LEDGER] ${scenario} ${width}px PASS`); }
      catch (error) { result.results.push({ scenario, width, status: "FAIL", error: error.message }); console.error(`[MARKET-LEDGER] ${scenario} ${width}px FAIL: ${error.message}`); }
    }
    assert.equal(result.results.length, 12); assert.equal(result.results.filter(row => row.status !== "PASS").length, 0);
    console.log("[MARKET-LEDGER] 12/12 PASS");
  } catch (error) { result.error = error.message; throw error; }
  finally {
    try { writeFileSync(join(evidenceDir, "results.json"), JSON.stringify(result, null, 2)); }
    finally { try { await browser?.close(); } finally { server?.closeAllConnections(); if (server) await new Promise(done => server.close(done)); } }
  }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
