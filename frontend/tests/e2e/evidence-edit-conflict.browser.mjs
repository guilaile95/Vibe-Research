// Deterministic production-UI concurrency harness. Synthetic API only; no providers.
// Run after npm run build. Browser execution is intentionally separate from node tests.
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dist = fileURLToPath(new URL("../../dist/", import.meta.url));
const output = process.env.EVIDENCE_EDIT_CONFLICT_BROWSER_OUTPUT_DIR || mkdtempSync(join(tmpdir(), "evidence-edit-conflict-"));
mkdirSync(output, { recursive: true });
assert.ok(existsSync(join(dist, "index.html")), "Build frontend/dist first");
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
const server = createServer((request, response) => {
  let path = resolve(dist, `.${new URL(request.url, "http://localhost").pathname}`);
  if (!path.startsWith(resolve(dist) + sep)) return response.writeHead(403).end();
  if (!existsSync(path) || !extname(path)) path = join(dist, "index.html");
  response.setHeader("Content-Type", mime[extname(path)] || "application/octet-stream");
  createReadStream(path).pipe(response);
});
const token = n => `evidence-edit.v1:${n.toString(16).padStart(64, "0")}`;
let version = 1;
const seed = () => ({ id: "ev-conflict", edit_token: token(version), subject_type: "stock", subject_id: "000001", evidence_type: "news", claim: "Initial claim", source_title: "Initial source", source_url: null, source_date: "2026-10-01", accessed_at: "2026-10-01T10:00:00.000Z", classification: "fact", confidence: "high", created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z", deleted: 0, deleted_at: null });
let current = seed(), failNextGet = false, missing = false;
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
let heldRequest = null;
const holdNext = method => (heldRequest = { method, started: deferred(), release: deferred() });
const bounded = promise => Promise.race([promise, new Promise((_, reject) => {
  const timer = setTimeout(() => reject(new Error("Held request timed out")), 10000);
  timer.unref();
})]);
const writes = [], errors = [], outbound = [];
let browser, context;
let status = "FAIL", failure = null;
const fieldLabels = { evidence_type: "证据类型", claim: "证据论断", source_title: "来源标题", source_url: "来源 URL", source_date: "来源日期", accessed_at: "查阅时间", classification: "分类", confidence: "置信度" };
const humanDraft = { evidence_type: "report", claim: "Human draft\nKeep every line", source_title: "Human title", source_url: "https://example.invalid/draft", source_date: "2026-10-02", accessed_at: "2026-10-02T12:34", classification: "inference", confidence: "low" };
const edit = page => page.getByRole("button", { name: "编辑", exact: true }).click();
const save = page => page.getByRole("button", { name: "保存", exact: true }).click();
const ready = page => page.getByRole("button", { name: "编辑", exact: true }).waitFor();
const conflict = page => page.getByTestId("evidence-edit-conflict").waitFor();
const readDraft = async page => Object.fromEntries(await Promise.all(Object.entries(fieldLabels).map(async ([key, label]) => [key, await page.getByLabel(label, { exact: true }).inputValue()])));
const assertDraft = async page => assert.deepEqual(await readDraft(page), humanDraft);
const confirmClick = async (page, locator, accept) => {
  page.once("dialog", dialog => accept ? dialog.accept() : dialog.dismiss());
  await locator.click();
};
try {
  await new Promise(done => server.listen(0, "127.0.0.1", done));
  const base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
  context = await browser.newContext({ serviceWorkers: "block", timezoneId: "UTC" });
  await context.routeWebSocket("**/*", socket => { outbound.push(socket.url()); socket.close(); });
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url()), method = request.method();
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
    if (url.origin !== base) { outbound.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (url.pathname === "/api/evidence/ev-next" && method === "GET") return route.fulfill({ json: { data: { ...seed(), id: "ev-next", claim: "Next route record" } } });
    if (url.pathname === "/api/evidence/ev-conflict") {
      const held = heldRequest?.method === method ? heldRequest : null;
      if (held) { heldRequest = null; held.started.resolve(); await held.release.promise; }
      if (method === "GET") {
        if (failNextGet) { failNextGet = false; return route.fulfill({ status: 503, json: { detail: "Synthetic latest read failed" } }); }
        if (missing) return route.fulfill({ status: 404, json: { detail: "Evidence missing" } });
        return route.fulfill({ json: { data: current } });
      }
      if (method === "PUT" || method === "DELETE") {
        const body = method === "PUT" ? request.postDataJSON() : null;
        const expected = body?.expected_edit_token ?? url.searchParams.get("expected_edit_token");
        writes.push({ method, expected, body });
        assert.match(expected, /^evidence-edit\.v1:[0-9a-f]{64}$/);
        if (method === "DELETE") assert.equal(url.searchParams.get("confirm"), "true");
        if (current.deleted) return route.fulfill({ status: 404, json: { detail: "Evidence deleted" } });
        if (expected !== current.edit_token) return route.fulfill({ status: 409, json: { detail: "Evidence changed; reload latest" } });
        version += 1;
        if (body) { const { expected_edit_token, ...fields } = body; current = { ...current, ...fields }; }
        else current = { ...current, deleted: 1, deleted_at: "2026-10-09T00:00:00Z" };
        current.edit_token = token(version);
        return route.fulfill({ json: { data: current } });
      }
    }
    return route.fulfill({ status: 503, json: { detail: "Synthetic optional source unavailable" } });
  });
  const a = await context.newPage(), b = await context.newPage();
  for (const page of [a, b]) { page.setDefaultTimeout(10000); page.on("pageerror", e => errors.push(e.message)); }
  const open = async page => { await page.goto(`${base}/evidence/ev-conflict`); await ready(page); };
  await open(a); await open(b); await edit(a); await edit(b);
  for (const [key, value] of Object.entries(humanDraft)) {
    const control = b.getByLabel(fieldLabels[key], { exact: true });
    if (["evidence_type", "classification", "confidence"].includes(key)) await control.selectOption(value);
    else await control.fill(value);
  }
  await a.getByLabel("证据论断", { exact: true }).fill("Writer A saved");
  await save(a); await ready(a);
  assert.equal(writes[0].expected, token(1)); assert.equal(current.claim, "Writer A saved");
  failNextGet = true;
  await save(b); await conflict(b); await b.getByTestId("evidence-latest-error").waitFor();
  await assertDraft(b);
  assert.equal(writes.length, 2); assert.equal(writes[1].expected, token(1));
  assert.equal(await b.getByRole("button", { name: "保存", exact: true }).isDisabled(), true);
  assert.equal(await b.getByTestId("evidence-discard-reload").isDisabled(), true);
  await b.getByTestId("evidence-refresh-latest").click();
  await b.getByTestId("evidence-conflict-comparison").waitFor(); await assertDraft(b);
  for (const key of Object.keys(fieldLabels)) await b.getByTestId(`evidence-compare-${key}`).waitFor();
  await b.screenshot({ path: join(output, "conflict-preserved-draft.png"), fullPage: true });
  await confirmClick(b, b.getByTestId("evidence-discard-reload"), false); await assertDraft(b);
  assert.equal(writes.length, 2, "Comparison refresh and rejected discard never retry a write");
  await confirmClick(b, b.getByTestId("evidence-discard-reload"), true); await ready(b);
  const staleDelete = await context.newPage(); await open(staleDelete);
  await edit(b); await b.getByLabel("证据论断", { exact: true }).fill("Explicit fresh edit"); await save(b); await ready(b);
  assert.equal(writes.at(-1).expected, token(2)); assert.equal(current.claim, "Explicit fresh edit");
  await confirmClick(staleDelete, staleDelete.getByRole("button", { name: "删除", exact: true }), true);
  await conflict(staleDelete); await staleDelete.getByTestId("evidence-conflict-comparison").waitFor();
  assert.equal(writes.at(-1).method, "DELETE"); assert.equal(writes.at(-1).expected, token(2)); assert.equal(current.deleted, 0);
  await confirmClick(staleDelete, staleDelete.getByTestId("evidence-discard-reload"), true);
  await confirmClick(staleDelete, staleDelete.getByRole("button", { name: "删除", exact: true }), true);
  await staleDelete.waitForURL(`${base}/evidence`); assert.equal(current.deleted, 1);
  // Deletion racing with a human draft: preserve draft; forbid further writes.
  version += 1; current = seed(); await open(a); await open(b); await edit(b);
  await b.getByLabel("证据论断", { exact: true }).fill("Keep deleted evidence draft");
  await confirmClick(a, a.getByRole("button", { name: "删除", exact: true }), true); await a.waitForURL(`${base}/evidence`);
  await save(b); await conflict(b); await b.getByTestId("evidence-latest-deleted").waitFor();
  assert.equal(await b.getByLabel("证据论断", { exact: true }).inputValue(), "Keep deleted evidence draft");
  assert.equal(await b.getByRole("button", { name: "保存", exact: true }).isDisabled(), true);
  // A missing latest read must not erase or unlock the draft either.
  missing = true; await b.getByTestId("evidence-refresh-latest").click(); await b.getByTestId("evidence-latest-error").waitFor();
  assert.equal(await b.getByLabel("证据论断", { exact: true }).inputValue(), "Keep deleted evidence draft");
  assert.equal(await b.getByTestId("evidence-discard-reload").isDisabled(), true);
  // Late save, comparison read and delete responses must not affect a new route.
  missing = false;
  const navigateNext = async page => {
    await page.evaluate(() => { history.pushState(null, "", "/evidence/ev-next"); dispatchEvent(new PopStateEvent("popstate")); });
    await page.getByRole("heading", { name: "Next route record", exact: true }).waitFor();
  };
  const assertNext = async (page, held, method) => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === "/api/evidence/ev-conflict" && r.request().method() === method);
    held.release.resolve(); await (await response).finished();
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.equal(new URL(page.url()).pathname, "/evidence/ev-next");
    await page.getByRole("heading", { name: "Next route record", exact: true }).waitFor();
    assert.equal(await page.getByTestId("evidence-edit-conflict").count(), 0);
    assert.equal(await page.locator("textarea").count(), 0);
  };
  version += 1; current = seed(); await open(b); await edit(b);
  await b.getByLabel("证据论断", { exact: true }).fill("Late save");
  let held = holdNext("PUT"); await save(b); await bounded(held.started.promise); await navigateNext(b); await assertNext(b, held, "PUT");
  await open(b); await edit(b); version += 1; current = { ...current, edit_token: token(version) };
  held = holdNext("GET"); await save(b); await bounded(held.started.promise); await navigateNext(b); await assertNext(b, held, "GET");
  await open(b); held = holdNext("DELETE");
  await confirmClick(b, b.getByRole("button", { name: "删除", exact: true }), true);
  await bounded(held.started.promise); await navigateNext(b); await assertNext(b, held, "DELETE");
  assert.deepEqual(errors, []); assert.deepEqual(outbound, []);
  await b.screenshot({ path: join(output, "complete-next-route.png"), fullPage: true });
  status = "PASS";
  console.log("PASS: stale edit/delete, all-field draft preservation, failed/missing latest, explicit discard/re-edit, deleted record lockout; synthetic API only");
} catch (error) {
  failure = String(error?.stack || error);
  throw error;
} finally {
  const pages = context?.pages() || [];
  const diagnostics = [];
  for (const [index, page] of pages.entries()) {
    if (status === "FAIL") {
      await page.screenshot({ path: join(output, `failure-page-${index}.png`), fullPage: true }).catch(() => {});
      diagnostics.push({ url: page.url(), text: await page.locator("body").innerText().catch(() => "unavailable") });
    }
  }
  writeFileSync(join(output, "results.json"), JSON.stringify({ status, writes: writes.length, errors, outbound, failure, diagnostics }, null, 2));
  await browser?.close();
  await new Promise(done => server.close(done));
}
