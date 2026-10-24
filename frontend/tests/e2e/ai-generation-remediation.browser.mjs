/** Actual request helper in two isolated browser tabs; no model/server credentials. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import { build } from "esbuild";

export async function exerciseAiGeneration(browser) {
  const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const bundle = await build({ stdin: { contents: 'import { request } from "./src/lib/api.ts"; window.submit = request;',
    resolveDir: frontend, loader: "ts" }, bundle: true, write: false, format: "iife" });
  const cfg = { provider: "deepseek", model: "synthetic", baseURL: "https://model.invalid", apiKey: "SYNTHETIC", revision: "1" };
  const state = { revision: "1", configured: true, submissions: [], raceClear: false };
  const server = createServer(async (req, res) => {
    if (req.url === "/client.js") { res.setHeader("content-type", "text/javascript"); res.end(bundle.outputFiles[0].text); return; }
    if (req.url === "/api/ai/credential-status" && req.method === "GET") {
      const receipt = { revision: state.revision, configured: state.configured };
      if (state.raceClear) { state.revision = "4"; state.configured = false; }
      res.setHeader("content-type", "application/json"); res.end(JSON.stringify(receipt)); return;
    }
    if (req.url === "/api/synthetic-model" && req.method === "POST") {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks));
      state.submissions.push(body);
      if (!state.configured || body.ai_config?.revision !== state.revision) {
        res.writeHead(409, { "content-type": "application/json" }); res.end('{"detail":"CREDENTIAL_REVISION_CONFLICT"}'); return;
      }
      res.setHeader("content-type", "application/json"); res.end('{"data":{"accepted":true}}'); return;
    }
    if (req.url === "/") { res.setHeader("content-type", "text/html"); res.end('<title>AI generation fixture</title><script src="/client.js"></script>'); return; }
    res.writeHead(404); res.end();
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const context = await browser.newContext();
  await context.route("**/*", route => route.request().url().startsWith(origin + "/") ? route.continue() : route.abort());
  try {
    const first = await context.newPage(), second = await context.newPage();
    await first.goto(origin); await second.goto(origin);
    await first.evaluate(config => { localStorage.setItem("vr-llm", JSON.stringify(config)); window.captured = config; }, cfg);
    await second.evaluate(() => localStorage.removeItem("vr-llm"));
    state.revision = "2"; state.configured = false;
    const stale = await first.evaluate(async () => {
      try { await window.submit("/synthetic-model", "POST", { ai_config: window.captured }); return "unexpected"; }
      catch (error) { return error.message; }
    });
    assert.match(stale, /AI 配置已变化/); assert.equal(state.submissions.length, 0);
    state.revision = "3"; state.configured = true;
    await second.evaluate(config => localStorage.setItem("vr-llm", JSON.stringify(config)), { ...cfg, revision: "3" });
    assert.equal(await first.evaluate(async () => (await window.submit("/synthetic-model", "POST", { ai_config: JSON.parse(localStorage.getItem("vr-llm")) })).accepted), true);
    assert.equal(state.submissions[0].ai_config.revision, "3");
    state.raceClear = true;
    const raced = await first.evaluate(async () => {
      try { await window.submit("/synthetic-model", "POST", { ai_config: JSON.parse(localStorage.getItem("vr-llm")) }); return "unexpected"; }
      catch (error) { return error.message; }
    });
    assert.match(raced, /CREDENTIAL_REVISION_CONFLICT/);
    assert.equal(state.submissions.length, 2);
    return { scenarios: 3, modelCalls: 0, staleBlockedBeforePost: true, revisionPreserved: true, serverRaceRejected: true };
  } finally {
    await context.close();
    await new Promise(resolve => server.close(resolve));
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { chromium } = await import("playwright");
  const browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
  try { console.log(JSON.stringify(await exerciseAiGeneration(browser))); }
  finally { await browser.close(); }
}
