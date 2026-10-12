import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { isShortlineResearchForDate } from "../src/lib/shortlineResearch.ts";
const fixture = JSON.parse(readFileSync(new URL("./fixtures/shortline-research.golden.json", import.meta.url)));
const day = "2026-07-30";
test("real Python synthetic raw-replay response validates without dropping cohorts", () => {
  assert.equal(isShortlineResearchForDate(fixture, day), true);
  assert.equal(fixture.fixture, true);
  assert.equal(fixture.projection.cohort.rows.length, 3);
  assert.equal(fixture.projection.cohort.groups.all_yesterday.unknown, 1);
});
test("date ownership, unknown arithmetic and immutable authority fail closed", () => {
  assert.equal(isShortlineResearchForDate(fixture, "2026-07-29"), false);
  for (const mutate of [
    x => x.point_in_time_claim = "KNOWN",
    x => x.ingestion_enabled = true,
    x => x.projection.cohort.rows.push(x.projection.cohort.rows[0]),
    x => x.projection.cohort.groups.all_yesterday.mean_pct = Infinity,
    x => x.projection.daily.ladder_gaps = "bad",
    x => x.projection.history.windows[0].dates.push(day),
    x => x.evidence[0].receipts[0].committed_at = "2026-07-30T00:00:00Z",
  ]) { const value = structuredClone(fixture); mutate(value); assert.equal(isShortlineResearchForDate(value, day), false); }
});
test("unavailable is explicit with no projection", () => {
  const value = { ...fixture, status: "unavailable", evidence: [], projection: null };
  assert.equal(isShortlineResearchForDate(value, day), true);
  value.projection = fixture.projection;
  assert.equal(isShortlineResearchForDate(value, day), false);
});
test("view is date-owned GET only and pagination cannot change denominator", () => {
  const source = readFileSync(new URL("../src/components/dailyReview/ShortlineResearchCard.tsx", import.meta.url), "utf8");
  assert.match(source, /generation\.current/); assert.match(source, /controller\.abort\(\)/);
  assert.match(source, /state\?\.day === tradeDate/);
  assert.match(source, /slice\(page \* 20, \(page \+ 1\) \* 20\)/);
  assert.doesNotMatch(source, /setInterval|localStorage|"POST"|"PUT"/);
});

for (const [label, mutate] of [
 ["structure median", x => x.projection.structure.market_structure.recent_10.median_limit_up_count = {}],
 ["null regime", x => x.projection.structure.regime_events = null],
 ["cohort denominator", x => x.projection.cohort.previous_limit_up_denominator = {}],
 ["coverage child", x => x.projection.cohort.outcome_coverage.classified = {}],
 ["sample status", x => x.projection.samples.windows[0].status = {}],
 ["band median", x => x.projection.structure.market_structure.recent_10.source_10pct_band_share_median = {}],
 ["invalid date", x => x.previous_trade_date = "2026-02-30"],
 ["ratio", x => x.projection.cohort.groups.all_yesterday.coverage_ratio = 2],
]) test(`reject malformed rendered ${label}`, () => {
 const bad = structuredClone(fixture); mutate(bad); assert.equal(isShortlineResearchForDate(bad, day), false);
});

for (const [label, mutate] of [
 ["invalid receipt date", x => x.evidence[0].trade_date = "2026-02-30"],
 ["normalized timestamp", x => x.evidence[0].receipts[0].captured_at = "2026-02-30T07:00:00Z"],
 ["24 hour timestamp", x => x.evidence[0].receipts[0].captured_at = "2026-07-29T24:00:00Z"],
 ["timezone absent", x => x.evidence[0].receipts[0].captured_at = "2026-07-29T07:00:00"],
 ["year zero", x => x.evidence[0].receipts[0].captured_at = "0000-07-29T07:00:00Z"],
 ["receipt ordering", x => x.evidence[0].receipts[0].locally_received_at = "2026-07-28T07:00:00Z"],
 ["fractional boards", x => x.projection.cohort.rows[0].previous_boards = 1.5],
 ["negative band denominator", x => x.projection.daily.price_limit_bands.denominator = -1],
]) test(`reject malformed provenance ${label}`, () => {
 const bad = structuredClone(fixture); mutate(bad); assert.equal(isShortlineResearchForDate(bad, day), false);
});

test("receipt ordering preserves microseconds and equivalent timezone instants", () => {
 const x = structuredClone(fixture); const r = x.evidence[0].receipts[0];
 r.captured_at = "2026-07-29T07:00:00.000002Z"; r.locally_received_at = "2026-07-29T07:00:00.000001Z";
 assert.equal(isShortlineResearchForDate(x, day), false);
 r.locally_received_at = "2026-07-29T15:00:00.000002+08:00";
 assert.equal(isShortlineResearchForDate(x, day), true);
});
