import assert from "node:assert/strict";
import test from "node:test";
import { klineResearchEvents, positionResearchEvents, researchDate } from "../src/lib/klineResearchEvents.ts";
import type { EvidenceRecord, ResearchEventCalendarEvent } from "../src/lib/api/types.ts";
const event = (overrides = {}): ResearchEventCalendarEvent => ({ event_id: "event-a", security_code: "000001", security_name: null, campaign_ids: ["campaign-a", "campaign-b"], event_type: "ANNOUNCEMENT", event_date: "2026-07-18", date_semantics: "DATE_ONLY", state: "OBSERVED", title: "Synthetic weekend event", details: {}, source: "fixture", source_record_identity: "record-a", fetched_at: "2026-07-20", limitations: [], ...overrides });
const evidence = (overrides = {}): EvidenceRecord => ({ id: "evidence-a", subject_type: "stock", subject_id: "000001", evidence_type: "report", claim: "synthetic", source_title: "Synthetic evidence", source_url: null, source_date: "2026-07-20", accessed_at: "2026-07-22", classification: "fact", confidence: "high", created_at: "2026-07-22", updated_at: "2026-07-22", deleted: 0, deleted_at: null, ...overrides });

test("dates are strict calendar dates: leap dates valid; rolled/unknown/timestamps never mapped to today", () => {
  assert.equal(researchDate("2024-02-29"), "2024-02-29");
  for (const raw of [null, "", "unknown", "2026-02-29", "2026-02-30", "2026-07-20T00:00:00Z", "2026-1-1"]) assert.equal(researchDate(raw), null);
});
test("stock boundaries exclude foreign, sector and deleted evidence; IDs remain source-specific", () => {
  const rows = klineResearchEvents("000001", [event(), event({ security_code: "000002", event_id: "foreign" })], [evidence(), evidence({ id: "sector", subject_type: "sector" }), evidence({ id: "foreign", subject_id: "000002" }), evidence({ id: "deleted", deleted: 1 })]);
  assert.deepEqual(rows.map((x) => x.key), ["calendar:event-a", "evidence:evidence-a"]);
  assert.deepEqual(rows[0].campaignIds, ["campaign-a", "campaign-b"]);
  assert.deepEqual(rows[1].campaignIds, []);
});
test("missing bar maps only to the next available bar inside window while preserving real event date", () => {
  const [row] = positionResearchEvents(klineResearchEvents("000001", [event()], []), ["2026-07-17", "2026-07-20"]);
  assert.equal(row.placement, "NEXT_AVAILABLE_BAR"); assert.equal(row.barDate, "2026-07-20"); assert.equal(row.event.date, "2026-07-18");
});
test("exact date, outside window and unknown remain distinct", () => {
  const rows = positionResearchEvents(klineResearchEvents("000001", [event({ event_id: "before", event_date: "2026-07-16" }), event({ event_id: "after", event_date: "2026-07-21" }), event({ event_id: "unknown", event_date: null }), event({ event_id: "exact", event_date: "2026-07-20" })], []), ["2026-07-17", "2026-07-20"]);
  assert.deepEqual(Object.fromEntries(rows.map((x) => [x.event.id, x.placement])), { before: "OUTSIDE_WINDOW", exact: "EXACT", after: "OUTSIDE_WINDOW", unknown: "UNKNOWN_DATE" });
  assert.equal(rows.filter((x) => x.barDate).length, 1);
});
test("UNKNOWN date semantics cannot use a date-looking value as authoritative", () => {
  const [row] = klineResearchEvents("000001", [event({ date_semantics: "UNKNOWN" })], []);
  assert.equal(row.date, null); assert.equal(row.rawDate, "2026-07-18");
});
test("undated evidence never falls back to accessed_at or created_at; no guessed campaign", () => {
  const [row] = klineResearchEvents("000001", [], [evidence({ source_date: null })]);
  assert.equal(row.date, null); assert.deepEqual(row.campaignIds, []);
});
test("window changes recompute mapping instead of retaining an old point", () => {
  const rows = klineResearchEvents("000001", [event()], []);
  assert.equal(positionResearchEvents(rows, ["2026-07-17", "2026-07-20"])[0].barDate, "2026-07-20");
  assert.equal(positionResearchEvents(rows, ["2026-07-21", "2026-07-22"])[0].barDate, null);
  assert.equal(positionResearchEvents(rows, [])[0].barDate, null);
});
test("duplicate source IDs collapse without merging evidence and calendar namespaces", () => {
  const rows = klineResearchEvents("000001", [event(), event()], [evidence({ id: "event-a" })]);
  assert.equal(rows.length, 2); assert.notEqual(rows[0].key, rows[1].key);
});
