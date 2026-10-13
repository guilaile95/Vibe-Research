// Full production app, synthetic HTTP/storage only. No backend or provider runs.
// Recovery uses the production migration alert, retry, and existing batch editor.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const frontend = fileURLToPath(new URL("../../", import.meta.url));
const dist = join(frontend, "dist");
const originalCodes = ["600000"];
const oversizedDraft = Array.from({ length: 51 }, (_, i) => String(600000 + i));
const reducedDraft = oversizedDraft.slice(0, 3);

async function staticServer() {
  const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
  const server = createServer((request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    // An API request that escapes interception must never contact a real service.
    if (pathname.startsWith("/api/")) { response.writeHead(503).end("UNMOCKED_API"); return; }
    if (pathname === "/__storage_probe") {
      response.setHeader("Content-Type", "text/html");
      response.end("<!doctype html><title>Synthetic draft fixture</title>"); return;
    }
    let target = resolve(dist, `.${decodeURIComponent(pathname)}`);
    if (!target.startsWith(dist + sep) || !existsSync(target) || !extname(target)) target = join(dist, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  await new Promise((done, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", done); });
  return server;
}

async function runScenario(browser, baseURL, width, evidenceDir) {
  const evidence = { width, status: "RUNNING", imports: [], saves: [], requests: [], unexpected: [], external: [], errors: [], checkpoints: [] };
  let context, page;
  let codes = [...originalCodes], etag = "1111111111111111";
  try {
    context = await browser.newContext({ baseURL, viewport: { width, height: 900 }, serviceWorkers: "block" });
    await context.routeWebSocket("**/*", socket => { evidence.external.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
      if (url.origin !== baseURL) { evidence.external.push(url.origin); return route.abort(); }
      const path = url.pathname, method = request.method();
      if (!path.startsWith("/api/")) return route.continue();
      evidence.requests.push(`${method} ${path}${url.search}`);
      if (path === "/api/watchlist" && method === "GET" && !url.search) {
        return route.fulfill({ json: { data: { status: "valid", data: { codes, updated_at: "synthetic" }, etag } } });
      }
      if (path === "/api/watchlist" && method === "PUT" && !url.search) {
        const body = request.postDataJSON();
        evidence.saves.push(body);
        if (body.expected_etag !== etag) return route.fulfill({ status: 409, json: { detail: "synthetic conflict" } });
        const next = [...new Set(body.codes)];
        if (next.length > 50) return route.fulfill({ status: 400, json: { detail: "关注股超过上限 50" } });
        codes = next; etag = "2222222222222222";
        return route.fulfill({ json: { data: { codes, etag, updated_at: "synthetic" } } });
      }
      if (path === "/api/watchlist/import-local" && method === "POST" && !url.search) {
        const body = request.postDataJSON();
        const incoming = [...new Set(body.codes)];
        const merged = [...new Set([...codes, ...incoming])];
        const status = body.expected_etag !== etag ? 409 : merged.length > 50 ? 400 : 200;
        const row = { body, status, authorityBefore: [...codes] };
        evidence.imports.push(row);
        if (status !== 200) {
          row.authorityAfter = [...codes];
          return route.fulfill({ status, json: { detail: status === 400 ? `关注股超过上限 50（去重后 ${merged.length} 只），请删减后再保存` : "synthetic conflict" } });
        }
        const added = incoming.filter(code => !codes.includes(code));
        codes = merged; etag = "3333333333333333"; row.authorityAfter = [...codes];
        return route.fulfill({ json: { data: { codes, added, etag, updated_at: "synthetic" } } });
      }
      if (path === "/api/local-ocr/preview" && method === "POST") {
        const body = request.postDataJSON();
        assert.equal(body.confirm_local_processing, true);
        assert.equal(body.extension, ".png");
        const hash = createHash("sha256").update(Buffer.from(body.content_b64, "base64")).digest("hex");
        return route.fulfill({ json: { data: { schema_version: "local_ocr_preview.v1", status: "OCR_UNVERIFIED", source_truth_verified: false, source_sha256: hash, engine: "local-tesseract", language: "eng", limitations: ["Synthetic transport fixture; OCR engine not run"], pages: [{ page_number: 1, text: "300750", source_sha256: hash, image_sha256: hash, text_sha256: createHash("sha256").update("300750").digest("hex") }] } } });
      }
      if (path === "/api/watchlist/anomalies" && method === "GET" && !url.search) {
        return route.fulfill({ json: { data: { provider_id: "hithink_financial_api", provider_contract: "hithink-watchlist-anomalies-v0.1", as_of_ms: null, unavailable_codes: [], items: [] } } });
      }
      if (path === "/api/quote" && method === "GET") {
        return route.fulfill({ json: { data: Object.fromEntries(codes.map(code => [code, { name: `Synthetic ${code}`, price: 10, change_pct: 0, amount_wan: 100 }])) } });
      }
      if (path === "/api/native-intel/watchlist-context" && method === "GET") {
        return route.fulfill({ json: { data: { status: "normal", retrieved_at: "synthetic", authority_ref: "synthetic", usage_boundary: "observation_only_not_an_investment_authority", watchlist_status: "valid", codes, degraded: [], securities: codes.map(code => ({ code, company_name: `Synthetic ${code}`, mention_count: 0, source_count: 0, items: [] })) } } });
      }
      evidence.unexpected.push(`${method} ${path}${url.search}`);
      return route.fulfill({ status: 503, json: { detail: "UNEXPECTED_SYNTHETIC_REQUEST" } });
    });
    page = await context.newPage(); page.setDefaultTimeout(10000);
    page.on("pageerror", error => evidence.errors.push(error.message));
    page.on("console", message => {
      if (message.type() === "error" && !/Failed to load resource.*400/.test(message.text())) evidence.errors.push(message.text());
    });
    await page.goto("/__storage_probe");
    const originalDraftBytes = JSON.stringify(oversizedDraft);
    await page.evaluate(value => localStorage.setItem("vr-watchlist", value), originalDraftBytes);
    await page.goto("/watchlist");
    await page.locator('[data-watchlist-code="600000"]').waitFor();
    assert.equal(await page.locator("[data-watchlist-code]").count(), 1);
    assert.equal(await page.evaluate(() => localStorage.getItem("vr-watchlist")), originalDraftBytes);
    assert.deepEqual(codes, originalCodes);
    assert.equal(evidence.imports.length, 1);
    assert.equal(evidence.imports[0].status, 400);
    assert.deepEqual(evidence.imports[0].body, { codes: oversizedDraft, expected_etag: "1111111111111111" });
    assert.deepEqual(evidence.imports[0].authorityAfter, originalCodes);
    assert.equal(await page.getByText(/已从本地草稿迁移至后端权威自选/).count(), 0);
    const alert = page.getByRole("alert").filter({ hasText: "本地草稿未导入" });
    await alert.waitFor();
    assert.match(await alert.innerText(), /超过上限 50/);
    assert.match(await alert.innerText(), /原草稿已保留/);
    evidence.checkpoints.push({ stage: "rejected", draftCount: 51, retainedBytesExactly: true, authority: [...codes], explicitMigrationErrorUI: true });
    await page.screenshot({ path: join(evidenceDir, `watchlist-import-${width}-rejected.png`), fullPage: true });

    await alert.getByRole("button", { name: "重试导入", exact: true }).click();
    await page.getByRole("button", { name: "编辑本地草稿", exact: true }).waitFor({ state: "visible" });
    await page.waitForFunction(() => ![...document.querySelectorAll("button")].find(button => button.textContent === "编辑本地草稿")?.disabled);
    assert.equal(evidence.imports.length, 2);
    assert.equal(evidence.imports[1].status, 400);
    assert.deepEqual(evidence.imports[1].body, evidence.imports[0].body);
    assert.equal(await page.evaluate(() => localStorage.getItem("vr-watchlist")), originalDraftBytes);
    await alert.getByRole("button", { name: "编辑本地草稿", exact: true }).click();
    const editor = page.getByRole("textbox").first();
    assert.equal(await editor.inputValue(), oversizedDraft.join(" "));
    await editor.fill(reducedDraft.join(" "));
    await page.getByRole("button", { name: "添加", exact: true }).click();
    await page.getByText("已添加 2 只（后端权威）", { exact: true }).waitFor();
    await page.locator('[data-watchlist-code="600002"]').waitFor();
    assert.equal(await page.locator("[data-watchlist-code]").count(), 3);
    assert.equal(await page.evaluate(() => localStorage.getItem("vr-watchlist")), null);
    assert.deepEqual(codes, reducedDraft);
    assert.equal(evidence.imports.length, 2);
    assert.deepEqual(evidence.saves, [{ codes: reducedDraft, expected_etag: "1111111111111111" }]);
    assert.equal(await alert.count(), 0);
    evidence.checkpoints.push({ stage: "edited-draft-save", userVisibleEditor: true, draftRemovedAfterSuccess: true, authority: [...codes] });
    await page.screenshot({ path: join(evidenceDir, `watchlist-import-${width}-recovered.png`), fullPage: true });
    await page.reload();
    await page.locator('[data-watchlist-code="600002"]').waitFor();
    assert.equal(evidence.imports.length, 2, "successful migration must not repeat after reload");
    assert.equal(await page.locator("[data-watchlist-code]").count(), 3);
    // Real table component: invalid rows block any write, preview is read-only,
    // duplicates remain visible, then explicit confirmation uses existing ETag.
    await page.getByText("从表格导入（本机预览）", { exact: true }).click();
    const tableEditor = page.getByRole("textbox", { name: "自选导入表格文本", exact: true });
    const beforeTableSaves = evidence.saves.length;
    await tableEditor.fill("code,market,name\n600519,SH,Fixture\n000858,SH,Wrong exchange");
    await page.getByRole("button", { name: "预览导入", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: /确认添加/ }).isDisabled(), true);
    assert.equal(evidence.saves.length, beforeTableSaves);
    await tableEditor.fill("code,market,name\n600519,SH,Fixture\n600519,SH,Duplicate\n000858,SZ,Fixture");
    await page.getByRole("button", { name: "预览导入", exact: true }).click();
    assert.match(await page.getByRole("list", { name: "导入逐行预览" }).innerText(), /本表重复/);
    assert.equal(evidence.saves.length, beforeTableSaves);
    await page.getByRole("button", { name: "确认添加 2 只", exact: true }).click();
    await page.getByText("已添加 2 只自选", { exact: true }).waitFor();
    assert.deepEqual(codes, [...reducedDraft, "600519", "000858"]);
    assert.equal(evidence.saves.length, beforeTableSaves + 1);
    assert.equal(await tableEditor.inputValue(), "");
    evidence.checkpoints.push({ stage: "table-preview-apply", invalidRowsBlocked: true, previewReadOnly: true, duplicatesVisible: true, authority: [...codes] });
    await page.screenshot({ path: join(evidenceDir, `watchlist-table-${width}.png`), fullPage: true });
    const beforeOcrWrites = evidence.saves.length;
    const beforeOcrRequests = evidence.requests.filter(value => value.includes("local-ocr")).length;
    await page.getByLabel("选择待识别自选截图", { exact: true }).setInputFiles({ name: "synthetic.png", mimeType: "image/png", buffer: Buffer.from("synthetic transport bytes") });
    assert.equal(evidence.requests.filter(value => value.includes("local-ocr")).length, beforeOcrRequests);
    await page.getByRole("button", { name: "本地 OCR 识别", exact: true }).click();
    await page.getByRole("textbox", { name: "核对并编辑截图识别文字", exact: true }).waitFor();
    assert.equal(evidence.saves.length, beforeOcrWrites);
    await page.getByRole("textbox", { name: "核对并编辑截图识别文字", exact: true }).fill("300750");
    await page.getByRole("button", { name: "使用核对后的文字替换上方导入编辑框", exact: true }).click();
    assert.equal(await tableEditor.inputValue(), "300750");
    assert.equal(evidence.saves.length, beforeOcrWrites);
    await page.getByRole("button", { name: "预览导入", exact: true }).click();
    await page.getByRole("button", { name: "确认添加 1 只", exact: true }).click();
    await page.getByText("已添加 1 只自选", { exact: true }).waitFor();
    assert.equal(evidence.saves.length, beforeOcrWrites + 1);
    evidence.checkpoints.push({ stage: "explicit-ocr-edit-preview-apply", noRequestOnSelection: true, noWriteBeforeReview: true, authority: [...codes] });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "no page horizontal overflow");
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
    assert.deepEqual(evidence.unexpected, []);
    assert.deepEqual(evidence.external, []);
    assert.deepEqual(evidence.errors, []);
    evidence.status = "PASS";
  } catch (error) {
    evidence.status = "FAIL"; evidence.error = error.stack || error.message;
    await page?.screenshot({ path: join(evidenceDir, `watchlist-import-${width}-failure.png`), fullPage: true }).catch(() => {});
  } finally {
    writeFileSync(join(evidenceDir, `watchlist-import-${width}.json`), JSON.stringify(evidence, null, 2));
    await context?.close();
  }
  return evidence;
}

async function main() {
  const evidenceDir = process.env.WATCHLIST_IMPORT_EVIDENCE_DIR || mkdtempSync(join(tmpdir(), "vr-watchlist-import-"));
  mkdirSync(evidenceDir, { recursive: true });
  const git = arg => execFileSync("git", ["rev-parse", arg], { cwd: frontend, encoding: "utf8" }).trim();
  const result = { checkoutHead: git("HEAD"), checkoutTree: git("HEAD^{tree}"), frontendSourceTree: git("HEAD:frontend/src"), pullRequestHead: process.env.WATCHLIST_IMPORT_PR_HEAD || null, coverage: "Synthetic HTTP full-app desktop/mobile; rejected-draft retention, visible actionable error, explicit rejected retry, existing editor subset save and reload without duplicate migration; table invalid-row blocking, dedup/read-only preview and explicit conditional apply.", results: [] };
  let browser, server;
  try {
    assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first");
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
    server = await staticServer();
    const baseURL = `http://127.0.0.1:${server.address().port}`;
    for (const width of [1440, 390]) {
      const row = await runScenario(browser, baseURL, width, evidenceDir);
      result.results.push(row);
      console.log(`[watchlist-import] ${width}px ${row.status}`);
    }
    assert.equal(result.results.filter(row => row.status === "PASS").length, 2, "both viewports must pass");
  } catch (error) { result.error = error.stack || error.message; throw error; }
  finally {
    writeFileSync(join(evidenceDir, "results.json"), JSON.stringify(result, null, 2));
    try { await browser?.close(); }
    finally { server?.closeAllConnections(); if (server) await new Promise(done => server.close(done)); }
  }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
