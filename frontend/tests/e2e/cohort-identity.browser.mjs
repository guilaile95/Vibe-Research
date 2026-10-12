// Actual production React card and API client under a synthetic date parent.
// No backend process, provider, model, credentials, or production archive access.
// Browser execution belongs to authorized CI; --build-only never starts one.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "playwright";
import { COHORT_DAY_A as dayA, COHORT_DAY_B as dayB, COHORT_CLOCK, cohortReply,
  validCohortQuery, validCohortStaticRequest, observeCohortReads } from "./cohort-identity.fixture.mjs";

import { waitForCohortLoading, waitForCohortMembers } from "./cohort-identity-readiness.mjs";

const frontend = fileURLToPath(new URL("../../", import.meta.url));
const output = process.env.COHORT_IDENTITY_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), "cohort-identity-dom-"));
mkdirSync(output, { recursive: true });
const dist = join(output, "component-dist");
process.chdir(frontend);
await build({ configFile: false, mode: "production", root: join(frontend, "tests/e2e/cohort-identity-adapter"),
  plugins: [react()], resolve: { alias: { "@": join(frontend, "src") } }, css: { postcss: frontend },
  build: { outDir: dist, emptyOutDir: true },
});
if (process.argv.includes("--build-only")) {
  console.log("Cohort member production component adapter built; browser NOT_RUN");
  process.exit(0);
}

const audit = { external: [], unexpected: [], reads: [], errors: [] };
let origin;
const server = createServer((request, response) => {
  const url = new URL(request.url, origin);
  if (request.headers.host !== new URL(origin).host || !validCohortStaticRequest(request.method, url.pathname, url.search)) {
    audit.unexpected.push(`static ${request.method} ${request.url}`); response.writeHead(403).end(); return;
  }
  if (url.pathname === "/favicon.ico") { response.writeHead(204).end(); return; }
  const target = url.pathname === "/" ? join(dist, "index.html") : resolve(dist, "." + url.pathname);
  if (!target.startsWith(resolve(dist) + sep) || !existsSync(target)) {
    audit.unexpected.push(`missing static ${url.pathname}`); response.writeHead(404).end(); return;
  }
  response.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[extname(target)]);
  createReadStream(target).pipe(response);
});
const gates = new Set();
const deferred = () => {
  let done;
  const promise = new Promise(resolve => { done = resolve; });
  const gate = { promise, release: () => { gates.delete(gate); done(); } };
  gates.add(gate); return gate;
};
const bounded = async promise => {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error("Expected synthetic cohort read did not arrive")), 10000); })]); }
  finally { clearTimeout(timer); }
};
const results = [];
let browser, activePage, activeWidth, phase = "startup", status = "FAIL";
const diagnostics = { failure: null, capture_errors: [] };
try {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, args: ["--disable-background-networking", "--dns-prefetch-disable", "--disable-features=NetworkPrediction"], ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: "block" });
    await context.addInitScript(observeCohortReads);
    await context.routeWebSocket("**/*", socket => { audit.external.push(`WebSocket ${socket.url()}`); socket.close(); });
    let mode = "normal", hold = null, readIndex = 0;
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== origin) { audit.external.push(request.url()); return route.abort(); }
      if (validCohortStaticRequest(request.method(), url.pathname, url.search)) return route.continue();
      audit.reads.push(`${request.method()} ${url.pathname}${url.search}`);
      if (!validCohortQuery(request.method(), url.pathname, url.search)) {
        audit.unexpected.push(request.url()); return route.fulfill({ status: 400, json: { detail: "UNEXPECTED_SYNTHETIC_READ" } });
      }
      const index = readIndex++, date = url.searchParams.get("trade_date");
      const reply = cohortReply(mode === "wrong-date" ? dayA : date, mode);
      if (mode === "unsafe-authority") reply.point_in_time_claim = "POINT_IN_TIME";
      if (mode === "empty-members") { reply.projection.rows = []; reply.evidence.previous.row_count = 0; }
      if (mode === "inconsistent-member") reply.projection.rows[0].current_source_code = "000001";
      if (hold && hold.date === date) {
        const selected = hold; hold = null; selected.index = index; selected.started.release();
        await selected.gate.promise;
      }
      return route.fulfill({ json: { data: reply } });
    });
    const page = await context.newPage(); activePage = page; activeWidth = width; phase = "initial members"; page.setDefaultTimeout(10000);
    page.on("pageerror", error => audit.errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") audit.errors.push(message.text()); });
    await page.clock.setFixedTime(new Date(COHORT_CLOCK));
    await page.goto(origin);
    const card = page.getByTestId("cohort-identity-card");
    const table = card.getByTestId("cohort-members-table");
    const readyMembers = day => waitForCohortMembers(card, table, day, cohortReply(day).previous_trade_date);
    const retry = card.getByRole("button", { name: "重新读取归档", exact: true });
    const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const rejectedRead = async action => {
      const index = readIndex;
      await action();
      await page.waitForFunction(index => window.__cohortReads[index]?.parsed, index);
      await settle();
      await card.getByRole("alert").waitFor();
      assert.equal(await table.count(), 0);
    };
    await readyMembers(dayA);
    assert.equal(await table.locator("tbody tr").count(), 2);
    await table.getByText("今日所选名单未出现", { exact: true }).waitFor();
    const absentRow = table.locator("tbody tr").filter({ hasText: "000001" });
    assert.match(await absentRow.innerText(), /未知/);
    await card.getByText("查看两日来源证据", { exact: true }).click();
    assert.ok((await card.innerText()).includes("a".repeat(64)));
    assert.ok((await card.innerText()).includes("b".repeat(64)));
    assert.ok((await card.innerText()).includes("当前存档版本的事后查阅，非历史时点可知数据"));
    assert.ok((await card.innerText()).includes(dayA));
    assert.ok((await card.innerText()).includes(dayB));
    results.push({ width, check: "individual source members, absent is not zero, two-date provenance and post-hoc scope" });

    await card.screenshot({ path: join(output, `cohort-initial-${width}.png`) });
    phase = "missing archive";
    mode = "unavailable";
    await retry.click();
    await card.getByText("缺少完整的两日名单归档，无法进行对照", { exact: true }).waitFor();
    assert.equal(await table.count(), 0);
    assert.equal(await card.getByText("今日所选名单未出现", { exact: true }).count(), 0);
    results.push({ width, check: "missing archive is unknown with no fabricated absence rows" });

    phase = "wrong date";
    mode = "wrong-date";
    await rejectedRead(() => page.getByRole("button", { name: dayB, exact: true }).click());
    results.push({ width, check: "wrong-date envelope is rejected rather than relabeled" });

    phase = "unsafe authority";
    mode = "unsafe-authority";
    await rejectedRead(() => retry.click());
    results.push({ width, check: "point-in-time authority escalation is rejected" });

    phase = "inconsistent member";
    mode = "inconsistent-member";
    await rejectedRead(() => retry.click());
    results.push({ width, check: "inconsistent false member cannot become a trusted absence" });

    phase = "unsupported empty members";
    mode = "empty-members";
    await rejectedRead(() => retry.click());
    results.push({ width, check: "normal empty membership cannot become a fabricated complete zero" });

    phase = "pending reread";
    mode = "normal";
    await page.getByRole("button", { name: dayA, exact: true }).click();
    await readyMembers(dayA);
    const late = { date: dayA, started: deferred(), gate: deferred(), index: -1 }; hold = late;
    await retry.click();
    await bounded(late.started.promise);
    await waitForCohortLoading(card, table);
    assert.equal(await table.count(), 0, "a pending reread hides old members");
    assert.ok((await card.innerText()).includes(`所选交易日：${dayA}`), "pending state still belongs to the held date");
    await card.screenshot({ path: join(output, `cohort-loading-${width}.png`) });
    phase = "superseded parsed reply";
    await page.getByRole("button", { name: dayB, exact: true }).click();
    await readyMembers(dayB);
    late.gate.release();
    await page.waitForFunction(index => window.__cohortReads[index]?.parsed, late.index);
    await settle();
    assert.equal(await page.evaluate(index => window.__cohortReads[index].aborted, late.index), true);
    await card.getByText("查看两日来源证据", { exact: true }).click();
    assert.ok((await card.innerText()).includes(dayB));
    assert.ok(!(await card.innerText()).includes(dayA));
    assert.equal(await table.locator("tbody tr").count(), 2);
    results.push({ width, check: "superseded parsed response cannot replace selected date and abort is observed" });

    phase = "empty date";
    await page.getByRole("button", { name: "清空日期", exact: true }).click();
    await card.getByText("等待页面交易日", { exact: false }).waitFor();
    assert.equal(await table.count(), 0);
    const readCount = readIndex;
    await page.getByRole("button", { name: "切换显示", exact: true }).click();
    await page.getByRole("button", { name: "切换显示", exact: true }).click();
    await card.getByText("等待页面交易日", { exact: false }).waitFor();
    await settle();
    assert.equal(readIndex, readCount);
    results.push({ width, check: "empty date and remount never invent a current-date read" });

    phase = "in-flight unmount";
    const unmounted = { date: dayA, started: deferred(), gate: deferred(), index: -1 }; hold = unmounted;
    await page.getByRole("button", { name: dayA, exact: true }).click();
    await bounded(unmounted.started.promise);
    await page.getByRole("button", { name: "切换显示", exact: true }).click();
    unmounted.gate.release();
    await page.waitForFunction(index => window.__cohortReads[index]?.parsed, unmounted.index);
    await settle();
    assert.equal(await page.evaluate(index => window.__cohortReads[index].aborted, unmounted.index), true);
    assert.equal(await card.count(), 0);
    await page.getByRole("button", { name: "切换显示", exact: true }).click();
    await readyMembers(dayA);
    assert.equal(readIndex, readCount + 2);
    results.push({ width, check: "in-flight unmount aborts and remount owns a fresh read" });

    await card.getByText("查看两日来源证据", { exact: true }).click();
    phase = "final layout";
    const layout = await card.evaluate(element => {
      const rect = element.getBoundingClientRect();
      return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, left: rect.left, right: rect.right,
        controls: [...element.querySelectorAll("button, summary")].map(control => {
          const box = control.getBoundingClientRect(); return { left: box.left, right: box.right, width: box.width };
        }) };
    });
    assert.ok(layout.documentWidth <= layout.viewport + 1);
    assert.ok(layout.left >= -1 && layout.right <= layout.viewport + 1);
    for (const control of layout.controls) assert.ok(control.width > 0 && control.left >= layout.left - 1 && control.right <= layout.right + 1);
    await card.screenshot({ path: join(output, `cohort-identity-${width}.png`) });
    results.push({ width, check: "member table and source hashes stay within desktop/mobile page width" });
    await context.close(); activePage = null;
  }
  assert.deepEqual(audit.external, []); assert.deepEqual(audit.unexpected, []); assert.deepEqual(audit.errors, []);
  assert.equal(results.length, 20);
  status = "PASS";
} catch (error) {
  diagnostics.failure = { width: activeWidth, phase, message: String(error?.message ?? error), stack: String(error?.stack ?? "") };
  // Capture while the held read is still pending, before cleanup releases gates.
  if (activePage && !activePage.isClosed()) {
    for (const [name, capture] of [
      ["dom", async () => writeFileSync(join(output, `failure-${activeWidth}.html`), await activePage.content(), "utf8")],
      ["state", async () => writeFileSync(join(output, `failure-${activeWidth}.json`), JSON.stringify(await activePage.evaluate(() => ({
        url: location.href, reads: window.__cohortReads ?? [], body_text: document.body.innerText,
      })), null, 2), "utf8")],
      ["screenshot", async () => activePage.screenshot({ path: join(output, `failure-${activeWidth}.png`), fullPage: true, timeout: 5000 })],
    ]) {
      try { await capture(); } catch (captureError) { diagnostics.capture_errors.push({ name, message: String(captureError) }); }
    }
  }
  throw error;
} finally {
  for (const gate of gates) gate.release();
  writeFileSync(join(output, "result.json"), JSON.stringify({ status,
    scope: "production cohort member card + API client; strict synthetic two-date readback, no live archive claim",
    backend_processes_started: 0, provider_requests: 0, results, audit, diagnostics }, null, 2));
  await browser?.close(); await new Promise(resolve => server.close(resolve));
}
console.log(JSON.stringify({ status, results: results.length, output }));
