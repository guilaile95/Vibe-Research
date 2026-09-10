import assert from "node:assert/strict";
import test from "node:test";

import {
  factorAggregateLabel,
  factorIcText,
  factorObservationHasCoverageLimitation,
  factorRatioText,
  factorReturnText,
  factorValidationStatusLabel,
} from "../src/lib/factorValidationView.ts";

test("factor validation keeps null and real zero distinct", () => {
  assert.equal(factorIcText(null), "—");
  assert.equal(factorIcText(0), "0.0000");
  assert.equal(factorReturnText(null), "—");
  assert.equal(factorReturnText(0), "0.0000%");
  assert.equal(factorRatioText(0), "0.00%");
});

test("factor validation labels bounded observations and coverage limitations", () => {
  assert.equal(factorValidationStatusLabel("EVALUATED"), "已评估");
  assert.equal(factorValidationStatusLabel("IMMATURE_FORWARD_WINDOW"), "未来窗口未成熟");
  assert.equal(factorAggregateLabel({ forward_window: 5 } as any), "5 条已存储观测");
  assert.equal(factorObservationHasCoverageLimitation({ factor_null_count: 0, immature_outcome_count: 1, invalid_outcome_count: 0 } as any), true);
  assert.equal(factorObservationHasCoverageLimitation({ factor_null_count: 0, immature_outcome_count: 0, invalid_outcome_count: 0 } as any), false);
});
