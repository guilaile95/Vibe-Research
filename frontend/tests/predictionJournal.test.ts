import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parsePredictionJournal, verifyPredictionWrite, PredictionGeneration, predictionPercent } from "../src/lib/predictionJournal.ts";
const empty = () => ({ schema_version: "manual-prediction.v1", as_of: "2026-01-03T00:00:00Z", records: [] as unknown[], summary: { total: 0, resolved_binary: 0, unresolved: 0, indeterminate: 0, brier: null, benchmark_count: 0, benchmark_brier: null, matched_forecast_brier: null, sample_caution: true, display_caution_minimum: 20, bins: Array.from({ length: 10 }, (_, i) => ({ lower: i / 10, upper: (i + 1) / 10, upper_inclusive: i === 9, count: 0, mean_probability: null, observed_frequency: null, sample_caution: true })) } });
function unresolved() {
  const data = empty(); data.summary.total = 1; data.summary.unresolved = 1;
  data.records = [{ schema_version: data.schema_version, forecast: { id: "fixture", question: "Binary criterion?", subject: "Synthetic", probability: .7, deadline: "2026-01-02T00:00:00Z", evidence_context: "Manual fixture", evidence_kind: "USER_ASSERTION", outcome_not_known: true, benchmark_probability: null, benchmark_context: null }, locked_at: "2026-01-01T00:00:00Z", revision: 0, outcome: "UNRESOLVED", history: [] }];
  return data;
}
test("honest empty and unresolved contract", () => {
  assert.equal(parsePredictionJournal(empty()).summary.brier, null);
  assert.equal(parsePredictionJournal(unresolved()).records[0].outcome, "UNRESOLVED");
  const bad = empty(); Object.assign(bad.summary, { brier: 0 }); assert.throws(() => parsePredictionJournal(bad));
});
test("no percentages confused with unit probabilities", () => {
  assert.equal(predictionPercent(.7), "70.0%"); assert.equal(predictionPercent(null), "不可用");
  const bad = unresolved(); (bad.records[0] as any).forecast.probability = 70; assert.throws(() => parsePredictionJournal(bad));
});
test("reject future outcomes and malformed history before rendering", () => {
  const bad = unresolved(); Object.assign(bad.records[0] as object, { revision: 1, outcome: "TRUE", history: [{ revision: 1, recorded_at: "2026-01-04T00:00:00Z", resolution: { expected_revision: 0, outcome: "TRUE", available_at: "2026-01-02T00:00:00Z", evidence: "Manual", evidence_kind: "USER_ASSERTION", correction_reason: "Initial" } }] });
  assert.throws(() => parsePredictionJournal(bad));
  const forged = unresolved(); (forged.records[0] as any).locked_at = "2026-01-04T00:00:00Z"; assert.throws(() => parsePredictionJournal(forged));
});
test("reject unknown outcomes, duplicate forecast identities, nonfinite stats and shifted bins", () => {
  const bad = unresolved(); (bad.records[0] as any).outcome = "unknown"; assert.throws(() => parsePredictionJournal(bad));
  const duplicate = unresolved(); duplicate.records.push(duplicate.records[0]); assert.throws(() => parsePredictionJournal(duplicate));
  const nan = empty(); Object.assign(nan.summary, { brier: NaN }); assert.throws(() => parsePredictionJournal(nan));
  const bins = empty(); bins.summary.bins[1].lower = .11; assert.throws(() => parsePredictionJournal(bins));
});
test("generation invalidates late reads after filter change, reload and unmount", () => {
  const gen = new PredictionGeneration(), first = gen.next();
  assert.equal(gen.current(first), true); gen.next(); assert.equal(gen.current(first), false);
  const second = gen.next(); assert.equal(gen.current(second), true); gen.next(); assert.equal(gen.current(second), false);
});
test("UI binds explicit manual mutations and independent authoritative readback", () => {
  const source = readFileSync(new URL("../src/components/personal-review/PredictionJournal.tsx", import.meta.url), "utf8");
  assert.match(source, /writing\.current \|\| uncertain \|\| asOf \|\| !data/);
  assert.match(source, /expected_revision: record\.revision/);
  assert.match(source, /generation\.current\.current\(token\)/);
  assert.match(source, /parsePredictionJournal\(raw\)/);
  assert.match(source, /不是统计证明/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|\/ai\//);
});

test("summary cannot silently disagree with registered outcomes", () => {
  const bad = unresolved(); Object.assign(bad.summary, { unresolved: 0, resolved_binary: 1, brier: 0 });
  assert.throws(() => parsePredictionJournal(bad));
});

 test("authoritative write readback must match requested content", () => {
   const data = parsePredictionJournal(unresolved());
   verifyPredictionWrite(data, "fixture", data.records[0].forecast as unknown as Record<string, unknown>, true);
   assert.throws(() => verifyPredictionWrite(data, "fixture", { probability: .1 }, true));
   assert.throws(() => verifyPredictionWrite(data, "fixture", { expected_revision: 0 }, false));
   assert.throws(() => verifyPredictionWrite(data, "missing", {}, true));
 });
