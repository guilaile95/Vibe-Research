import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { api, listCampaigns } from "../src/lib/api.ts";
import { recoveredMarketApi } from "../src/lib/recoveredMarketApi.ts";
import { discoverySectors, filterDiscoveryItems, discoveryFiltersFromSearch } from "../src/lib/discoveryView.ts";
import { buildDiscoveryResearchOrigin } from "../src/lib/discoveryResearchOrigin.ts";
import { validateReportPageOcrResponse } from "../src/lib/localReportOcr.ts";
import { reportPageMaterials } from "../src/lib/researchCheck.ts";
import { discoverySnapshot, originalReport, revisedReport, originalText, researchCheckReadReply, researchCheckPageReadReply } from "./e2e/research-check-loop.fixture.mjs";

// Run the real clients through the same pure reply functions used by Playwright.
// No browser or HTTP server starts, and no providers/model/network are contacted.
test("UI fixture matches raw Discovery and data-wrapped MyReports/evidence/campaign contracts", async t => {
  const oldFetch = globalThis.fetch, oldStorage = globalThis.localStorage;
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: () => null } });
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), "http://synthetic.invalid");
    const reply = init?.method === "POST" ? researchCheckPageReadReply(JSON.parse(String(init.body)), 1) : researchCheckReadReply(url.pathname, url.search, 1);
    assert.notEqual(reply, null, `unhandled fixture endpoint ${url.pathname}`);
    return new Response(JSON.stringify(reply), { headers: { "Content-Type": "application/json" } });
  };
  t.after(() => { globalThis.fetch = oldFetch; Object.defineProperty(globalThis, "localStorage", { configurable: true, value: oldStorage }); });
  const snapshot = await recoveredMarketApi.getDiscovery();
  assert.deepEqual(snapshot, discoverySnapshot); assert.equal("data" in snapshot, false);
  assert.deepEqual(discoverySectors(snapshot), ["合成行业"]);
  const items = filterDiscoveryItems(snapshot, discoveryFiltersFromSearch(new URLSearchParams("strategy=SWING")));
  assert.equal(items.length, 1); assert.equal(items[0].security_code, "600519");
  const origin = buildDiscoveryResearchOrigin(items[0], snapshot, ["财务时效待核"]);
  assert.ok(origin); assert.equal(origin.observations[0].rawValue, "0.12");
  assert.equal(snapshot.funnel.queue_items.SWING, snapshot.queues.SWING.length);
  assert.equal(snapshot.coverage?.filter_scope, "RETURNED_QUEUE_ONLY");
  assert.equal(snapshot.datasets[1].source_coverage?.full_text_included, false);
  assert.deepEqual(await api.myReports(), [originalReport, revisedReport]);
  const hits = await api.searchMyReportText("归母净利润", [revisedReport.id]);
  assert.equal(hits[0].report_id, revisedReport.id); assert.equal(hits[0].title, revisedReport.title); assert.equal(hits[0].extraction_kind, "DOCUMENT_TEXT");
  assert.deepEqual(await listCampaigns({ security_code: "600519" }), []);
  const evidence = await api.evidenceList({ subject_type: "stock", subject_id: "600519", limit: 200, offset: 0 });
  assert.equal(evidence.total, 0); assert.deepEqual(evidence.items, []);
  const theses = await api.thesisList({ subject_type: "stock", subject_id: "600519", limit: 20, offset: 0 });
  assert.equal(theses.limit, 20); assert.deepEqual(theses.items, []);
  const intel = await api.nativeIntelSecurityContext("600519");
  assert.equal(intel.security.code, "600519"); assert.equal(intel.observation.source_count, 0); assert.equal(intel.rank_history.available, false);
  for (const end of [1, 2]) {
    const response = await api.readReportPages({ report_id: originalReport.id, expected_file_sha256: originalReport.file_sha256!, selected_report_ids: [originalReport.id], page_from: 1, page_to: end });
    validateReportPageOcrResponse(response, originalReport.id, originalReport.file_sha256!, 1, end);
    const materials = await reportPageMaterials(originalReport, response, "600519", 1, end);
    assert.equal(materials[0].content, originalText); assert.equal(response.complete_requested_text, end === 1);
    if (end === 2) assert.deepEqual(response.coverage.omitted, [2]);
  }
});
test("fixture keeps transport separation and refuses unavailable or mismatched T0 page input", () => {
  assert.equal("data" in researchCheckReadReply("/api/screener/discovery"), false);
  assert.ok("data" in researchCheckReadReply("/api/myreports"));
  assert.equal("data" in researchCheckReadReply("/api/native-intel/security-context/600519"), false);
  assert.deepEqual(researchCheckReadReply("/api/myreports").data, [originalReport]);
  assert.throws(() => researchCheckPageReadReply({ report_id: revisedReport.id, expected_file_sha256: revisedReport.file_sha256, selected_report_ids: [revisedReport.id], page_from: 1, page_to: 1 }, 0), /T0/);
  assert.throws(() => researchCheckPageReadReply({ report_id: originalReport.id, expected_file_sha256: "wrong", selected_report_ids: [originalReport.id], page_from: 1, page_to: 1 }));
  const browser = readFileSync(new URL("./e2e/research-check-loop.browser.mjs", import.meta.url), "utf8");
  assert.match(browser, /researchCheckReadReply\(path, url\.search, reportStage\)/);
  assert.match(browser, /json: researchCheckPageReadReply\(input, reportStage\)/);
  assert.match(browser, /page\.goto\('\/screener\?mode=discovery&strategy=SWING'\)/);
  assert.doesNotMatch(browser, /ok\(discoverySnapshot\)/);
});
