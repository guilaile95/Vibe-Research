import test from "node:test";
import assert from "node:assert/strict";
import { currentSourceImpact, type DataHealthImpact } from "../src/lib/dataHealthView.ts";

const mapped: DataHealthImpact = { schema_version: "data-health-impact.v1", source_id: "evidence_ledger",
  mapping_state: "mapped", reason_code: "PERSISTED_LEDGER_LINKS", truncated: false, items: [] };
test("impact belongs to exact current source and supported schema", () => {
  assert.equal(currentSourceImpact("evidence_ledger", mapped), mapped);
  assert.equal(currentSourceImpact("quotes", mapped), null);
  assert.equal(currentSourceImpact("evidence_ledger", undefined), null);
  assert.equal(currentSourceImpact("evidence_ledger", { ...mapped, schema_version: "future" } as unknown as DataHealthImpact), null);
});
test("unmapped and empty registered sets stay distinct", () => {
  const unmapped = { ...mapped, source_id: "quotes", mapping_state: "unmapped" as const };
  assert.equal(currentSourceImpact("quotes", unmapped)?.mapping_state, "unmapped");
  assert.equal(currentSourceImpact("evidence_ledger", mapped)?.mapping_state, "mapped");
});
