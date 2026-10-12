import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validObservationView } from "../src/lib/observationWorkflows.ts";
import { metricDefinitions, formatMetric } from "../src/lib/nextDayVerification.ts";
const golden = JSON.parse(readFileSync(new URL("./fixtures/observation-workflows-preview.json", import.meta.url), "utf8"));
const empty = JSON.parse(readFileSync(new URL("./fixtures/observation-workflows-empty.json", import.meta.url), "utf8"));
test("all real-service synthetic payloads have six date-owned slots and disabled activation", () => {
  assert.equal(validObservationView(golden, golden.trade_date), true);
  for (const [day, value] of Object.entries(empty)) assert.equal(validObservationView(value, day), true);
  assert.equal(validObservationView(golden, "2026-07-30"), false);
  assert.equal(golden.slots[0].observation.price_basis, "open_vs_previous_close");
  assert.equal(golden.events.length, 1);
});
for (const [name, mutate] of [
  ["invalid observed time", (x: any) => x.slots[0].observation.observed_at = "bad"],
  ["null source list", (x: any) => x.slots[0].observation.rows[0].sources = null],
  ["null cohort", (x: any) => x.slots[0].observation.cohort = null],
  ["string median", (x: any) => x.slots[0].observation.cohort.median_pct = "1"],
  ["false completeness", (x: any) => x.slots[0].observation.cohort.samples = 0],
  ["infinite event", (x: any) => x.events[0].move_pct = Infinity],
  ["duplicate event", (x: any) => x.events.push(x.events[0])],
  ["duplicate slot", (x: any) => x.slots[1] = x.slots[0]],
  ["external activation", (x: any) => x.external_notifications_enabled = true],
  ["task unknown", (x: any) => x.tasks[0].kind = "send_external"],
] as const) test(`malformed observation rejects ${name} without render crash`, () => {
  const value = structuredClone(golden); mutate(value); assert.equal(validObservationView(value), false);
});
test("eight condition units retain ratio versus percentage-point distinction", () => {
  assert.equal(Object.keys(metricDefinitions).length, 8);
  assert.equal(formatMetric("money_effect_median", 0.5), "0.5 百分点");
  assert.equal(formatMetric("promotion_1to2", 0.5), "50.0%");
  assert.equal(formatMetric("deep_loss_count", null), "未知");
});

test("slot source timestamps cannot roll normalized dates or cross immutable cutoffs", () => {
  for (const bad of ["2026-02-30T01:25:00Z", "2026-07-31T24:00:00Z", "2026-07-31T01:29:00Z"]) {
    const value = structuredClone(golden); value.slots[0].observation.observed_at = bad;
    assert.equal(validObservationView(value), false);
  }
  const future = structuredClone(golden); future.slots[0].observation.rows[0].provider_at = "2026-07-31T01:25:01Z";
  assert.equal(validObservationView(future), false);
});

test("synthetic labels and rendered state identities are closed enums", () => {
  for (const change of [
    (x: any) => x.fixture_label = {}, (x: any) => x.synthetic = "true",
    (x: any) => x.calendar_state = "PERMISSION_GRANTED", (x: any) => x.events[0].kind = "BUY",
    (x: any) => x.events[0].symbol = "foreign", (x: any) => x.generated_at = "0000-01-01T00:00:00Z",
  ]) { const value = structuredClone(golden); change(value); assert.equal(validObservationView(value), false); }
});

test("microsecond future provider and changed immutable cutoff are rejected", () => {
  const future = structuredClone(golden);
  future.slots[0].observation.rows[0].provider_at = "2026-07-31T01:25:00.000001Z";
  assert.equal(validObservationView(future), false);
  const cutoff = structuredClone(golden);
  cutoff.slots[0].observation.cutoff_at = "2026-07-31T01:29:00.000001Z";
  assert.equal(validObservationView(cutoff), false);
});
