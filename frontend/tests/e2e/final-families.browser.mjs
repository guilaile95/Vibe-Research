// Final four original QA families: synthetic streams + isolated real production
// upload/history/calendar routes. No user files, provider/model or scheduler.
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { syntheticLlm, plan, encode, debateEvents, ancillaryReply, realRouteAllowed, observeHistoryReads } from "./final-families.fixture.mjs";
const frontend = fileURLToPath(new URL("../../", import.meta.url)), dist = join(frontend, "dist");
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { resolve, promise }; };
async function bounded(promise, label) {
  let timer; try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Timed out: ${label}`)), 10000); })]); } finally { clearTimeout(timer); }
}
export async function stopBackend(child, graceMs = 5000) {
  if (!child || !child.pid || child.exitCode !== null || child.signalCode !== null) return;
  const exited = new Promise(done => child.once("exit", done));
  child.kill("SIGTERM");
  let timer;
  try {
    const ended = await Promise.race([exited.then(() => true), new Promise(done => { timer = setTimeout(() => done(false), graceMs); })]);
    if (!ended) { child.kill("SIGKILL"); await bounded(exited, "isolated backend kill/exit"); }
  } finally { clearTimeout(timer); }
}
async function startBackend(baseURL) {
  const root = mkdtempSync(join(tmpdir(), "vr-final-acceptance-"));
  for (const dir of ["home", "tmp", "data", "reports"]) mkdirSync(join(root, dir));
  const reservation = createServer(); await new Promise(done => reservation.listen(0, "127.0.0.1", done));
  const port = reservation.address().port; await new Promise(done => reservation.close(done));
  const env = { ...process.env, VR_FINAL_FIXTURE_ROOT: root, VR_DATA_DIR: join(root, "data"), VR_REPORTS_DIR: join(root, "reports"),
    VIBE_RESEARCH_REVIEW_DB: join(root, "review.db"), VIBE_RESEARCH_CAMPAIGN_DB: join(root, "campaign.db"), VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(root, "evidence.db"),
    HOME: join(root, "home"), USERPROFILE: join(root, "home"), TMPDIR: join(root, "tmp"), TEMP: join(root, "tmp"), TMP: join(root, "tmp"),
    PYTHONDONTWRITEBYTECODE: "1", VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH: "1", VR_API_KEY: "", VR_ALLOW_ORIGINS: baseURL };
  const child = spawn(process.env.PYTHON || "python", ["-m", "uvicorn", "final_acceptance_harness_app:app", "--app-dir", join(frontend, "tests/e2e"), "--host", "127.0.0.1", "--port", String(port)], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
  let logs = "", spawnError = null;
  child.on("error", error => { spawnError = error; });
  child.stdout.on("data", chunk => { logs += chunk; }); child.stderr.on("data", chunk => { logs += chunk; });
  const url = `http://127.0.0.1:${port}`;
  try {
    const deadline = Date.now() + 20000;
    for (let i = 0; i < 100 && Date.now() < deadline; i++) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null || child.signalCode !== null) throw new Error(`Isolated backend exited: ${logs.slice(-4000)}`);
      try { if ((await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(1000) })).ok) return { child, root, url }; } catch {}
      await new Promise(done => setTimeout(done, 200));
    }
    throw new Error(`Isolated backend startup timeout: ${logs.slice(-4000)}`);
  } catch (error) { await stopBackend(child); throw error; }
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


async function runScenario(browser, baseURL, backend, width, scenario, evidenceDir) {
  let context, page;
  const errors = [], external = [], unexpected = [], requests = [], realResponses = [], uploads = [], holds = [], checks = [];
  let debateMode = "bull-eof", reflectionComplete = false;
  try {
    context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
    await context.addInitScript(observeHistoryReads);
    await context.routeWebSocket("**/*", socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
      if (url.origin !== baseURL) { external.push(url.origin); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      requests.push(`${request.method()} ${url.pathname}${url.search}`);
      if (scenario === "debate" && request.method() === "POST" && url.pathname === "/api/debate") {
        const body = request.postDataJSON(); assert.deepEqual(body.llm, syntheticLlm); assert.equal(body.code, "600519");
        return route.fulfill({ contentType: "application/x-ndjson", body: encode(debateEvents(body.rounds, debateMode)) });
      }
      if (scenario === "notes-mobile" && request.method() === "POST" && url.pathname === "/api/reflect") {
        const body = request.postDataJSON(); assert.deepEqual(body.llm, syntheticLlm);
        return route.fulfill({ contentType: "application/x-ndjson", body: encode([{ type: "delta", text: "SYNTHETIC_MOBILE_AUDIT" }, ...(reflectionComplete ? [{ type: "done", content: "SYNTHETIC_MOBILE_AUDIT", truncated: true }] : [])]) });
      }
      if (realRouteAllowed(request.method(), url.pathname, scenario)) {
        const response = await route.fetch({ url: backend.url + url.pathname + url.search, timeout: 10000 });
        const body = await response.json();
        const record = { method: request.method(), path: url.pathname + url.search, status: response.status() };
        realResponses.push(record);
        if (request.method() === "POST") uploads.push(request.postDataJSON().name);
        const date = url.searchParams.get("trade_date");
        if (scenario.startsWith("history-") && date) {
          const hold = holds.find(h => !h.started && h.date === date);
          assert.ok(hold, `unplanned filtered history read ${date}`);
          assert.equal(response.status(), 200); assert.equal(body.data.items.length, 1); assert.equal(body.data.items[0].trade_date, date);
          hold.started = true; hold.actual = body; hold.ready.resolve(); await hold.release.promise;
          if (hold.fail) { record.deliveredStatus = 503; return route.fulfill({ status: 503, json: { detail: "SYNTHETIC_HISTORY_FAILURE" } }); }
        }
        return route.fulfill({ response, json: body });
      }
      const reply = ancillaryReply(request.method(), url.pathname, url.search);
      if (reply !== null) return route.fulfill({ json: reply });
      unexpected.push(`${request.method()} ${url.pathname}${url.search}`);
      return route.fulfill({ status: 503, json: { detail: "UNEXPECTED_SYNTHETIC_REQUEST" } });
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => errors.push(error.message)); page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    const notes = () => page.evaluate(() => JSON.parse(localStorage.getItem("vr-notes") || "[]"));
    if (scenario === "debate" || scenario === "notes-mobile") {
      await page.goto("/__storage_probe");
      await page.evaluate(cfg => localStorage.setItem("vr-llm", JSON.stringify(cfg)), syntheticLlm);
      if (scenario === "debate") {
        await page.goto("/debate"); await page.getByRole("heading", { name: "多空辩论", exact: true }).waitFor();
        const start = async rounds => {
          await page.getByPlaceholder("6 位代码，如 600519", { exact: true }).fill("600519");
          await page.locator("select").selectOption(String(rounds));
          await page.getByRole("button", { name: "开始辩论", exact: true }).click();
        };
        for (const mode of ["bull-eof", "all-eof"]) {
          debateMode = mode; await start(1); await page.getByText("辩论失败", { exact: true }).waitFor();
          await page.getByText("SYNTHETIC_bull", { exact: true }).waitFor();
          assert.equal(await page.getByText("辩论完成", { exact: true }).count(), 0);
          assert.equal(await page.getByRole("button", { name: "存入沉淀", exact: true }).count(), 0);
          assert.deepEqual(await notes(), []);
        }
        checks.push("bull-only and all-stage EOF without done retain partial UI but cannot save");
        debateMode = "complete";
        for (const rounds of [1, 2]) {
          await start(rounds); await page.getByText("辩论完成", { exact: true }).waitFor();
          for (const stage of plan(rounds)) await page.getByText(`SYNTHETIC_${stage}`, { exact: true }).waitFor();
          await page.getByPlaceholder("6 位代码，如 600519", { exact: true }).fill("000001");
          await page.getByRole("button", { name: "存入沉淀", exact: true }).click();
          await page.getByRole("button", { name: "已存入沉淀", exact: true }).waitFor();
          const saved = (await notes())[0]; assert.match(saved.title, /600519/); assert.doesNotMatch(saved.title, /000001/);
          for (const stage of plan(rounds)) assert.ok(saved.content.includes(`SYNTHETIC_${stage}`));
        }
        assert.equal((await notes()).length, 2); await page.reload(); assert.equal((await notes()).length, 2);
        checks.push("real done + complete three/five stages save original ticker and survive reload");
      } else {
        await page.evaluate(() => localStorage.setItem("vr-notes", JSON.stringify([{ id: "synthetic-mobile-note", kind: "复盘", title: "SYNTHETIC_MOBILE_NOTE", content: "SYNTHETIC_ORIGINAL_CONTENT", ts: 1 }])));
        await page.goto("/notes"); await page.getByText("SYNTHETIC_MOBILE_NOTE", { exact: true }).click();
        await page.getByRole("button", { name: "反思审计", exact: true }).click();
        await page.getByRole("alert").filter({ hasText: "反思未完整结束" }).waitFor();
        assert.equal(await page.getByRole("button", { name: "把审计结果存为新记录", exact: true }).count(), 0); assert.equal((await notes()).length, 1);
        reflectionComplete = true; await page.getByRole("button", { name: "反思审计", exact: true }).click();
        await page.getByRole("button", { name: "把审计结果存为新记录", exact: true }).click();
        await page.getByRole("button", { name: "已存为新记录", exact: true }).waitFor();
        const saved = (await notes()).find(note => note.kind === "反思审计"); assert.match(saved.content, /未覆盖全文/); assert.match(saved.content, /SYNTHETIC_MOBILE_AUDIT/);
        await page.reload(); assert.equal((await notes()).length, 2); assert.equal((await notes()).filter(note => note.kind === "反思审计").length, 1);
        checks.push("mobile delta+EOF forbids reflection save; complete truncated retry saves honestly and reloads");
      }
    } else if (scenario.startsWith("history-")) {
      await page.goto("/daily-review"); await page.getByTestId("today-view-tab-history").click();
      const input = page.getByLabel("交易日期", { exact: true }); await input.waitFor();
      const row = date => page.getByRole("row").filter({ has: page.getByRole("cell", { name: date, exact: true }) });
      await row("2026-09-06").waitFor();
      const hold = async (date, fail = false) => {
        const h = { date, fail, ready: deferred(), release: deferred(), started: false, index: await page.evaluate(() => window.__historyReads.length) }; holds.push(h);
        await input.fill(date); await bounded(h.ready.promise, "actual SQLite history read"); return h;
      };
      const release = async h => {
        h.release.resolve(); await page.waitForFunction(i => window.__historyReads[i]?.parsed, h.index);
        await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
      };
      for (const round of [1, 2]) {
        const a = await hold("2026-09-05", scenario === "history-late-error"), b = await hold("2026-09-06");
        if (round === 1) { await release(b); await row("2026-09-06").waitFor(); assert.equal(await row("2026-09-05").count(), 0); }
        await release(a); assert.equal(await input.inputValue(), "2026-09-06");
        assert.equal(await row("2026-09-05").count(), 0);
        assert.doesNotMatch(await page.locator("main").innerText(), /历史记录加载失败|SYNTHETIC_HISTORY_FAILURE/);
        if (round === 2) { await page.getByText("刷新中…", { exact: true }).waitFor(); await release(b); }
        await row("2026-09-06").waitFor(); assert.equal(await page.locator("tbody tr").count(), 1);
      }
      if (scenario === "history-late-error") {
        const current = await hold("2026-09-05", true); await release(current);
        await page.getByText(/历史记录加载失败：SYNTHETIC_HISTORY_FAILURE/).waitFor(); assert.equal(await page.locator("tbody tr").count(), 0);
        const retry = { date: "2026-09-05", fail: false, ready: deferred(), release: deferred(), started: false, index: await page.evaluate(() => window.__historyReads.length) }; holds.push(retry);
        await page.getByTitle("刷新历史列表", { exact: true }).click(); await bounded(retry.ready.promise, "history retry"); await release(retry); await row("2026-09-05").waitFor();
      }
      checks.push("old actual SQLite date response released after newer row completion; stale success/error/finalizer cannot change row/filter/loading; current error retry tested separately");
      await input.scrollIntoViewIfNeeded();
    } else if (scenario === "calendar-422") {
      await page.goto("/decision-inbox"); const calendar = page.getByTestId("research-event-calendar");
      await calendar.getByTestId("research-event-empty-universe").waitFor();
      const from = calendar.getByLabel("起始日期（自然日）"), to = calendar.getByLabel("结束日期（自然日）");
      const initialFrom = await from.inputValue(), initialTo = await to.inputValue(); assert.ok(initialFrom && initialTo);
      await from.fill("2000-01-01"); await to.fill("2000-01-02"); await calendar.getByRole("button", { name: "应用范围", exact: true }).click();
      await calendar.getByTestId("research-event-calendar-error").filter({ hasText: "date_from 超出最大回溯范围" }).waitFor();
      assert.equal(await from.isVisible(), true); assert.equal(await to.isVisible(), true); assert.ok(realResponses.some(r => r.status === 422));
      await from.fill(initialFrom); await to.fill(initialTo);
      const before = realResponses.length;
      await Promise.all([
        page.waitForResponse(r => new URL(r.url()).pathname === "/api/research-events" && r.status() === 422),
        calendar.getByTestId("research-event-calendar-refresh").click(),
      ]);
      assert.ok(realResponses.length > before); assert.ok(realResponses.at(-1).path.includes("date_from=2000-01-01"), "Refresh uses last applied window, not unsubmitted draft");
      assert.equal(await from.inputValue(), initialFrom); assert.equal(await to.inputValue(), initialTo);
      await calendar.getByRole("button", { name: "应用范围", exact: true }).click();
      await calendar.getByTestId("research-event-empty-universe").waitFor(); assert.equal(await calendar.getByTestId("research-event-calendar-error").count(), 0);
      assert.equal(realResponses.at(-1).status, 200); await from.scrollIntoViewIfNeeded();
      checks.push("actual production422 from too-old ordered dates keeps controls; unapplied draft is not refreshed; corrected Apply returns200 without reload/provider");
    } else if (scenario === "report-upload") {
      const prefix = `SYNTHETIC_${width}_`, first = `${prefix}first.txt`, bad = `${prefix}rejected.html`, retry = `${prefix}retry.txt`, third = `${prefix}third.txt`;
      const contents = Object.fromEntries([first, bad, retry, third].map(name => [name, `${name}: SYNTHETIC_FIXTURE_BYTES`]));
      const file = name => ({ name, mimeType: "text/plain", buffer: Buffer.from(contents[name]) });
      await page.goto("/my-reports"); const input = page.locator('input[type="file"]');
      await input.setInputFiles([file(first), file(bad), file(third)]);
      await page.getByText(/已上传 1 份.*上传失败.*后续文件未上传/).waitFor();
      assert.deepEqual(uploads, [first, bad]);
      const listing = async () => { const response = await fetch(backend.url + "/api/myreports", { signal: AbortSignal.timeout(10000) }); assert.equal(response.status, 200); return (await response.json()).data.filter(r => r.name.startsWith(prefix)); };
      let records = await listing(); assert.deepEqual(records.map(r => r.name), [first]);
      await page.locator(`[id="report-${records[0].id}"]`).waitFor();
      const index = () => JSON.parse(readFileSync(join(backend.root, "reports/index.json"), "utf8")).filter(r => r.name.startsWith(prefix));
      assert.deepEqual(index().map(r => r.name), [first]);
      const verifyBytes = records => { for (const record of records) { assert.match(record.id, /^[a-f0-9]{32}$/); assert.equal(record.ext, ".txt"); assert.equal(readFileSync(join(backend.root, "reports", record.id + record.ext), "utf8"), contents[record.name]); } };
      verifyBytes(records);
      await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-partial.png`), fullPage: true });
      await input.setInputFiles([file(retry), file(third)]);
      await page.getByRole("checkbox", { name: `选择 ${third.slice(0, -4)}`, exact: true }).waitFor();
      assert.deepEqual(uploads, [first, bad, retry, third]); records = await listing(); assert.equal(records.length, 3); verifyBytes(records);
      assert.deepEqual(index().map(r => r.name).sort(), [first, retry, third].sort());
      assert.equal(index().some(r => r.name === bad), false);
      await page.reload(); for (const record of records) await page.locator(`[id="report-${record.id}"]`).waitFor();
      checks.push("actual production upload writes first bytes/index and UI before reload; native400 rejects html, third not submitted; explicit corrected retry persists remaining files and reloads");
    }
    assert.deepEqual(unexpected, []); assert.deepEqual(external, []);
    const failureCount = realResponses.filter(r => (r.deliveredStatus ?? r.status) >= 400).length;
    assert.equal(errors.filter(e => /Failed to load resource.*(400|422|503)/.test(e)).length, failureCount);
    assert.deepEqual(errors.filter(e => !/Failed to load resource.*(400|422|503)/.test(e)), []);
    assert.equal(await page.locator("vite-error-overlay").count(), 0); assert.ok((await page.title()).trim());
    const audit = await (await fetch(backend.url + "/api/e2e/final-audit", { signal: AbortSignal.timeout(10000) })).json(); assert.deepEqual(audit.violations, []); assert.equal(audit.reports_root_isolated, true);
    await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-pass.png`), fullPage: true });
    return { scenario, width, status: "PASS", checks, requests, realResponses, historyReads: await page.evaluate(() => window.__historyReads), guardViolations: audit.violations };
  } catch (error) {
    await page?.screenshot({ path: join(evidenceDir, `${scenario}-${width}-failure.png`), fullPage: true }).catch(() => {});
    throw new Error(`${scenario} ${width}px: ${error.message}; ${JSON.stringify({ errors, unexpected, external, requests, realResponses })}`, { cause: error });
  } finally { holds.forEach(h => h.release.resolve()); await context?.close(); }
}
async function main() {
  const evidenceDir = process.env.FINAL_FAMILIES_EVIDENCE_DIR || mkdtempSync(join(tmpdir(), "vr-final-family-evidence-")); mkdirSync(evidenceDir, { recursive: true });
  const git = arg => execFileSync("git", ["rev-parse", arg], { cwd: frontend, encoding: "utf8" }).trim();
  const result = { checkoutHead: git("HEAD"), checkoutTree: git("HEAD^{tree}"), frontendSourceTree: git("HEAD:frontend/src"), pullRequestHead: process.env.FINAL_FAMILIES_PR_HEAD || null, results: [] };
  let browser, server, backend;
  try {
    assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first"); server = await staticServer(); const baseURL = `http://127.0.0.1:${server.address().port}`;
    backend = await startBackend(baseURL);
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
    for (const width of [1440, 390]) for (const scenario of ["debate", ...(width === 390 ? ["notes-mobile"] : []), "history-late-success", "history-late-error", "calendar-422", "report-upload"]) {
      try { result.results.push(await runScenario(browser, baseURL, backend, width, scenario, evidenceDir)); console.log(`[FINAL-FAMILY] ${scenario} ${width}px PASS`); }
      catch (error) { result.results.push({ scenario, width, status: "FAIL", error: error.message }); console.error(`[FINAL-FAMILY] ${scenario} ${width}px FAIL: ${error.message}`); }
    }
    result.guard = await (await fetch(backend.url + "/api/e2e/final-audit", { signal: AbortSignal.timeout(10000) })).json(); assert.deepEqual(result.guard.violations, []);
    assert.equal(result.results.length, 11); assert.equal(result.results.filter(r => r.status !== "PASS").length, 0);
    console.log("[FINAL-FAMILY] 11/11 PASS");
  } catch (error) { result.error = error.message; throw error; }
  finally {
    try { writeFileSync(join(evidenceDir, "results.json"), JSON.stringify(result, null, 2)); }
    finally { try { await browser?.close(); } finally {
      try { await stopBackend(backend?.child); } finally { server?.closeAllConnections(); if (server) await new Promise(done => server.close(done)); }
    } }
  }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
