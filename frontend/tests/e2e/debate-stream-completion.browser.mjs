import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

// Synthetic UI-only regression: serve the built dist on a random local port;
// no backend, provider, credentials, persistent browser profile, or paid call.
const dist = path.resolve(fileURLToPath(new URL("../../dist/", import.meta.url)));
const out = path.resolve(process.env.DEBATE_QA_OUT || path.join(process.env.TEMP, "debate-completion-qa"));
await mkdir(out, { recursive: true });
const report = { kind: "synthetic dist UI regression", browser: "Browser plugin not available; installed Playwright", checks: [], requests: [], errors: [], console: [], blockedExternal: [] };
const plan = rounds => rounds >= 2 ? ["bull", "bear", "bull_rebut", "bear_rebut", "referee"] : ["bull", "bear", "referee"];
const transcript = (rounds, prefix = "SYNTHETIC") => plan(rounds).map(stage => ({ stage, content: `${prefix}_${stage}` }));
const fixture = (body, prefix) => [
  ...transcript(body.rounds, prefix).flatMap(({ stage, content }) => [
    { type: "stage", stage, label: stage }, { type: "delta", stage, text: content },
    { type: "stage_done", stage, label: stage, content },
  ]),
  { type: "done", code: body.code, stages: transcript(body.rounds, prefix) },
];
const encode = events => events.map(ev => JSON.stringify(ev)).join("\n") + "\n";
let mode = "normal", releaseOld;
const server = createServer(async (req, res) => {
  try {
    const pathname = new URL(req.url, "http://127.0.0.1").pathname;
    if (pathname === "/api/debate") {
      let raw = ""; for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw), requestMode = mode;
      report.requests.push({ path: pathname, code: body.code, rounds: body.rounds, mode: requestMode });
      const normal = fixture(body);
      res.writeHead(200, { "content-type": "application/x-ndjson" });
      if (requestMode === "cancel") {
        const old = fixture(body, "STALE");
        res.write(encode(old.slice(0, 2)));
        await new Promise(resolve => { releaseOld = resolve; });
        res.end(encode(old.slice(2))); return;
      }
      if (requestMode === "disconnect") {
        res.write(encode(normal.slice(0, 3)));
        setTimeout(() => res.destroy(), 100); return;
      }
      let events = normal;
      if (requestMode === "bull-eof") events = normal.slice(0, 3);
      else if (requestMode === "all-eof") events = normal.slice(0, -1);
      else if (requestMode === "missing-stages-done") events = [...normal.slice(0, 3), { ...normal.at(-1), stages: normal.at(-1).stages.slice(0, 1) }];
      else if (requestMode === "forged-full-done") events = [...normal.slice(0, 3), normal.at(-1)];
      else if (requestMode === "error") events = [{ type: "error", stage: "bull", message: "SYNTHETIC_PROVIDER_FAILURE" }, ...normal];
      else if (requestMode === "failed-role") events = normal.map(ev => ev.type === "stage_done" && ev.stage === "bull" ? { ...ev, failed: true } : ev);
      res.end(encode(events)); return;
    }
    if (pathname.startsWith("/api/")) {
      res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(pathname === "/api/health" ? { status: "ok" } : { data: [] })); return;
    }
    let target = path.resolve(dist, "." + decodeURIComponent(pathname));
    if (!target.startsWith(dist + path.sep) && target !== dist) { res.writeHead(403).end(); return; }
    try { if (!(await stat(target)).isFile()) target = path.join(dist, "index.html"); } catch { target = path.join(dist, "index.html"); }
    res.setHeader("content-type", { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" }[path.extname(target)] || "application/octet-stream");
    res.end(await readFile(target));
  } catch { if (!res.headersSent) res.writeHead(500); res.end("synthetic fixture failure"); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
report.origin = origin;
let browser, context, page;
const start = async (code = "600519", rounds = "1") => {
  await page.getByPlaceholder("6 位代码，如 600519").fill(code);
  await page.locator("select").selectOption(rounds);
  await page.getByRole("button", { name: "开始辩论", exact: true }).click();
};
const notes = () => page.evaluate(() => JSON.parse(localStorage.getItem("vr-notes") || "[]"));
const check = async (name, fn) => {
  try {
    await fn();
    const index = report.checks.length;
    const screenshot = path.join(out, `${index}.png`), dom = path.join(out, `${index}.txt`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await writeFile(dom, await page.locator("body").innerText());
    report.checks.push({ name, status: "PASS", screenshot, dom });
  } catch (error) {
    report.checks.push({ name, status: "FAIL", message: String(error) }); process.exitCode = 1;
  }
};
try {
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: "block" });
  await context.route("**/*", async route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    report.blockedExternal.push(route.request().url());
    if (route.request().url().startsWith("https://fonts.googleapis.com/")) return route.fulfill({ status: 200, contentType: "text/css", body: "/* offline font fixture */" });
    await route.abort();
  });
  await context.addInitScript(() => localStorage.setItem("vr-llm", JSON.stringify({ provider: "cli-codex", model: "synthetic-offline" })));
  page = await context.newPage();
  page.on("pageerror", error => report.errors.push(String(error)));
  page.on("console", message => { if (["warning", "error"].includes(message.type())) report.console.push({ type: message.type(), text: message.text() }); });
  await page.goto(origin + "/debate");
  await check("built Debate page identity, meaningful content, and no framework overlay", async () => {
    assert.equal(page.url(), origin + "/debate"); assert.ok(await page.title());
    await page.getByRole("heading", { name: "多空辩论", exact: true }).waitFor();
    assert.ok((await page.locator("body").innerText()).length > 100);
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
  });
  for (const rounds of ["1", "2"]) await check(`normal ${rounds}-round completion saves all stages with original ticker`, async () => {
    mode = "normal"; await start("600519", rounds);
    await page.getByText("辩论完成", { exact: true }).waitFor();
    for (const stage of plan(Number(rounds))) await page.getByText(`SYNTHETIC_${stage}`, { exact: true }).waitFor();
    await page.getByPlaceholder("6 位代码，如 600519").fill("000001");
    await page.getByRole("button", { name: "存入沉淀", exact: true }).click();
    await page.getByRole("button", { name: "已存入沉淀", exact: true }).waitFor();
    const saved = (await notes())[0]; assert.match(saved.title, /600519/); assert.doesNotMatch(saved.title, /000001/);
    for (const stage of plan(Number(rounds))) assert.ok(saved.content.includes(`SYNTHETIC_${stage}`));
  });
  for (const scenario of ["bull-eof", "bull-eof", "all-eof", "missing-stages-done", "forged-full-done", "error", "failed-role", "disconnect"]) await check(`${scenario}: partial content stays visible; completion and saving blocked`, async () => {
    mode = scenario; const before = await notes(); await start();
    await page.getByText("辩论失败", { exact: true }).waitFor();
    await page.getByText("SYNTHETIC_bull", { exact: true }).waitFor();
    assert.equal(await page.getByText("辩论完成", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "存入沉淀", exact: true }).count(), 0);
    assert.deepEqual(await notes(), before);
    if (scenario === "error") await page.getByText(/SYNTHETIC_PROVIDER_FAILURE/).waitFor();
  });
  await check("stop mid-stage, restart, and late old response cannot replace the complete new result", async () => {
    mode = "cancel"; await start(); await page.getByText("STALE_bull", { exact: true }).waitFor();
    await page.getByRole("button", { name: "中止", exact: true }).click();
    await page.getByText("已中止", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "存入沉淀", exact: true }).count(), 0);
    mode = "normal"; await start("000001", "2"); await page.getByText("辩论完成", { exact: true }).waitFor();
    releaseOld(); releaseOld = undefined;
    await page.waitForTimeout(250);
    assert.doesNotMatch(await page.locator("body").innerText(), /STALE/);
    for (const stage of plan(2)) assert.equal(await page.getByText(`SYNTHETIC_${stage}`, { exact: true }).count(), 1);
    await page.getByRole("button", { name: "存入沉淀", exact: true }).click();
    assert.match((await notes())[0].title, /000001/);
  });
  await check("console and page runtime health", async () => {
    assert.deepEqual(report.errors, []);
    assert.deepEqual(report.blockedExternal.filter(url => !url.startsWith("https://fonts.googleapis.com/")), []);
    const relevant = report.console.filter(item => !item.text.includes("net::ERR_INCOMPLETE_CHUNKED_ENCODING") && !item.text.includes("net::ERR_CONNECTION_RESET"));
    assert.deepEqual(relevant, []);
  });
} catch (error) { report.fatal = String(error); process.exitCode = 1; }
finally {
  releaseOld?.();
  report.finishedAt = new Date().toISOString(); await writeFile(path.join(out, "browser-results.json"), JSON.stringify(report, null, 2));
  await context?.close(); await browser?.close(); await new Promise(resolve => server.close(resolve));
  console.log(JSON.stringify({ checks: report.checks.map(({ name, status, message }) => ({ name, status, message })), errors: report.errors, console: report.console, fatal: report.fatal, output: out }, null, 2));
}
