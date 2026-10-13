// Production Notes UI, synthetic isolated browser storage; no API, model, or account requests.
// Build first, then: node --import ./tests/e2e/runtime-env.mjs tests/e2e/manual-notes.browser.mjs
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
const frontend = fileURLToPath(new URL("../../", import.meta.url));
const dist = join(frontend, "dist");
const seed = { id: "synthetic-existing", kind: "暂定研究", title: "既有合成记录", content: "Synthetic retained note", ts: 1 };

async function run(browser, baseURL, width, scenario, output) {
  const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
  const errors = [], requests = [];
  let phase = "initial load";
  await context.addInitScript(({ scenario, seed }) => {
    const setItem = Storage.prototype.setItem;
    if (!localStorage.getItem("synthetic-manual-seeded")) {
      setItem.call(localStorage, "vr-notes", scenario === "corrupt" ? "corrupt-original" : JSON.stringify(scenario === "quota" ? [seed] : []));
      setItem.call(localStorage, "synthetic-manual-seeded", "yes");
    }
    window.__denyManualNoteWrite = scenario === "quota";
    Storage.prototype.setItem = function (key, value) {
      if (key === "vr-notes" && window.__denyManualNoteWrite) throw new DOMException("Synthetic quota", "QuotaExceededError");
      return setItem.call(this, key, value);
    };
  }, { scenario, seed });
  await context.routeWebSocket("**/*", socket => { requests.push(`WebSocket ${socket.url()}`); socket.close(); });
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
    if (url.origin !== baseURL || url.pathname.startsWith("/api/")) {
      requests.push(`${route.request().method()} ${url.href}`);
      return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  const form = page.getByRole("form", { name: "新建研究记录", exact: true });
  const create = page.getByRole("button", { name: "新建研究记录", exact: true });
  const noteState = () => page.evaluate(() => JSON.parse(localStorage.getItem("vr-notes") || "[]"));
  const edit = async (title, content = "Synthetic user observation; needs verification") => {
    await create.click();
    await form.waitFor();
    await form.getByLabel("记录标题", { exact: true }).fill(title);
    await form.getByLabel("记录正文", { exact: true }).fill(content);
  };
  const saved = async (count, title) => {
    await page.waitForFunction(({ count, title }) => {
      const notes = JSON.parse(localStorage.getItem("vr-notes") || "[]");
      const params = new URL(location.href).searchParams;
      return notes.length === count && notes[0]?.title === title && params.get("note") === notes[0].id &&
        !document.querySelector('form[aria-label="新建研究记录"]') &&
        document.body.innerText.includes("研究记录已保存在当前浏览器，尚未核验。");
    }, { count, title });
    assert.equal((await noteState()).length, count);
    await page.getByText(title, { exact: true }).waitFor();
  };
  try {
    await page.goto(`/notes${scenario === "normal" ? "?security_code=000001" : ""}`);
    await page.getByRole("heading", { name: "研究记录", exact: true }).waitFor();
    await create.waitFor();
    if (scenario === "corrupt") {
      phase = "corrupt storage blocks creation, native storage event restores it";
      assert.equal(await create.isDisabled(), true);
      assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), "corrupt-original");
      const other = await context.newPage();
      await other.goto("/__storage-probe");
      await other.evaluate(() => localStorage.setItem("vr-notes", "[]"));
      await page.waitForFunction(() => [...document.querySelectorAll("button")].find(button => button.textContent.trim() === "新建研究记录")?.disabled === false);
      await edit("存储恢复后的记录");
      await form.getByRole("button", { name: "保存研究记录", exact: true }).click();
      await saved(1, "存储恢复后的记录");
      await other.close();
    } else if (scenario === "quota") {
      phase = "failed checked write retains input and existing notes";
      await edit("配额恢复后保存");
      await form.getByRole("button", { name: "保存研究记录", exact: true }).click();
      await form.getByRole("alert").filter({ hasText: "浏览器无法保存数据" }).waitFor();
      assert.equal(await form.getByLabel("记录标题", { exact: true }).inputValue(), "配额恢复后保存");
      assert.deepEqual(await noteState(), [seed]);
      await page.screenshot({ path: join(output, `${scenario}-${width}-error.png`), fullPage: false });
      await page.evaluate(() => { window.__denyManualNoteWrite = false; });
      await form.getByRole("button", { name: "保存研究记录", exact: true }).click();
      await saved(2, "配额恢复后保存");
      assert.deepEqual((await noteState())[1], seed);
    } else {
      phase = "invalid source and repeated save";
      await edit("手写合成研究记录");
      assert.equal(await form.getByLabel("关联股票代码（可选）", { exact: true }).inputValue(), "000001");
      await form.locator("summary").click();
      await form.getByLabel("来源标题", { exact: true }).fill("Synthetic source, unverified");
      await form.getByLabel("来源链接", { exact: true }).fill("javascript:alert(1)");
      await form.getByRole("button", { name: "保存研究记录", exact: true }).click();
      await form.getByRole("alert").filter({ hasText: "来源链接须为" }).waitFor();
      assert.equal((await noteState()).length, 0);
      await form.getByLabel("来源链接", { exact: true }).fill("https://example.test/source");
      await form.getByRole("button", { name: "保存研究记录", exact: true }).dblclick();
      await saved(1, "手写合成研究记录");
      const savedNote = (await noteState())[0];
      assert.equal(savedNote.kind, "暂定研究");
      assert.equal(savedNote.research.securityCode, "000001");
      assert.equal(savedNote.research.sourceLinks[0].url, "https://example.test/source");
      assert.match(savedNote.content, /^用户手动记录，尚未核验。/);
      await page.getByTestId("note-research-context").getByText("000001 · 用户暂定记录，尚未核验", { exact: true }).waitFor();
      phase = "reload proves persistence and focused-note continuity";
      await page.reload();
      await page.getByText("手写合成研究记录", { exact: true }).waitFor();
      await page.getByTestId("note-research-context").waitFor();
      assert.deepEqual(await noteState(), [savedNote]);
      phase = "fresh editor guards navigation after a previous successful save";
      await edit("不能丢失的草稿");
      await page.getByRole("button", { name: "显示全部记录", exact: true }).click();
      const navigationDialog = page.getByRole("dialog", { name: "内容尚未保存", exact: true });
      await navigationDialog.waitFor();
      await navigationDialog.getByRole("button", { name: "留在此页", exact: true }).click();
      await navigationDialog.waitFor({ state: "hidden" });
      assert.equal(await form.getByLabel("记录标题", { exact: true }).inputValue(), "不能丢失的草稿");
      assert.equal(new URL(page.url()).searchParams.get("security_code"), "000001");
      phase = "cancel and Escape preserve the draft until explicit discard";
      const cancel = form.getByRole("button", { name: "取消", exact: true });
      await cancel.click();
      const discard = page.getByRole("dialog", { name: "放弃未保存的研究记录？", exact: true });
      await discard.waitFor();
      await page.keyboard.press("Escape");
      await discard.waitFor({ state: "hidden" });
      assert.equal(await form.getByLabel("记录标题", { exact: true }).inputValue(), "不能丢失的草稿");
      await cancel.click();
      await discard.getByRole("button", { name: "放弃本次输入", exact: true }).click();
      await form.waitFor({ state: "hidden" });
      assert.deepEqual(await noteState(), [savedNote]);
      phase = "explicit navigation discard updates URL without saving";
      await edit("明确放弃的草稿");
      await page.getByRole("button", { name: "显示全部记录", exact: true }).click();
      await navigationDialog.getByRole("button", { name: "放弃未保存内容并离开", exact: true }).click();
      await page.waitForFunction(() => !new URL(location.href).searchParams.has("security_code") && !document.querySelector('form[aria-label="新建研究记录"]'));
      assert.deepEqual(await noteState(), [savedNote]);
    }
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await page.screenshot({ path: join(output, `${scenario}-${width}-complete.png`), fullPage: false });
    assert.deepEqual(requests, [], "manual notes never send API/model/source requests");
    assert.deepEqual(errors, []);
    return { scenario, width, status: "PASS", requests: 0 };
  } catch (error) {
    await page.screenshot({ path: join(output, `${scenario}-${width}-failure.png`), fullPage: false }).catch(() => {});
    const dom = await page.evaluate(() => document.body.innerText).catch(() => null);
    writeFileSync(join(output, `${scenario}-${width}-failure.json`), JSON.stringify({ phase, error: error.stack || error.message, url: page.url(), dom, requests, errors }, null, 2));
    throw error;
  } finally { await context.close(); }
}
async function main() {
  assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first");
  const output = process.env.MANUAL_NOTES_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), "vr-manual-notes-"));
  mkdirSync(output, { recursive: true });
  const server = createServer((request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname === "/__storage-probe") { response.setHeader("Content-Type", "text/html"); response.end("<!doctype html><title>Synthetic storage probe</title>"); return; }
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
    for (const width of [1440, 390]) for (const scenario of ["normal", "quota", "corrupt"]) {
      try { result.results.push(await run(browser, baseURL, width, scenario, output)); }
      catch (error) { result.results.push({ width, scenario, status: "FAIL", error: error.message }); console.error(error); }
    }
    assert.equal(result.results.filter(row => row.status !== "PASS").length, 0, "all manual-notes scenarios must pass");
    console.log(JSON.stringify(result, null, 2));
  } catch (error) { result.error = error.message; throw error; }
  finally {
    writeFileSync(join(output, "results.json"), JSON.stringify(result, null, 2));
    await browser?.close(); server.closeAllConnections(); await new Promise(done => server.close(done));
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
