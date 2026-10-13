// Production bundle with contract-shaped synthetic evidence only. No account, market or model calls.
// Run after npm run build: node --import ./tests/e2e/runtime-env.mjs tests/e2e/evidence-list.browser.mjs
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
const frontend = fileURLToPath(new URL("../../", import.meta.url));
const dist = join(frontend, "dist");

export function evidenceFixture(index, subject = "sample") {
  return {
    id: `synthetic-${subject}-${index}`, subject_type: "stock", subject_id: subject,
    evidence_type: "announcement", claim: `Synthetic evidence ${subject} ${index}: ${"来源陈述仍需核验。".repeat(8)}`,
    source_title: index === 0 ? "" : `Synthetic source ${index}`, source_url: null,
    source_date: index === 0 ? null : "2026-10-01", accessed_at: "2026-10-02T00:00:00Z",
    classification: index % 2 ? "inference" : "fact", confidence: "low",
    created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", deleted: 0, deleted_at: null,
  };
}
export function evidenceReply(url) {
  const subject = url.searchParams.get("subject_id") || "sample";
  const offset = Number(url.searchParams.get("offset") || 0);
  const limit = Number(url.searchParams.get("limit") || 50);
  const total = subject === "empty" ? 0 : 51;
  return { items: Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => evidenceFixture(index + offset, subject)), total, offset, limit };
}

// One atomic rendered-state check. A changed URL alone can precede React's commit,
// and a same-subject row can belong to the previous page. Do not use row counts as
// the completion signal: they remain independent exact assertions after readiness.
export function evidenceViewReady(expected, snapshot) {
  if (!snapshot) {
    const section = document.querySelector('section[aria-labelledby="evidence-list-heading"]');
    const params = new URL(location.href).searchParams;
    snapshot = {
      pathname: location.pathname,
      subject: params.get("subject_id") || "",
      subjectType: params.get("subject_type") || "",
      page: Number(params.get("page") || "1"),
      busy: section?.getAttribute("aria-busy"),
      applied: section?.querySelector("h2 + p")?.textContent?.trim(),
      status: section?.querySelector('[role="status"]')?.textContent?.trim(),
      firstId: section?.querySelector("article h3")?.id,
      heading: section?.querySelector("h3")?.textContent?.trim(),
    };
  }
  if (snapshot.pathname !== "/evidence" || snapshot.subject !== expected.subject ||
      snapshot.subjectType !== (expected.subject ? "stock" : "") || snapshot.page !== expected.page ||
      snapshot.applied !== (expected.subject ? `已应用：个股 / ${expected.subject}` : "已应用：全部标的")) return false;
  if (expected.kind === "loading") return snapshot.busy === "true" && snapshot.status === "正在加载证据…";
  if (snapshot.busy !== "false") return false;
  if (expected.kind === "error") return snapshot.heading === "证据加载失败";
  if (expected.kind === "empty") return snapshot.heading === "此筛选下暂无证据";
  const offset = (expected.page - 1) * 50;
  const count = Math.min(50, 51 - offset);
  return snapshot.status === `共 51 条 · 第 ${expected.page} / 2 页 · 本页 ${count} 条` &&
    snapshot.firstId === `evidence-synthetic-${expected.subject || "sample"}-${offset}`;
}

async function bounded(promise, message) {
  let timeout;
  try {
    return await Promise.race([promise, new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error(message)), 10000); })]);
  } finally { clearTimeout(timeout); }
}

async function run(browser, baseURL, width, output) {
  const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [], unexpected = [], external = [], requests = [];
  let failure = false, releaseSlow, slowSeen, phase = "initial load";
  const slowRequested = new Promise(done => { slowSeen = done; });
  const slowGate = new Promise(done => { releaseSlow = done; });
  // Deliberately non-cancellable synthetic transport tests the completion-ownership guard too.
  await context.addInitScript(() => {
    const original = window.fetch;
    window.__evidenceParsed = [];
    window.fetch = async (input, init) => {
      if (String(input).includes("/api/evidence?") && init) {
        const { signal: _signal, ...rest } = init;
        const response = await original(input, rest);
        const json = response.json.bind(response);
        response.json = async () => {
          const payload = await json();
          window.__evidenceParsed.push(String(input));
          return payload;
        };
        return response;
      }
      return original(input, init);
    };
  });
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error" && !message.text().includes("503")) errors.push(message.text()); });
  await context.routeWebSocket("**/*", socket => { external.push(socket.url()); socket.close(); });
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
    if (url.origin !== baseURL) { external.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (request.method() === "GET" && url.pathname === "/api/evidence") {
      requests.push(url.search);
      assert.equal(url.searchParams.get("limit"), "50");
      assert.equal(Boolean(url.searchParams.get("subject_type")), Boolean(url.searchParams.get("subject_id")));
      if (url.searchParams.get("subject_id") === "slow") { slowSeen(); await slowGate; }
      if (failure) return route.fulfill({ status: 503, json: { detail: "Synthetic evidence unavailable" } });
      return route.fulfill({ json: { data: evidenceReply(url) } });
    }
    unexpected.push(`${request.method()} ${url.pathname}`);
    return route.fulfill({ status: 503, json: { detail: "UNEXPECTED_SYNTHETIC_REQUEST" } });
  });
  const form = page.getByRole("form", { name: "证据筛选" });
  const query = async id => {
    phase = `submit filter ${id}`;
    await form.getByLabel("主体类型", { exact: true }).selectOption("stock");
    await form.getByLabel("主体代码/标识", { exact: true }).fill(id);
    await form.getByRole("button", { name: "查询", exact: true }).click();
  };
  const ready = async (subject, pageNumber = 1, kind = "success") => {
    phase = `await ${kind}: ${subject || "all subjects"}, page ${pageNumber}`;
    await page.waitForFunction(evidenceViewReady, { subject, page: pageNumber, kind });
  };
  const row = subject => page.getByRole("article").filter({ hasText: `Synthetic evidence ${subject}` });
  try {
    await page.goto("/evidence");
    await ready("");
    assert.equal(new URL(page.url()).pathname, "/evidence");
    assert.ok(await page.title());
    await page.getByRole("heading", { name: "证据库", exact: true }).waitFor();
    assert.equal(await row("sample").count(), 50);
    await page.getByText("未提供来源标题", { exact: true }).waitFor();
    await page.getByText("来源信息不完整，核验时请补充来源标题或日期。", { exact: true }).waitFor();
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    assert.equal(overflow, false, "no page-level horizontal overflow");
    await page.screenshot({ path: join(output, `evidence-${width}-normal.png`), fullPage: false });
    const initialReads = requests.length;
    await form.getByLabel("主体代码/标识", { exact: true }).fill("not-applied");
    assert.equal(await row("sample").count(), 50, "editing a draft does not relabel results");
    await form.getByRole("button", { name: "查询", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: /请同时选择主体类型/ }).waitFor();
    assert.equal(requests.length, initialReads, "partial filter is never sent as a global query");
    await query("fast");
    await ready("fast");
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await ready("fast", 2);
    assert.equal(await row("fast").count(), 1);
    assert.equal(await page.locator("#evidence-synthetic-fast-0").count(), 0, "page 1 rows are retired");
    const detailHref = await row("fast").getByRole("link").getAttribute("href");
    assert.equal(new URL(detailHref, baseURL).searchParams.get("return_to"), "/evidence?subject_type=stock&subject_id=fast&page=2");
    await page.getByRole("link", { name: "新建证据", exact: true }).click();
    await page.getByRole("heading", { name: "新建证据", exact: true }).waitFor();
    await page.getByRole("link", { name: "取消", exact: true }).click();
    await ready("fast", 2);
    assert.equal(await row("fast").count(), 1, "cancel creation restores the page and subject");
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    await ready("fast");
    assert.equal(await row("fast").count(), 50);
    await query("empty");
    await ready("empty", 1, "empty");
    assert.equal(await page.getByRole("article").count(), 0);
    await page.goBack();
    await ready("fast");
    assert.equal(await row("fast").count(), 50);
    assert.equal(await form.getByLabel("主体代码/标识", { exact: true }).inputValue(), "fast");
    failure = true;
    await query("failed");
    await ready("failed", 1, "error");
    assert.equal(await row("fast").count(), 0, "failed new subject does not show old subject rows");
    await page.screenshot({ path: join(output, `evidence-${width}-error.png`), fullPage: false });
    failure = false;
    await page.getByRole("button", { name: "重新加载", exact: true }).click();
    await ready("failed");
    assert.equal(await row("failed").count(), 50);
    await query("slow");
    await bounded(slowRequested, "Slow request did not start");
    await ready("slow", 1, "loading");
    assert.equal(await row("failed").count(), 0, "loading new subject immediately retires previous rows");
    await query("newer");
    await ready("newer");
    assert.equal(await row("newer").count(), 50);
    phase = "release and process superseded response";
    const slowFinished = page.waitForResponse(response => response.url().includes("subject_id=slow"));
    releaseSlow();
    await (await slowFinished).finished();
    await page.waitForFunction(() => window.__evidenceParsed.some(url => url.includes("subject_id=slow")));
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.equal(await row("slow").count(), 0, "late non-cancellable completion cannot replace newer rows");
    assert.equal(await row("newer").count(), 50);
    phase = "invalid deep link and clear";
    await page.goto("/evidence?subject_id=partial");
    await page.getByRole("alert").filter({ hasText: /请同时选择主体类型/ }).waitFor();
    await form.getByRole("button", { name: "清除筛选", exact: true }).click();
    await ready("");
    assert.deepEqual(unexpected, []);
    assert.deepEqual(external, []);
    assert.deepEqual(errors, []);
    return { width, status: "PASS", requestCount: requests.length, boundary: "Synthetic data, production list/create UI, no writes or live providers" };
  } catch (error) {
    // The fixture is synthetic. Preserve the failing screen and route/DOM/request
    // state rather than leaving only the earlier normal screenshot in CI artifacts.
    await page.screenshot({ path: join(output, `evidence-${width}-failure.png`), fullPage: false }).catch(() => {});
    const dom = await page.evaluate(() => ({ title: document.title, text: document.body.innerText })).catch(() => null);
    writeFileSync(join(output, `evidence-${width}-failure.json`), JSON.stringify({
      width, phase, error: error.message, url: page.url(), dom, requests, errors, unexpected, external,
    }, null, 2));
    throw error;
  } finally { releaseSlow(); await context.close(); }
}
async function main() {
  assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first");
  const output = process.env.EVIDENCE_LIST_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), "vr-evidence-list-"));
  mkdirSync(output, { recursive: true });
  const server = createServer((request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    let target = resolve(dist, `.${decodeURIComponent(pathname)}`);
    if (!target.startsWith(dist + sep) || !existsSync(target) || !extname(target)) target = join(dist, "index.html");
    response.setHeader("Content-Type", ({ ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" })[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  let browser;
  const result = { results: [], output };
  try {
    await new Promise((done, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", done); });
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
    const baseURL = `http://127.0.0.1:${server.address().port}`;
    for (const width of [1440, 390]) {
      try { result.results.push(await run(browser, baseURL, width, output)); }
      catch (error) {
        result.results.push({ width, status: "FAIL", error: error.message });
        console.error(`[Evidence ${width}] ${error.stack || error.message}`);
      }
    }
    assert.equal(result.results.filter(row => row.status !== "PASS").length, 0, "both evidence viewports must pass");
    console.log(JSON.stringify(result, null, 2));
  } catch (error) { result.error = error.message; throw error; }
  finally {
    writeFileSync(join(output, "results.json"), JSON.stringify(result, null, 2));
    await browser?.close();
    server.closeAllConnections();
    await new Promise(done => server.close(done));
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
