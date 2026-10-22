import assert from "node:assert/strict";
import test from "node:test";
import { blankOperand, compareForecast, contentDigest, evidenceMaterial, replayResearchCalculation, reportPageMaterials, safeSourceUrl, type CheckOperand } from "../src/lib/researchCheck.ts";
import { materialKey, validateResearchRound, type ResearchMaterial } from "../src/lib/researchWorkflow.ts";
import type { EvidenceRecord, MyReport, ReportPageReadResult } from "../src/lib/api/types.ts";

const source = (id: string, content: string): ResearchMaterial => ({ id, version: "fixture-v1", securityCode: "300672", title: id, content, sourceUrl: "https://example.com/fixture.pdf", sourceKind: "report_pages", sourceHash: "a".repeat(64), publishedAt: "2025-01-24", capturedAt: 1, availability: "partial", readRange: { pages: [1], totalPages: 3, truncated: false, ocr: false, description: "Synthetic fixture, first page only" } });
const forecastSource = source("synthetic-original", "证券代码300672；2024全年；合并报表；归属于上市公司股东的净利润；单位：万元；预计盈利648.13–753.93万元。");
const revisedSource = source("synthetic-revised", "证券代码300672；2024全年；合并报表；归属于上市公司股东的净利润；单位：万元；预计亏损594.25–891.37万元，修订预告不是实际业绩。");
const actualSource = source("synthetic-actual", "证券代码300672；2024全年；合并报表；归母净利润；单位：万元；实际700万元。");
const materials = [forecastSource, revisedSource, actualSource];
const operand = (material: ResearchMaterial, fields: Partial<CheckOperand> = {}): CheckOperand => ({ ...blankOperand(), materialKey: materialKey(material), sourceExcerpt: material.content, subject: "300672", metric: "归母净利润", periodStart: "2024-01-01", periodEnd: "2024-12-31", periodType: "annual", currency: "CNY", unit: "万元", basis: "consolidated", valueType: "forecast", low: "648.13", high: "753.93", confirmed: true, ...fields });
const original = operand(forecastSource);
const revised = operand(revisedSource, { low: "-594.25", high: "-891.37" });
const actual = operand(actualSource, { low: "700", high: "", valueType: "actual" });

test("T0 missing actual material refuses instead of guessing; no AI or future material needed", () => {
  const result = compareForecast("300672", "actual", original, actual, [forecastSource]);
  assert.equal(result.comparable, false); assert.match(result.reason, /缺少本轮/); assert.equal(result.result, "不能比较");
});
test("revised negative forecast endpoints normalize and remain predictions, preserving T0", () => {
  const result = compareForecast("300672", "revision", original, revised, materials);
  assert.equal(result.comparable, true); assert.match(result.formula, /\[-8913700, -5942500\]/);
  assert.match(result.result, /不重叠.*不是实际业绩/); assert.equal(result.inputs.length, 4);
  assert.deepEqual(result.inputs.map(input => input.valueType), ["forecast", "forecast", "forecast", "forecast"]);
  assert.equal(original.low, "648.13"); assert.equal(revised.low, "-594.25");
  assert.deepEqual(replayResearchCalculation("300672", result, materials), result);
});
test("actual interval comparison is exact, inclusive and source-quote bound", () => {
  const result = compareForecast("300672", "actual", original, actual, materials);
  assert.equal(result.comparable, true); assert.equal(result.result, "实际值落在所选预告区间内");
  assert.match(result.formula, /6481300 ≤ 7000000 ≤ 7539300/);
  assert.equal(compareForecast("300672", "actual", original, { ...actual, low: "701" }, materials).comparable, false);
  assert.equal(compareForecast("300672", "actual", original, { ...actual, sourceExcerpt: "made up 700" }, materials).comparable, false);
  assert.deepEqual(replayResearchCalculation("300672", result, materials), result);
});
test("mixed scale requires separate explicit confirmation, exact decimal scale conversion", () => {
  const f = source("goer-forecast-fixture", "归母净利润预计255698.02–277459.56万元");
  const a = source("goer-actual-fixture", "归母净利润2665044826.06元");
  const first = operand(f, { low: "255698.02", high: "277459.56" });
  const second = operand(a, { low: "2665044826.06", high: "", unit: "元", valueType: "actual" });
  assert.match(compareForecast("300672", "actual", first, second, [f, a]).reason, /原单位不一致/);
  const result = compareForecast("300672", "actual", first, second, [f, a], true);
  assert.equal(result.comparable, true); assert.equal(result.unitConversionConfirmed, true);
  assert.match(result.formula, /2556980200 ≤ 2665044826.06 ≤ 2774595600/);
  assert.deepEqual(replayResearchCalculation("300672", result, [f, a]), result);
});
for (const [name, patch] of Object.entries({ stock: { subject: "000001" }, metric: { metric: "扣非归母净利润" }, period: { periodEnd: "2024-09-30" }, periodType: { periodType: "YTD" }, invalidDate: { periodEnd: "2024-02-30" }, currency: { currency: "USD" }, unknownUnit: { unit: "" }, unknownBasis: { basis: "" }, parentBasis: { basis: "parent" }, forecastAsActual: { valueType: "forecast" }, unconfirmed: { confirmed: false } })) {
  test(`refuse unknown/mismatched ${name} without a result`, () => assert.equal(compareForecast("300672", "actual", original, { ...actual, ...patch } as CheckOperand, materials).comparable, false));
}
test("does not accept unread link, different-stock material, malformed mode or unsupported decimal", () => {
  assert.equal(compareForecast("300672", "other" as "actual", original, actual, materials).comparable, false);
  for (const patch of [{ content: "", availability: "link_only" }, { securityCode: "000001" }]) assert.equal(compareForecast("300672", "actual", original, actual, [forecastSource, { ...actualSource, ...patch } as ResearchMaterial]).comparable, false);
  for (const value of ["NaN", "Infinity", "1e4", "", "0x10", "1.0000000000001"]) assert.equal(compareForecast("300672", "actual", { ...original, low: value }, actual, materials).comparable, false);
});
test("numeric support requires complete number token, not substring, while sign remains manually confirmed", () => {
  const single = source("one", "实际11万元");
  const result = compareForecast("300672", "actual", original, operand(single, { low: "1", valueType: "actual" }), [forecastSource, single]);
  assert.equal(result.comparable, false); assert.match(result.reason, /数值未出现/);
});
test("corrupted replay grouping and source references reject; frozen valid round requires explicitly reviewed operands", () => {
  const result = compareForecast("300672", "actual", original, actual, materials);
  const forged = structuredClone(result); forged.inputs[1].period = "2023-01-01/2023-12-31|annual";
  assert.throws(() => replayResearchCalculation("300672", forged, materials));
  const round = { id: "r", questionId: "q", securityCode: "300672", parentRoundId: null, createdAt: 1, materials, calculation: result, judgement: "limited", limitations: "synthetic", nextMaterial: "cashflow", reviewedMaterialKeys: [materialKey(forecastSource), materialKey(actualSource)], ignoredMaterialKeys: [], coverage: "partial" };
  assert.equal(validateResearchRound(round).calculation?.comparable, true);
  assert.throws(() => validateResearchRound({ ...round, reviewedMaterialKeys: [] }));
});
test("per-page snapshots retain actual text, file hash, returned coverage and user-confirmed identity separately", async () => {
  const report: MyReport = { id: "fixture-report", name: "fixture.pdf", size: 123, industry: "synthetic", ext: ".pdf", ts: 1, file_sha256: "a".repeat(64), page_count: 2, source_url: "https://example.com/original" };
  const result: ReportPageReadResult = { report_id: report.id, file_sha256: report.file_sha256!, scope: "INDEXED_PAGE_TEXT_ONLY", full_report_read: false, requested: [1, 2, 3], returned_chars: 4, complete_requested_text: false, coverage: { readable: [1], omitted: [2], invalid: [3], unreadable: [], error: [] }, items: [{ page: 1, status: "readable", reason: "AVAILABLE", text: "实际原文", returned_chars: 4, indexed_chars: 8, truncated: true }, { page: 2, status: "omitted", reason: "BUDGET" }, { page: 3, status: "invalid", reason: "OUT_OF_RANGE" }] };
  const snapshots = await reportPageMaterials(report, result, "300672", 1, 3);
  assert.equal(snapshots.length, 3); assert.equal(snapshots[0].content, "实际原文"); assert.equal(snapshots[0].readRange.truncated, true);
  assert.equal(snapshots[0].availability, "partial"); assert.equal(snapshots[2].availability, "unavailable"); assert.deepEqual(snapshots[2].readRange.pages, []);
  assert.equal(snapshots[0].sourceHash, report.file_sha256); assert.match(snapshots[0].readRange.description, /full_report_read.*false/);
  assert.deepEqual(snapshots[0].provenance?.security_assignment, { code: "300672", basis: "USER_CONFIRMED_FROM_ORIGINAL_PAGE", automatically_verified: false });
  const changed = await reportPageMaterials(report, { ...result, items: [{ ...result.items[0], text: "changed" }, ...result.items.slice(1)] }, "300672", 1, 3);
  assert.notEqual(changed[0].version, snapshots[0].version);
  await assert.rejects(() => reportPageMaterials(report, { ...result, file_sha256: "b".repeat(64) }, "300672", 1, 3));
});
test("existing evidence snapshot retains exact excerpt, not invented original file hash", async () => {
  const record = { id: "e", subject_type: "stock", subject_id: "300672", deleted: 0, claim: "actual excerpt", source_title: "source", source_url: "https://example.com/doc", source_date: "2025-01-24", updated_at: "2025-01-24T00:00:00Z", classification: "inference", confidence: "low" } as EvidenceRecord;
  const snapshot = await evidenceMaterial(record, "300672"); assert.equal(snapshot.content, record.claim); assert.equal(snapshot.sourceHash, null); assert.equal(snapshot.availability, "partial"); assert.match(snapshot.readRange.description, /不代表读取原链接全文/);
  assert.notEqual((await evidenceMaterial({ ...record, claim: "changed" }, "300672")).version, snapshot.version);
  await assert.rejects(() => evidenceMaterial(record, "000001"));
  assert.equal((await contentDigest("x")).length, 64); assert.equal(safeSourceUrl("javascript:alert(1)"), null); assert.equal(safeSourceUrl("https://user:password@example.com"), null);
});
