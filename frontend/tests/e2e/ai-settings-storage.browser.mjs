// AI-02 / SET-01: production UI + native storage events + local synthetic HTTP streams.
// No real credentials, backend, provider, runtime process or model is contacted.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { config, chatKey, readReply, validSyntheticStream, observeSyntheticStreams } from "./ai-settings-storage.fixture.mjs";
const frontend = fileURLToPath(new URL("../../", import.meta.url));
const dist = join(frontend, "dist");
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { resolve, promise }; };
async function bounded(promise) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Synthetic stream did not start")), 10000); })]); }
  finally { clearTimeout(timer); }
}
function prepareStream(state, path, prefix = "SYNTHETIC_PARTIAL ") {
  const slot = { path, prefix, started: deferred(), body: null, response: null,
    finish(text = "SYNTHETIC_COMPLETE", error = false) {
      if (!slot.response || slot.response.writableEnded) return;
      slot.response.end(JSON.stringify(error ? { type: "error", message: text } : { type: "delta", text }) + "\n" + (error ? "" : '{"type":"done","trace":[],"rounds":1}\n'));
    } };
  state.queue.push(slot); state.all.push(slot); return slot;
}
async function staticServer(streamState) {
  const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
  const server = createServer(async (request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname.startsWith("/api/")) {
      let raw = "";
      for await (const chunk of request) { raw += chunk; if (raw.length > 100000) { response.writeHead(413).end(); return; } }
      let body; try { body = JSON.parse(raw); } catch { body = null; }
      const slot = streamState.queue.shift();
      if (!slot || !validSyntheticStream(request.method, pathname, body) || slot.path !== pathname) {
        streamState.unexpected.push(`${request.method} ${pathname}`);
        response.writeHead(400).end(); return;
      }
      slot.body = body; slot.authorization = request.headers.authorization || "";
      slot.response = response;
      response.writeHead(200, { "Content-Type": "application/x-ndjson", "Cache-Control": "no-store" });
      response.write(JSON.stringify({ type: "delta", text: slot.prefix }) + "\n");
      slot.started.resolve();
      return;
    }
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


async function runScenario(browser, baseURL, width, scenario, streamState, evidenceDir) {
  let context, page, peer;
  const errors = [], unexpected = [], requests = [], external = [], storageEvidence = [], streamEvidence = [];
  const slotsBefore = streamState.all.length;
  try {
    context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
    await context.addInitScript(observeSyntheticStreams);
    await context.routeWebSocket("**/*", socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
      if (url.origin !== baseURL) { external.push(url.origin); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      requests.push(`${request.method()} ${url.pathname}${url.search}`);
      const reply = readReply(request.method(), url.pathname, url.search);
      if (reply) return route.fulfill({ json: reply });
      if (!url.search && validSyntheticStream(request.method(), url.pathname, request.postDataJSON())) return route.continue();
      unexpected.push(`${request.method()} ${url.pathname}${url.search}`);
      return route.fulfill({ status: 503, json: { detail: "UNEXPECTED_SYNTHETIC_REQUEST" } });
    });
    peer = await context.newPage(); await peer.goto("/__storage_probe");
    await peer.evaluate(cfg => { localStorage.clear(); localStorage.setItem("vr-llm", JSON.stringify(cfg)); }, config);
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", e => errors.push(e.message));
    page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    const events = async (key, value, clear = false) => {
      const count = await page.evaluate(() => window.__storageEvents.length);
      await peer.evaluate(({ key, value, clear }) => { if (clear) localStorage.clear(); else localStorage.setItem(key, value); }, { key, value, clear });
      await page.waitForFunction(({ key, count }) => window.__storageEvents.slice(count).some(e => e.key === key && e.local && e.trusted), { key, count });
      storageEvidence.push(await page.evaluate(({ key, count }) => window.__storageEvents.slice(count).find(e => e.key === key && e.local && e.trusted), { key, count }));
    };
    const streamCount = () => page.evaluate(() => window.__streams.length);
    const started = async (slot, index) => {
      await bounded(slot.started.promise);
      await page.waitForFunction(i => window.__streams[i]?.chunks > 0, index);
    };
    const finished = async (slot, index, text, error = false) => {
      slot.finish(text, error);
      await page.waitForFunction(i => window.__streams[i]?.eof, index);
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
      streamEvidence.push(await page.evaluate(i => ({ ...window.__streams[i] }), index));
    };
    const aborted = index => page.waitForFunction(i => window.__streams[i]?.aborted, index);
    const stored = () => page.evaluate(() => JSON.stringify(Object.fromEntries(Object.entries(localStorage))));
    if (scenario.startsWith("chat-")) {
      const openChat = async () => {
        await page.getByRole("checkbox", { name: "选择 Synthetic report", exact: true }).check();
        await page.getByRole("button", { name: "基于所选资料提问（1）", exact: true }).click();
        await page.getByPlaceholder("询问 Vibe...").waitFor();
      };
      const panel = page.locator('aside[aria-label="Vibe AI 对话"]');
      const send = async question => {
        const index = await streamCount(), slot = prepareStream(streamState, "/api/chat");
        await page.getByPlaceholder("询问 Vibe...").fill(question);
        await panel.getByRole("button", { name: "发送", exact: true }).click();
        await started(slot, index);
        await panel.getByText("SYNTHETIC_PARTIAL", { exact: false }).last().waitFor();
        return { slot, index };
      };
      await page.goto("/my-reports"); await openChat();
      const { slot, index } = await send("SYNTHETIC_FIRST_QUESTION");
      assert.deepEqual(slot.body.report_ids, ["synthetic-report"]);
      assert.equal(slot.body.messages.length, 1);
      if (scenario === "chat-unrelated") {
        for (let round = 0; round < 2; round++) {
          for (const key of ["vr-sidebar", "vr-notes", "unrelated", "vr-askai-chat:other", "vr-askai-epoch:other"]) {
            await events(key, key === "vr-notes" ? JSON.stringify([{ id: String(round), kind: "test", title: "Synthetic", content: "Synthetic", ts: round }]) : String(round));
            assert.equal(await page.evaluate(i => window.__streams[i].aborted, index), false);
            assert.equal(await panel.getByRole("button", { name: "停止生成", exact: true }).count(), 1);
          }
        }
        // Native sessionStorage events come from a same-tab frame, not another tab.
        const frameReady = page.waitForEvent("framenavigated", { predicate: frame => frame.name() === "synthetic-session" && frame.url().endsWith("/__storage_probe"), timeout: 10000 });
        await page.evaluate(() => { const frame = document.createElement("iframe"); frame.name = "synthetic-session"; frame.src = "/__storage_probe"; frame.hidden = true; document.body.append(frame); });
        const frame = await frameReady;
        await frame.evaluate(() => sessionStorage.setItem("vr-llm", "SYNTHETIC_SESSION_ONLY"));
        await page.waitForFunction(() => window.__storageEvents.some(e => e.key === "vr-llm" && !e.local && e.trusted));
        storageEvidence.push(await page.evaluate(() => window.__storageEvents.find(e => e.key === "vr-llm" && !e.local && e.trusted)));
        assert.equal(await page.evaluate(i => window.__streams[i].aborted, index), false);
        await finished(slot, index, "SYNTHETIC_COMPLETE_FIRST");
        await page.waitForFunction(key => localStorage.getItem(key)?.includes("SYNTHETIC_COMPLETE_FIRST"), chatKey);
        const retry = await send("SYNTHETIC_FOLLOWUP");
        assert.equal(retry.slot.body.messages.length, 3);
        assert.match(retry.slot.body.messages[1].content, /SYNTHETIC_COMPLETE_FIRST/);
        await finished(retry.slot, retry.index, "SYNTHETIC_COMPLETE_SECOND");
        await page.reload(); await openChat();
        await panel.getByText("SYNTHETIC_COMPLETE_SECOND", { exact: false }).waitFor();
      } else {
        if (scenario === "chat-runtime") await events("vr-llm", JSON.stringify({ ...config, apiKey: "SYNTHETIC_CHANGED" }));
        else if (scenario === "chat-access") await events("vr-access-key", "SYNTHETIC_PEER_ACCESS");
        else if (scenario === "chat-current") await events(chatKey, "[]");
        else if (scenario === "chat-epoch") await events(`vr-askai-epoch:${chatKey}`, "1");
        else if (scenario === "chat-clear") await events(null, null, true);
        else if (scenario === "chat-controls") await panel.getByRole("button", { name: "清空本页对话", exact: true }).click();
        await aborted(index);
        assert.equal(await panel.getByRole("button", { name: "停止生成", exact: true }).count(), 0);
        await finished(slot, index, "SYNTHETIC_LATE_CANCELLED");
        assert.doesNotMatch(await panel.innerText(), /SYNTHETIC_LATE_CANCELLED/);
        assert.doesNotMatch(await stored(), /SYNTHETIC_LATE_CANCELLED|SYNTHETIC_FIRST_QUESTION|SYNTHETIC_PARTIAL/);
        if (scenario === "chat-clear") await events("vr-llm", JSON.stringify(config));
        const retry = await send("SYNTHETIC_RETRY_QUESTION");
        assert.equal(retry.slot.body.messages.length, 1, "cancelled turn cannot become retry history");
        await finished(retry.slot, retry.index, "SYNTHETIC_RETRY_COMPLETE");
        await page.waitForFunction(key => localStorage.getItem(key)?.includes("SYNTHETIC_RETRY_COMPLETE"), chatKey);
        assert.doesNotMatch(await stored(), /SYNTHETIC_LATE_CANCELLED|SYNTHETIC_FIRST_QUESTION/);
        await page.reload(); await openChat();
        await panel.getByText("SYNTHETIC_RETRY_COMPLETE", { exact: false }).waitFor();
        assert.doesNotMatch(await panel.innerText(), /SYNTHETIC_LATE_CANCELLED|SYNTHETIC_FIRST_QUESTION/);
      }
    } else {
      await page.goto("/settings");
      const access = page.getByPlaceholder("与后端 VR_API_KEY 保持一致", { exact: true });
      const save = access.locator("..").getByRole("button", { name: "保存", exact: true });
      const start = page.getByTestId("model-connection-test-start");
      const result = page.getByTestId("model-connection-test-result");
      await access.waitFor();
      await page.getByTestId("backend-connection-status").filter({ hasText: "已连接" }).waitFor();
      const probe = async () => {
        const index = await streamCount(), slot = prepareStream(streamState, "/api/ai/connection-test");
        await start.click(); await started(slot, index);
        assert.equal(await result.getAttribute("data-probe-status"), "pending");
        return { slot, index };
      };
      if (scenario === "settings-save") {
        assert.equal(await start.isEnabled(), true);
        assert.equal(await streamCount(), 0);
        for (const rawValue of ["SYNTHETIC_FIRST_ACCESS", "  SYNTHETIC_SECOND_ACCESS  ", ""]) {
          const value = rawValue.trim();
          await access.fill(rawValue); assert.equal(await start.isDisabled(), true);
          await save.click(); await page.waitForFunction(() => !document.querySelector('[data-testid="model-connection-test-start"]').disabled);
          assert.equal(await page.evaluate(() => localStorage.getItem("vr-access-key") || ""), value);
          assert.equal(await access.inputValue(), value, "successful save canonicalizes padded input");
          const p = await probe(); assert.equal(p.slot.authorization, value ? `Bearer ${value}` : "");
          await finished(p.slot, p.index, "SYNTHETIC_PROBE_COMPLETE");
          await page.locator('[data-testid="model-connection-test-result"][data-probe-status="success"]').waitFor();
        }
        // Same-tab raw storage mutation emits no storage event. The click must
        // still check live persisted access before sending a stale draft.
        await page.evaluate(() => localStorage.setItem("vr-access-key", "SYNTHETIC_SILENT_CHANGE"));
        await start.click();
        assert.equal(await streamCount(), 3, "live access mismatch prevents a request even without a storage event");
        await page.evaluate(() => localStorage.removeItem("vr-access-key"));
        await access.fill("SYNTHETIC_RETRY_ACCESS");
        await page.evaluate(() => {
          const setItem = Storage.prototype.setItem;
          window.__restoreStorage = () => { Storage.prototype.setItem = setItem; };
          Storage.prototype.setItem = function(key, value) { if (key === "vr-access-key") throw new DOMException("Synthetic denied write", "SecurityError"); return setItem.call(this, key, value); };
        });
        await save.click(); await page.getByText("浏览器无法保存后端访问密钥，请检查存储权限或空间", { exact: true }).waitFor();
        assert.equal(await start.isDisabled(), true);
        assert.equal(await page.evaluate(() => localStorage.getItem("vr-access-key") || ""), "");
        assert.equal(await streamCount(), 3);
        await page.evaluate(() => window.__restoreStorage());
        await save.click(); await page.waitForFunction(() => !document.querySelector('[data-testid="model-connection-test-start"]').disabled);
        assert.equal(await page.evaluate(() => localStorage.getItem("vr-access-key")), "SYNTHETIC_RETRY_ACCESS");
        const recovered = await probe();
        assert.equal(recovered.slot.authorization, "Bearer SYNTHETIC_RETRY_ACCESS");
        await finished(recovered.slot, recovered.index, "SYNTHETIC_PROBE_RETRY_COMPLETE");
        await page.locator('[data-testid="model-connection-test-result"][data-probe-status="success"]').waitFor();
        await page.reload(); await access.waitFor();
        assert.equal(await access.inputValue(), "SYNTHETIC_RETRY_ACCESS");
        assert.equal(await start.isEnabled(), true);
      } else {
        const beforeLlm = await page.evaluate(() => localStorage.getItem("vr-llm"));
        for (const action of ["form", "peer", "cancel"]) {
          const p = await probe();
          if (action === "form") await page.getByTestId("wave5-api-key-input").fill("SYNTHETIC_DRAFT_CHANGED");
          else if (action === "peer") await events("vr-access-key", "SYNTHETIC_REMOTE_ACCESS");
          else await page.getByTestId("model-connection-test-cancel").click();
          await aborted(p.index);
          await finished(p.slot, p.index, "SYNTHETIC_LATE_PROBE_SUCCESS");
          if (action === "cancel") assert.equal(await result.getAttribute("data-probe-status"), "cancelled");
          else assert.equal(await result.count(), 0, "late success cannot reappear after invalidation");
          if (action === "peer") {
            assert.equal(await access.inputValue(), "", "peer state must not replace draft");
            assert.equal(await start.isDisabled(), true);
            await save.click(); await page.waitForFunction(() => !document.querySelector('[data-testid="model-connection-test-start"]').disabled);
          }
        }
        const failure = await probe(); await finished(failure.slot, failure.index, "SYNTHETIC_PROBE_ERROR", true);
        await page.locator('[data-testid="model-connection-test-result"][data-probe-status="error"]').waitFor();
        const retry = await probe(); await finished(retry.slot, retry.index, "SYNTHETIC_PROBE_RECOVERED");
        await page.locator('[data-testid="model-connection-test-result"][data-probe-status="success"]').waitFor();
        assert.equal(await page.evaluate(() => localStorage.getItem("vr-llm")), beforeLlm);
        assert.doesNotMatch(await stored(), /SYNTHETIC_LATE_PROBE_SUCCESS|SYNTHETIC_PROBE_RECOVERED/);
        await page.reload(); await access.waitFor();
        assert.equal(await result.count(), 0, "probe results remain ephemeral");
      }
    }
    assert.ok((await page.title()).trim());
    assert.equal(new URL(page.url()).pathname, scenario.startsWith("chat-") ? "/my-reports" : "/settings");
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(external, []);
    assert.deepEqual(errors, []);
    assert.deepEqual(streamState.unexpected, []);
    assert.equal(streamState.queue.length, 0);
    await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-pass.png`), fullPage: true });
    return { scenario, width, status: "PASS", streamCount: streamState.all.length - slotsBefore, requests, storageEvidence, streamEvidence,
      boundary: "Native trusted localStorage events; sessionStorage event uses same-tab iframe; synthetic HTTP stream transport deliberately ignores abort to test ownership" };
  } catch (error) {
    await page?.screenshot({ path: join(evidenceDir, `${scenario}-${width}-failure.png`), fullPage: true }).catch(() => {});
    throw new Error(`${scenario} ${width}px: ${error.message}; ${JSON.stringify({ errors, unexpected, requests, external })}`, { cause: error });
  } finally {
    streamState.all.slice(slotsBefore).forEach(slot => slot.finish("SYNTHETIC_CLEANUP"));
    streamState.queue.length = 0;
    await context?.close();
  }
}
async function main() {
  const evidenceDir = process.env.AI_SETTINGS_EVIDENCE_DIR || mkdtempSync(join(tmpdir(), "vr-ai-settings-evidence-"));
  mkdirSync(evidenceDir, { recursive: true });
  const git = arg => execFileSync("git", ["rev-parse", arg], { cwd: frontend, encoding: "utf8" }).trim();
  const result = { checkoutHead: git("HEAD"), checkoutTree: git("HEAD^{tree}"), frontendSourceTree: git("HEAD:frontend/src"), pullRequestHead: process.env.AI_SETTINGS_PR_HEAD || null, results: [] };
  const streamState = { queue: [], all: [], unexpected: [] };
  let browser, server;
  try {
    assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first");
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
    server = await staticServer(streamState);
    const baseURL = `http://127.0.0.1:${server.address().port}`;
    for (const width of [1440, 390]) for (const scenario of ["chat-unrelated", "chat-runtime", "chat-access", "chat-current", "chat-epoch", "chat-clear", "chat-controls", "settings-save", "settings-races"]) {
      try { result.results.push(await runScenario(browser, baseURL, width, scenario, streamState, evidenceDir)); console.log(`[AI-SET] ${scenario} ${width}px PASS`); }
      catch (error) { result.results.push({ scenario, width, status: "FAIL", error: error.message }); console.error(`[AI-SET] ${scenario} ${width}px FAIL: ${error.message}`); }
    }
    assert.equal(result.results.length, 18);
    assert.equal(result.results.filter(row => row.status !== "PASS").length, 0, "all scenario groups must pass");
    console.log("[AI-SET] 18/18 PASS");
  } catch (error) { result.error = error.message; throw error; }
  finally {
    try { writeFileSync(join(evidenceDir, "results.json"), JSON.stringify(result, null, 2)); }
    finally { try { await browser?.close(); } finally { server?.closeAllConnections(); if (server) await new Promise(done => server.close(done)); } }
  }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
