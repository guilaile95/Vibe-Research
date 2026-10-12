/** Strict offline rendering/interaction acceptance. Golden API mocks are checked
 * separately against real service + temporary SQLite tests; this is NOT a
 * browser-to-real-database end-to-end claim. Never starts Python or providers. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { existsSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { observeIntegratedReads, runIntegratedReview, runSavedAiBasis } from "./daily-review-integrated.scenarios.mjs";
import { createFixture, golden, DAY, CLOCK, JOURNAL_VIEWPORTS } from "./next-day-verification.fixture.mjs";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const dist = path.join(frontend, "dist");
const evidenceDir = path.resolve(process.env.NEXT_DAY_VERIFICATION_EVIDENCE_DIR || path.join(tmpdir(), `vr-nextday-browser-${process.pid}`));
const pendingGates = new Set();
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); const gate = { promise, resolve }; pendingGates.add(gate); return gate; };
const withSealQuality = process.argv.includes("--with-seal-quality");
const violations = [];
const pageErrors = [];
const results = [];
const captures = [];
let currentViewport;
let browser, context, page, origin;
let fixture;
const fixtureRuns = [];
function resetFixture(label, options = {}) { fixture = createFixture(origin, { withSealQuality, ...options }); fixtureRuns.push({ label: `${currentViewport?.label || "setup"}/${label}`, fixture }); }
let dailyGate = deferred();
let writeGate = null;
let writeObserved = null;
const server = createServer((req, res) => {
  const raw = req.url || "/";
  if (req.method !== "GET" || req.headers.host !== new URL(origin).host || raw.startsWith("/api")) {
    violations.push(`escaped fixture request ${req.method} ${raw}`);
    res.writeHead(403).end(); return;
  }
  const relative = raw === "/daily-review" || raw === "/" ? "index.html" : raw.slice(1);
  const file = path.resolve(dist, relative);
  if (!file.startsWith(dist + path.sep) || !existsSync(file)) { res.writeHead(404).end(); return; }
  const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
  let bytes = readFileSync(file);
  if (path.extname(file) === ".html") {
    // Routing cannot catch speculative DNS/preconnect sockets. Strip hints and
    // external font stylesheets before the browser parses this offline HTML.
    bytes = Buffer.from(bytes.toString("utf8")
      .replace(/<link\b(?=[^>]*\brel=["'](?:preconnect|dns-prefetch)["'])[^>]*>/gi, "")
      .replace(/<link\b(?=[^>]*\bhref=["']https?:\/\/)[^>]*>/gi, ""));
  }
  res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" });
  res.end(bytes);
});

async function shot(name, requiredText) {
  const card = page.getByTestId("next-day-verification");
  await card.waitFor({ state: "visible" });
  if (requiredText) await card.getByText(requiredText, { exact: false }).first().waitFor({ state: "visible" });
  await card.scrollIntoViewIfNeeded();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  const state = await card.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const controls = [...element.querySelectorAll("input, select, button")].map((control) => {
      const box = control.getBoundingClientRect();
      return { label: control.getAttribute("aria-label") || control.textContent?.trim(),
        disabled: control.matches(":disabled"), visible: box.width > 0 && box.height > 0,
        left: box.left, right: box.right, width: box.width };
    });
    return { text: element.innerText, selectedDate: element.querySelector('input[type="date"]')?.value,
      left: rect.left, right: rect.right, width: rect.width, height: rect.height,
      clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, controls };
  });
  assert.ok(state.width > 0 && state.height > 0, "journal card must be painted");
  assert.ok(state.left >= -1 && state.right <= currentViewport.width + 1, "journal card must fit the real viewport");
  assert.ok(state.scrollWidth <= state.clientWidth + 1, "journal card must not horizontally overflow");
  for (const control of state.controls.filter((entry) => entry.visible)) {
    assert.ok(control.left >= state.left - 1 && control.right <= state.right + 1, `control must fit journal card: ${control.label}`);
  }
  const prefix = `${currentViewport.label}-${name}`;
  const files = [];
  // DailyReview scrolls inside <main>. Capturing an element taller than that
  // scrollport can still produce blank pixels. Crop only the visible card top,
  // then scroll/capture short state, controls and result regions separately.
  await card.evaluate((element) => element.scrollIntoView({ block: "start", inline: "nearest", behavior: "instant" }));
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const clip = await card.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const main = element.closest("main")?.getBoundingClientRect() || { top: 0, bottom: innerHeight, left: 0, right: innerWidth };
    const x = Math.max(0, box.left, main.left), y = Math.max(0, box.top, main.top);
    return { x, y, width: Math.min(innerWidth, box.right, main.right) - x,
      height: Math.min(innerHeight, box.bottom, main.bottom) - y };
  });
  assert.ok(clip.width > 0 && clip.height > 100, "card top must be inside the main scrollport");
  files.push(`${prefix}-card-top.png`, `${prefix}-viewport.png`);
  await page.screenshot({ path: path.join(evidenceDir, files[0]), clip, animations: "disabled", caret: "hide" });
  await page.screenshot({ path: path.join(evidenceDir, files[1]), fullPage: false, animations: "disabled", caret: "hide" });
  async function captureRegion(locator, label) {
    if (!await locator.count()) return;
    await locator.scrollIntoViewIfNeeded();
    const box = await locator.boundingBox();
    assert.ok(box && box.height <= currentViewport.height - 100, `${label} must fit in the scrollport`);
    const region = await locator.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const main = element.closest("main")?.getBoundingClientRect() || { top: 0, bottom: innerHeight };
      return { top: box.top, bottom: box.bottom, clipTop: Math.max(0, main.top), clipBottom: Math.min(innerHeight, main.bottom) };
    });
    assert.ok(region.top >= region.clipTop - 1 && region.bottom <= region.clipBottom + 1, `${label} must be fully visible before capture`);
    const filename = `${prefix}-${label}.png`;
    await locator.screenshot({ path: path.join(evidenceDir, filename), animations: "disabled", caret: "hide" });
    files.push(filename);
  }
  if (requiredText) await captureRegion(card.getByText(requiredText, { exact: false }).first(), "state");
  await captureRegion(card.locator("fieldset"), "controls");
  await captureRegion(card.locator("div").filter({ hasText: "事前冻结值" }).last(), "saved-result");
  await captureRegion(card.getByText(/^近 60 个交易日条件：/), "coverage");
  captures.push({ name: prefix, viewport: currentViewport, requiredText: requiredText || null, ...state, files });
  results.push(prefix);
}

async function readyDate(day) {
  await page.waitForFunction((expected) => {
    const card = document.querySelector('[data-testid="next-day-verification"]');
    return card?.querySelector('input[type="date"]')?.value === expected
      && !card.textContent.includes("正在读取验证记录") && card.textContent.includes("下一交易日：");
  }, day);
}
const body = (revision, direction, reason) => ({ revision, items: direction ? [{ metric: "limit_up_count", direction, reason }] : [] });

try {
  assert.ok(existsSync(path.join(dist, "index.html")), "Build the production frontend before browser acceptance");
  mkdirSync(evidenceDir, { recursive: true });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ["--disable-background-networking", "--dns-prefetch-disable", "--disable-features=NetworkPrediction"] });
  for (const viewport of JOURNAL_VIEWPORTS) {
  currentViewport = viewport;
  dailyGate = deferred();
  resetFixture("save-conflict-clear");
  context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, locale: "zh-CN", timezoneId: "America/Los_Angeles", serviceWorkers: "block" });
  await context.routeWebSocket("**/*", (ws) => { violations.push(`WebSocket forbidden ${ws.url()}`); ws.close(); });
  await context.route("**/*", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.origin === origin && url.pathname === "/api/daily-review" && req.method() === "GET") await dailyGate.promise;
    const expectedWriteTarget = url.origin === origin && req.method() === "PUT" && url.pathname === `/api/next-day-verification/${DAY}` && !url.search;
    let payload;
    if (expectedWriteTarget && req.postData()) {
      try { payload = req.postDataJSON(); } catch { /* Invalid JSON is denied by the exact payload fixture. */ }
    }
    const result = fixture.handle(req.url(), req.method(), payload);
    if (result.kind === "deny") return route.abort("blockedbyclient");
    if (result.kind === "static") return route.continue();
    if (req.method() === "PUT") writeObserved?.resolve();
    const gate = req.method() === "PUT" ? writeGate : null;
    if (gate) { writeGate = null; await gate.promise; }
    try { await route.fulfill({ status: result.status, contentType: "application/json", body: JSON.stringify(result.body) }); }
    catch (error) {
      // A superseded read can be intentionally cancelled by the production UI.
      if (req.method() !== "GET" || !/closed|canceled|cancelled|invalid interception|already handled/i.test(String(error))) throw error;
    }
  });
  await context.addInitScript(() => {
    // No watchlist import, model credentials, or stored research fixtures.
    localStorage.clear();
    const original = window.fetch.bind(window);
    window.__journalHeld = [];
    window.__holdJournalDate = null;
    window.fetch = (input, init) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.origin);
      const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
      if (url.origin === location.origin && method === "GET" && window.__holdJournalDate && url.pathname === `/api/next-day-verification/${window.__holdJournalDate}`) {
        window.__holdJournalDate = null;
        // Deliberately ignore abort to prove the component's response ownership,
        // rather than allowing transport cancellation to hide stale-read defects.
        return new Promise((resolve) => window.__journalHeld.push({ url: url.pathname, method, signal: init?.signal, resolve }));
      }
      return original(input, init);
    };
  });
  await context.addInitScript(observeIntegratedReads);
  page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.clock.setFixedTime(new Date(CLOCK));
  await page.goto(`${origin}/daily-review`, { waitUntil: "domcontentloaded" });
  let card = page.getByTestId("next-day-verification");
  await readyDate("2026-08-03");
  assert.match(await card.innerText(), /尚未收盘/);
  assert.equal(fixture.writes.length, 0);
  dailyGate.resolve();
  await readyDate(DAY);
  await card.getByText(/可记录，下一交易日/).waitFor();
  assert.ok(fixture.requests.some((r) => r.url === `${origin}/api/next-day-verification/2026-08-03`));
  if (withSealQuality) {
    await page.locator("#market-detail-short-history > summary").click();
    const seal = page.getByTestId("seal-quality-card");
    await seal.getByText("封板质量归档证据未连接；不会自动启用采集或请求行情。", { exact: true }).waitFor();
    assert.equal(await seal.getByTestId("seal-never_broken_ratio").count(), 0);
    results.push(`${currentViewport.label}-integrated-seal-archive-unconnected-smoke`);
    const cohort = page.getByTestId("cohort-identity-card");
    await cohort.getByText("缺少完整的两日名单归档，无法进行对照", { exact: true }).waitFor();
    assert.equal(await cohort.getByTestId("cohort-members-table").count(), 0);
    results.push(`${currentViewport.label}-integrated-cohort-archive-missing-smoke`);
    const readiness = page.getByTestId("evidence-readiness-card");
    await readiness.getByTestId("readiness-seal_quality").getByText("封板质量：未连接归档", { exact: true }).waitFor();
    await readiness.getByTestId("readiness-cohort_identity").getByText("两日名单：缺少所需归档", { exact: true }).waitFor();
    await readiness.getByTestId("readiness-next_day_verification").getByText("明日验证事前事实：缺少所需归档", { exact: true }).waitFor();
    results.push(`${currentViewport.label}-integrated-readiness-missing-smoke`);

  }
  await shot("01-cold-canonical-and-loaded-date", "可记录，下一交易日");

  await card.getByLabel("涨停家数方向").selectOption("up");
  await card.getByLabel("涨停家数理由").fill("Synthetic prior condition");
  assert.equal(fixture.writes.length, 0, "editing never autosaves");
  fixture.expectSave(body(0, "up", "Synthetic prior condition"), "open_saved");
  const saveGate = deferred(); writeGate = saveGate; writeObserved = deferred();
  await card.getByRole("button", { name: "保存整晚条件", exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="验证复盘交易日"]').disabled);
  assert.equal(await card.getByLabel("涨停家数方向").isDisabled(), true);
  await card.getByRole("button", { name: "保存中…", exact: true }).evaluate((el) => el.click());
  await writeObserved.promise;
  assert.equal(fixture.writes.length, 1, "repeated save while pending must not duplicate");
  saveGate.resolve();
  await card.getByText(/已保存；仅记录研究条件/).waitFor();
  await card.getByText(/待下一交易日收盘/).waitFor();
  await shot("02-explicit-save-missing-prior", "待下一交易日收盘");

  await card.getByLabel("涨停家数方向").selectOption("down");
  await card.getByLabel("涨停家数理由").fill("Unsaved input survives failure");
  fixture.expectSave(body(1, "down", "Unsaved input survives failure"), null, 503);
  await card.getByRole("button", { name: "保存整晚条件", exact: true }).click();
  await card.getByText(/输入已保留/).waitFor();
  assert.equal(await card.getByLabel("涨停家数理由").inputValue(), "Unsaved input survives failure");
  await shot("03a-save-error-retains-input", "验证记录不可写入，未保存修改");
  fixture.expectSave(body(1, "down", "Unsaved input survives failure"), "open_external", 409);
  await card.getByRole("button", { name: "保存整晚条件", exact: true }).click();
  await card.getByText(/记录已改变/).waitFor();
  await shot("03b-revision-conflict", "记录已改变，请重新读取后再保存");
  await card.getByRole("button", { name: /重新读取/ }).click();
  await card.getByText(/条件版本：2/).waitFor();
  assert.equal(await card.getByLabel("涨停家数理由").inputValue(), "Saved by another window");
  await card.getByLabel("涨停家数方向").selectOption("");
  fixture.expectSave(body(2, null), "open_cleared");
  await card.getByRole("button", { name: "保存为空（清除本晚条件）", exact: true }).click();
  await card.getByText(/条件版本：3/).waitFor();
  await shot("03c-conflict-recovery-explicit-clear", "条件版本：3");

  // Start a separate synthetic journal for sealed rendering. Never resurrect a
  // cleared row or move revision3 back to revision2 within the same fixture.
  await page.close();
  resetFixture("independent-sealed-and-calendar-state");
  fixture.setView(DAY, "sealed_missing");
  fixture.setView("2026-08-03", "after_close_today");
  page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.clock.setFixedTime(new Date("2026-08-03T07:10:00Z"));
  await page.goto(`${origin}/daily-review`, { waitUntil: "domcontentloaded" });
  card = page.getByTestId("next-day-verification");
  await card.getByText("已封存，不能修改或删除", { exact: true }).waitFor();
  await card.getByText(/待核验：缺少合格事前值或收盘事实/).waitFor();
  assert.equal(await card.getByLabel("涨停家数方向").isDisabled(), true);
  assert.equal(await card.getByRole("button", { name: "保存整晚条件", exact: true }).isDisabled(), true);
  const count = fixture.writes.length;
  await card.getByRole("button", { name: "保存整晚条件", exact: true }).evaluate((el) => el.click());
  assert.equal(fixture.writes.length, count);
  assert.doesNotMatch(await card.innerText(), /· 不成立/);
  await shot("04-sealed-missing-is-not-failure", "已封存，不能修改或删除");
  await card.getByLabel("验证复盘交易日").fill("2026-12-31");
  await card.getByText(/交易日历未知或日期不是支持的交易日/).waitFor();
  assert.equal(await card.getByRole("button", { name: "保存为空（清除本晚条件）", exact: true }).isDisabled(), true);
  await shot("05-unknown-calendar-blocks-writes", "交易日历未知或日期不是支持的交易日");

  // Another independent pre-seal journal owns the delayed-read tests.
  await page.close();
  resetFixture("independent-preseal-date-races");
  fixture.setView(DAY, "open_saved");
  page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.clock.setFixedTime(new Date(CLOCK));
  await page.goto(`${origin}/daily-review`, { waitUntil: "domcontentloaded" });
  card = page.getByTestId("next-day-verification");
  await card.getByText(/条件版本：1/).waitFor();
  await page.evaluate(() => { window.__holdJournalDate = "2026-07-30"; });
  await card.getByLabel("验证复盘交易日").fill("2026-07-30");
  await page.waitForFunction(() => window.__journalHeld.length === 1);
  await card.getByLabel("验证复盘交易日").fill(DAY);
  await card.getByText(/条件版本：1/).waitFor();
  assert.equal(await page.evaluate(() => window.__journalHeld[0].signal.aborted), true);
  await page.evaluate((payload) => window.__journalHeld[0].resolve(new Response(JSON.stringify({ data: payload }), { status: 200, headers: { "Content-Type": "application/json" } })), golden.older);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await card.getByLabel("验证复盘交易日").inputValue(), DAY);
  assert.doesNotMatch(await card.innerText(), /OLDER_RESPONSE_MUST_NOT_REPLACE_CURRENT/);
  assert.equal(fixture.writes.length, count);
  await shot("06-stale-date-response-suppressed", "条件版本：1");

  fixture.failGet(DAY);
  await card.getByRole("button", { name: /重新读取/ }).click();
  await card.getByText(/验证记录不可读取，已停止操作/).waitFor();
  assert.equal(await card.getByLabel("涨停家数方向").count(), 0, "failed read hides stale editor");
  await shot("07a-read-error", "验证记录不可读取，已停止操作");
  await card.getByRole("button", { name: /重新读取/ }).click();
  await card.getByText(/条件版本：1/).waitFor();
  await shot("07b-read-error-recovery", "条件版本：1");
  await page.close();

  // Late market data must not overwrite a date deliberately chosen by the user.
  dailyGate = deferred();
  page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.clock.setFixedTime(new Date(CLOCK));
  await page.goto(`${origin}/daily-review`, { waitUntil: "domcontentloaded" });
  card = page.getByTestId("next-day-verification");
  await readyDate("2026-08-03");
  await card.getByLabel("验证复盘交易日").fill("2026-12-31");
  await card.getByText(/交易日历未知或日期不是支持的交易日/).waitFor();
  dailyGate.resolve();
  await page.getByTestId("daily-review-refresh").waitFor();
  // Wait for the actual market response and ensuing state to settle.
  await page.waitForFunction(() => document.body.textContent.includes("2026-07-31 · 当前市场快照"));
  assert.equal(await card.getByLabel("验证复盘交易日").inputValue(), "2026-12-31");
  await shot("08-user-date-survives-late-market-response", "交易日历未知或日期不是支持的交易日");
  if (withSealQuality) {
    await page.close();
    resetFixture("full-current-history-readonly-acceptance", { fullReview: true });
    page = await context.newPage();
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.clock.setFixedTime(new Date(CLOCK));
    await page.goto(`${origin}/daily-review`, { waitUntil: "domcontentloaded" });
    await runIntegratedReview({ page, fixture, viewport, evidenceDir, results, captures, shot });
    for (const aiMode of ["v1", "malformed_v2"]) {
      await page.close();
      resetFixture(`saved-ai-basis-${aiMode}`, { fullReview: true, aiMode });
      page = await context.newPage();
      page.on("pageerror", (error) => pageErrors.push(error.message));
      await page.clock.setFixedTime(new Date(CLOCK));
      await page.goto(`${origin}/daily-review`, { waitUntil: "domcontentloaded" });
      await runSavedAiBasis({ page, viewport, evidenceDir, results, captures, mode: aiMode });
      assert.equal(fixture.writes.length, 0, "restoring saved AI never writes or invokes models");
    }
  }
  await context.close();
  context = undefined;
  }
  for (const run of fixtureRuns) { assert.deepEqual(run.fixture.expectedWrites, [], run.label); assert.deepEqual(run.fixture.violations, [], run.label); }
  assert.deepEqual(violations, []);
  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ status: "passed", scenarios: results, explicit_puts: fixtureRuns.reduce((sum, run) => sum + run.fixture.writes.length, 0), unexpected_requests: 0 }));
} catch (error) {
  if (page && !page.isClosed()) {
    const prefix = currentViewport?.label || "setup";
    writeFileSync(path.join(evidenceDir, `${prefix}-failure-dom.html`), await page.content(), "utf8");
    await page.getByTestId("next-day-verification").screenshot({ path: path.join(evidenceDir, `${prefix}-failure-card.png`), animations: "disabled" }).catch(() => {});
    await page.screenshot({ path: path.join(evidenceDir, `${prefix}-failure-viewport.png`), fullPage: false }).catch(() => {});
  }
  process.exitCode = 1;
  console.error(error);
} finally {
  for (const gate of pendingGates) gate.resolve();
  mkdirSync(evidenceDir, { recursive: true });
  writeFileSync(path.join(evidenceDir, "results.json"), JSON.stringify({ scenarios: results, viewports: JOURNAL_VIEWPORTS, captures, fixtureRuns: fixtureRuns.map(({ label, fixture: f }) => ({ label, requests: f.requests, writes: f.writes })), violations: [...violations, ...fixtureRuns.flatMap(({ fixture: f }) => f.violations)], pageErrors, passed: !process.exitCode }, null, 2));
  await context?.close();
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
