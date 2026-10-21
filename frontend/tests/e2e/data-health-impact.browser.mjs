// Production UI + bounded synthetic read-only APIs, no model/provider execution.
import assert from "node:assert/strict";
import { join } from "node:path";
export async function runHealthImpactScenario(browser, baseURL, width, evidenceDir) {
  const context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [], unexpected = [];
  let calls = 0, release;
  const late = new Promise(done => { release = done; });
  const record = id => ({ source_id: id, display_name: id === "quotes" ? "SYNTHETIC_PROVIDER" : "SYNTHETIC_LEDGER", module: "synthetic", status: "normal", is_stale: false, blocks_advice: false, last_error_code: null });
  const impact = recovered => ({ schema_version: "data-health-impact.v1", source_id: "evidence_ledger", mapping_state: "mapped", reason_code: "PERSISTED_LEDGER_LINKS", truncated: false,
    items: [{ thesis_id: "synthetic_thesis", title: "SYNTHETIC_RESEARCH", subject_type: "stock", subject_id: "600519", frozen: true, path: "/thesis/synthetic_thesis", evidence: [
      { evidence_id: "synthetic_evidence", state: "available", path: "/evidence/synthetic_evidence" },
      { evidence_id: "missing_evidence", state: recovered ? "available" : "missing", path: recovered ? "/evidence/missing_evidence" : null },
      { evidence_id: "wrong_subject", state: "subject_mismatch", path: null },
    ] }] });
  const detail = (id, value, marker) => ({ data: { record: record(id), calculation: {}, related_pages: [], impact: value, marker } });
  await context.addInitScript(() => {
    const native = window.fetch.bind(window); window.__healthImpactParsed = [];
    window.fetch = async (...args) => {
      const response = await native(...args), json = response.json.bind(response);
      response.json = async () => { const value = await json(); if (value?.data?.marker) window.__healthImpactParsed.push(value.data.marker); return value; };
      return response;
    };
  });
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
  await context.routeWebSocket("**/*", socket => { unexpected.push("websocket"); socket.close(); });
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
    if (url.origin !== baseURL) { unexpected.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (request.method() === "GET" && url.pathname === "/api/data-health") return route.fulfill({ json: { data: {
      items: [record("evidence_ledger"), record("quotes")], overall_status: "normal", blocks_advice: false, block_reasons: [],
      summary: { normal: 2, partial: 0, unavailable: 0, stale: 0, not_initialized: 0 },
    } } });
    if (request.method() === "GET" && url.pathname === "/api/data-health/evidence_ledger") {
      calls += 1;
      if (calls === 3) { await late; return route.fulfill({ json: detail("evidence_ledger", impact(false), "late") }); }
      return route.fulfill({ json: detail("evidence_ledger", impact(calls > 1), "current") });
    }
    if (request.method() === "GET" && url.pathname === "/api/data-health/quotes") return route.fulfill({ json: detail("quotes", {
      schema_version: "data-health-impact.v1", source_id: "quotes", mapping_state: "unmapped", reason_code: "NO_REGISTERED_OBJECT_BINDING", truncated: false, items: [],
    }, "provider") });
    unexpected.push(`${request.method()} ${url.pathname}`);
    return route.fulfill({ status: 503, json: { detail: "UNEXPECTED_SYNTHETIC_REQUEST" } });
  });
  try {
    await page.goto("/data-health", { waitUntil: "domcontentloaded" });
    const card = name => page.locator("div.cursor-pointer").filter({ has: page.getByText(name, { exact: true }) });
    await card("SYNTHETIC_LEDGER").click();
    const panel = page.getByRole("region", { name: "影响范围与下一步" });
    await panel.getByText(/股票：600519/).waitFor();
    assert.match(await panel.innerText(), /已冻结.*冻结快照保持不变/);
    assert.match(await panel.innerText(), /missing_evidence：当前记录缺失或已删除/);
    assert.match(await panel.innerText(), /wrong_subject：主体不一致/);
    assert.equal(await panel.getByRole("link", { name: "查看证据", exact: true }).count(), 1);
    assert.equal(await panel.getByRole("link", { name: "查看证据", exact: true }).getAttribute("href"), "/evidence/synthetic_evidence");
    assert.equal(await panel.getByRole("link", { name: "查看投资逻辑并人工核对" }).getAttribute("href"), "/thesis/synthetic_thesis");
    assert.equal(await panel.getByRole("button").count(), 0);
    await page.screenshot({ path: join(evidenceDir, `health-impact-${width}-missing.png`), fullPage: true });
    await page.getByRole("button", { name: "重新读取", exact: true }).click();
    await panel.getByText(/missing_evidence：当前记录可读取/).waitFor();
    assert.equal(await panel.getByRole("link", { name: "查看证据", exact: true }).count(), 2);
    await page.getByRole("button", { name: "重新读取", exact: true }).click();
    await page.getByText("加载详情…", { exact: true }).waitFor();
    assert.equal(await panel.count(), 0, "stale impact hidden during loading");
    await card("SYNTHETIC_PROVIDER").click();
    await panel.getByText(/尚未登记此来源到股票/).waitFor();
    release();
    await page.waitForFunction(() => window.__healthImpactParsed.includes("late"));
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.match(await panel.innerText(), /尚未登记此来源到股票/);
    assert.doesNotMatch(await panel.innerText(), /600519|SYNTHETIC_RESEARCH|synthetic_evidence/);
    assert.equal(await panel.getByRole("link").count(), 0);
    assert.deepEqual(unexpected, []); assert.deepEqual(errors, []);
    await page.screenshot({ path: join(evidenceDir, `health-impact-${width}-pass.png`), fullPage: true });
    return { scenario: "health-impact", width, status: "PASS", ledgerCalls: calls };
  } finally { release(); await context.close(); }
}
