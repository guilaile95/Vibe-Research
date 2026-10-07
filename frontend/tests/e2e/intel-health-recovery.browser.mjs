// Actual production UI with synthetic, offline HTTP responses. No model/backend jobs.
// INTEL deliberately ignores transport abort for deep-read fetches only, so a late
// A response really reaches the browser and tests ownership rather than cancellation.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const frontend = fileURLToPath(new URL("../../", import.meta.url));
const dist = join(frontend, "dist");
const NAME = "SYNTHETIC_QUOTES";
const OLD = "SYNTHETIC_OLD";
const NEW = "SYNTHETIC_NEW";
const FAILURE = "SYNTHETIC_DETAIL_UNAVAILABLE";
const deepPath = id => `/api/native-intel/items/${id}/deep-read`;
const json = data => ({ status: 200, json: data });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const record = (marker, status = "partial") => ({
  source_id: "quotes", display_name: NAME, module: "synthetic", status,
  is_stale: false, observed_at: "2026-10-05T00:00:00Z", last_success_at: null,
  last_error_code: marker, last_error_summary: marker, blocks_advice: false,
});
const detail = (marker, status = "partial") => json({ data: {
  record: record(marker, status), calculation: {}, related_pages: [],
} });
const overview = (marker, status = "partial") => json({ data: {
  items: [record(marker, status)], overall_status: status, block_reasons: [],
  summary: { normal: 0, partial: status === "partial" ? 1 : 0,
    unavailable: status === "unavailable" ? 1 : 0, stale: 0, not_initialized: 0 },
} });
const deep = id => json({
  item_id: id, title: `SOURCE_${id}`, status: "success", content_level: "ARTICLE_BODY",
  original_url: `https://synthetic.invalid/${id}`, content: `BODY_${id}`, analysis: `ANALYSIS_${id}`,
});

// Export the exact browser fixture for cheap offline contract tests, not UI claims.
export function recoveryFixture(scenario) {
  assert.ok(["intel", "health-refresh", "health-retry"].includes(scenario));
  const state = { overviewCalls: 0, detailCalls: 0, deepCalls: [], unexpected: [] };
  const oldRequested = deferred(), reloadRequested = deferred();
  const oldReply = deferred(), reloadReply = deferred();
  const common = {
    "/api/native-intel/config": { region_order: ["hotlist"], regions_enabled: { hotlist: true, rss: false, standalone: false } },
    "/api/native-intel/standalone": { status: "normal", items: [] },
    "/api/native-intel/filter/items": { status: "normal", items: [], sources: [] },
    "/api/native-intel/hotlist": { status: "normal", sources: [], items: [1, 2].map(id => ({
      item_id: id, title: `SOURCE_${id}`, url: `https://synthetic.invalid/${id}`,
      source_id: "fixture", hint: "tech", current_state: "ON_LIST", rank: id,
    })) },
    "/api/native-intel/status": { status: "normal", sources: [], store: { item_count: 0 } },
    "/api/native-intel/items": { status: "normal", items: [] },
    "/api/native-intel/trending": { status: "normal", entities: [] },
    "/api/radar": { data: { industries: [], stats: { total_sources: 0, industries: 0 } } },
  };
  return {
    state, oldRequested: oldRequested.promise, reloadRequested: reloadRequested.promise,
    releaseOld: () => oldReply.resolve(deep(1)),
    releaseReload: () => reloadReply.resolve(detail(NEW, "unavailable")),
    async reply(method, path) {
      if (method === "POST" && [deepPath(1), deepPath(2)].includes(path) && scenario === "intel") {
        const id = path === deepPath(1) ? 1 : 2;
        state.deepCalls.push(id);
        if (id === 1) { oldRequested.resolve(); return oldReply.promise; }
        return deep(id);
      }
      if (method === "GET" && path === "/api/data-health" && scenario !== "intel") {
        state.overviewCalls += 1;
        return state.overviewCalls === 1 ? overview(OLD) : overview(NEW, "unavailable");
      }
      if (method === "GET" && path === "/api/data-health/quotes" && scenario !== "intel") {
        state.detailCalls += 1;
        if (scenario === "health-retry") return state.detailCalls === 1
          ? { status: 503, json: { detail: FAILURE } } : detail(NEW);
        if (state.detailCalls === 1) return detail(OLD);
        reloadRequested.resolve();
        return reloadReply.promise;
      }
      if (method === "GET" && Object.hasOwn(common, path)) return json(common[path]);
      state.unexpected.push(`${method} ${path}`);
      return { status: 503, json: { detail: "UNEXPECTED_SYNTHETIC_REQUEST" } };
    },
  };
}

async function bounded(promise, label) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), 10000);
    })]);
  } finally { clearTimeout(timer); }
}

async function staticServer() {
  const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
  const server = createServer((request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
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

export function recordLateDeepReads() {
  const nativeFetch = window.fetch.bind(window);
  window.__recoveryDeepReads = {};
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const match = url.pathname.match(/^\/api\/native-intel\/items\/(\d+)\/deep-read$/);
    if (!match) return nativeFetch(input, init);
    const event = window.__recoveryDeepReads[match[1]] = { aborted: Boolean(init?.signal?.aborted), parsed: false };
    init?.signal?.addEventListener("abort", () => { event.aborted = true; }, { once: true });
    const response = await nativeFetch(input, { ...init, signal: undefined });
    const readJson = response.json.bind(response);
    response.json = async () => { const data = await readJson(); event.parsed = true; return data; };
    return response;
  };
}

async function runScenario(browser, baseURL, width, scenario, evidenceDir) {
  const fixture = recoveryFixture(scenario);
  const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [], external = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => {
    if (message.type() === "error" && !(scenario === "health-retry" && /Failed to load resource.*503/.test(message.text()))) errors.push(message.text());
  });
  await context.routeWebSocket("**/*", socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== baseURL) {
      if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
      external.push(url.origin);
      return route.abort();
    }
    if (url.pathname.startsWith("/api/")) {
      if (request.method() === "POST" && /\/deep-read$/.test(url.pathname)) {
        assert.equal(request.postDataJSON()?.llm, null, "isolated context must not contain model credentials");
      }
      return route.fulfill(await fixture.reply(request.method(), url.pathname));
    }
    return route.continue();
  });
  // Only synthetic deep-read requests ignore AbortSignal. All other fetches stay native.
  if (scenario === "intel") await context.addInitScript(recordLateDeepReads);
  try {
    const path = scenario === "intel" ? "/intel" : "/data-health";
    await page.goto(path, { waitUntil: "domcontentloaded" });
    assert.equal(new URL(page.url()).pathname, path);
    assert.ok((await page.title()).trim(), "page title is nonempty");
    await page.getByRole("heading", { name: scenario === "intel" ? "资讯中心" : "数据健康", exact: true }).waitFor();
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
    if (scenario === "intel") {
      await page.getByRole("button", { name: "实时热榜", exact: true }).click();
      await page.getByTestId("native-intel-deep-read-1").click();
      await bounded(fixture.oldRequested, "A request");
      await page.getByRole("button", { name: "关闭来源深读" }).click();
      assert.equal(await page.getByTestId("native-intel-deep-read-modal").count(), 0);
      await page.getByTestId("native-intel-deep-read-2").click();
      await page.getByTestId("native-intel-deep-read-content").filter({ hasText: "BODY_2" }).waitFor();
      fixture.releaseOld();
      await page.waitForFunction(() => window.__recoveryDeepReads["1"]?.parsed);
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
      const modal = page.getByTestId("native-intel-deep-read-modal");
      assert.equal(await page.getByTestId("native-intel-deep-read-content").innerText(), "BODY_2");
      assert.equal(await page.getByTestId("native-intel-deep-read-analysis").innerText(), "ANALYSIS_2");
      assert.ok((await modal.innerText()).includes("SOURCE_2"));
      assert.doesNotMatch(await modal.innerText(), /SOURCE_1|BODY_1|ANALYSIS_1|正在读取来源/);
      assert.equal(await modal.getByRole("link", { name: "原始来源" }).getAttribute("href"), "https://synthetic.invalid/2");
      assert.equal(await page.evaluate(() => window.__recoveryDeepReads["1"].aborted), true);
      assert.deepEqual(fixture.state.deepCalls, [1, 2]);
    } else {
      const card = page.locator("div.cursor-pointer").filter({ has: page.getByText(NAME, { exact: true }) });
      await card.waitFor();
      assert.equal(await card.count(), 1);
      await card.click();
      const detailCard = page.getByRole("heading", { name: "单来源详情", exact: true }).locator("..");
      if (scenario === "health-refresh") {
        await detailCard.getByText(`错误码：${OLD}`, { exact: true }).waitFor();
        await page.getByRole("button", { name: "重新读取", exact: true }).click();
        await bounded(fixture.reloadRequested, "selected detail reload");
        await card.getByLabel("数据状态：不可用", { exact: true }).waitFor();
        await detailCard.getByText("加载详情…", { exact: true }).waitFor();
        assert.doesNotMatch(await detailCard.innerText(), new RegExp(OLD));
        fixture.releaseReload();
        await detailCard.getByText(`错误码：${NEW}`, { exact: true }).waitFor();
        await detailCard.getByLabel("数据状态：不可用", { exact: true }).waitFor();
        assert.equal(fixture.state.overviewCalls, 2);
      } else {
        await detailCard.getByRole("alert").filter({ hasText: FAILURE }).waitFor();
        await detailCard.getByRole("button", { name: "重试详情", exact: true }).waitFor();
        assert.equal(fixture.state.detailCalls, 1);
        await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-error.png`), fullPage: true });
        // Click the same source card, not the retry button or a different source.
        await card.click();
        await detailCard.getByText(`错误码：${NEW}`, { exact: true }).waitFor();
        assert.equal(await detailCard.getByRole("alert").count(), 0);
        assert.equal(fixture.state.overviewCalls, 1, "same-card retry does not reload the page");
      }
      assert.equal(fixture.state.detailCalls, 2);
      assert.doesNotMatch(await detailCard.innerText(), /加载详情|SYNTHETIC_OLD/);
    }
    assert.deepEqual(fixture.state.unexpected, [], "all API calls match the bounded fixture");
    assert.deepEqual(external, [], "no external network or WebSocket attempts");
    assert.deepEqual(errors, [], "no page errors or unexpected console errors");
    await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-pass.png`), fullPage: true });
    return { scenario, width, status: "PASS", requests: fixture.state };
  } catch (error) {
    await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-failure.png`), fullPage: true }).catch(() => {});
    throw new Error(`${scenario} at ${width}px: ${error.message}; evidence=${JSON.stringify({ requests: fixture.state, errors, external })}`, { cause: error });
  } finally {
    fixture.releaseOld(); fixture.releaseReload();
    await context.close();
  }
}

async function main() {
  const evidenceDir = process.env.RECOVERY_EVIDENCE_DIR || mkdtempSync(join(tmpdir(), "vr-recovery-evidence-"));
  mkdirSync(evidenceDir, { recursive: true });
  const result = {
    checkoutHead: execFileSync("git", ["rev-parse", "HEAD"], { cwd: frontend, encoding: "utf8" }).trim(),
    checkoutTree: execFileSync("git", ["rev-parse", "HEAD^{tree}"], { cwd: frontend, encoding: "utf8" }).trim(),
    frontendSourceTree: execFileSync("git", ["rev-parse", "HEAD:frontend/src"], { cwd: frontend, encoding: "utf8" }).trim(),
    pullRequestHead: process.env.RECOVERY_PR_HEAD || null,
    boundary: "Production dist; synthetic offline APIs; deep-read fetch ignores abort to test late-response ownership; no live model/data quality claim",
    results: [],
  };
  let browser, server;
  try {
    assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first");
    // Honor a configured existing executable; no installer or alternate launch retry.
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
    server = await staticServer();
    const baseURL = `http://127.0.0.1:${server.address().port}`;
    for (const width of [1440, 390]) for (const scenario of ["intel", "health-refresh", "health-retry"]) {
      const row = await runScenario(browser, baseURL, width, scenario, evidenceDir);
      result.results.push(row);
      console.log(`[RECOVERY] ${scenario} ${width}px PASS`);
    }
    assert.equal(result.results.length, 6);
    console.log(`[RECOVERY] 6/6 PASS; evidence: ${evidenceDir}`);
  } catch (error) {
    result.error = error.message;
    throw error;
  } finally {
    writeFileSync(join(evidenceDir, "results.json"), JSON.stringify(result, null, 2));
    try { await browser?.close(); } finally {
      server?.closeAllConnections();
      if (server) await new Promise(done => server.close(done));
    }
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
