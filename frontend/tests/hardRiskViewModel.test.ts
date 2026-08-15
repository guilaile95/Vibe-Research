/**
 * P0-HR1 Hard Risk view-model 契约测试。
 *
 * 覆盖（工作单 §6 frontend acceptance 1-11）：
 * - CONFIRMED visible（danger，明确文案）
 * - CONFIRMED != EXIT/SELL（绝不出现卖出/退出/清仓/EXIT/SELL 文案）
 * - CLEAR visible only for explicit positive-proof CLEAR
 * - UNKNOWN / NOT_EVALUATED / ERROR 一律不绿
 * - reason codes 透传可见
 * - authority refs（provenance）透传可见
 * - sibling Campaign 状态隔离（纯函数，互不污染）
 * - refresh / payload-driven（payload 变化 → 输出变化）
 * - missing / null / 非法字段 fail closed（不显示安全）
 * 第 12 项（现有 Decision Inbox 卡片回归）由全量 npm test 覆盖。
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  HARD_RISK_EVALUATIONS,
  HARD_RISK_STATES,
  hardRiskDisplay,
} from "../src/lib/hardRiskViewModel.ts";

const FORBIDDEN = ["卖出", "退出", "清仓", "EXIT", "SELL"];

function assertNoAutoExitText(text: string) {
  for (const token of FORBIDDEN) {
    assert.equal(text.includes(token), false, `CONFIRMED 文案不得包含「${token}」`);
  }
}

// ---------------------------------------------------------------------------
// 1. CONFIRMED visible
// ---------------------------------------------------------------------------

test("CONFIRMED：danger tone + 明确「已确认 Hard Risk」", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    reason_codes: ["HARD_RISK_CONFIRMED"],
    authority_refs: ["hard-risk:confirmed-authority"],
  });
  assert.equal(view.tone, "danger");
  assert.equal(view.statusLabel, "已确认 Hard Risk");
  assert.equal(view.showSafeGreen, false);
});

// ---------------------------------------------------------------------------
// 2. CONFIRMED != EXIT/SELL
// ---------------------------------------------------------------------------

test("CONFIRMED：绝不包含自动卖出/退出/清仓/EXIT/SELL 文案", () => {
  for (const evaluation of [undefined, "EVALUATED"]) {
    const view = hardRiskDisplay({
      hard_risk_state: "CONFIRMED",
      hard_risk_evaluation: evaluation,
    });
    assertNoAutoExitText(view.statusLabel);
    assertNoAutoExitText(view.description);
    assert.match(view.description, /重新审查/);
    assert.match(view.description, /Action Envelope/);
  }
});

// ---------------------------------------------------------------------------
// 3. CLEAR visible only for explicit CLEAR
// ---------------------------------------------------------------------------

test("CLEAR：显式 positive-proof CLEAR 才显示安全绿色", () => {
  const clear = hardRiskDisplay({ hard_risk_state: "CLEAR" });
  assert.equal(clear.tone, "safe");
  assert.equal(clear.showSafeGreen, true);
  assert.equal(clear.statusLabel, "已确认无 Hard Risk");

  const withEvaluated = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
  });
  assert.equal(withEvaluated.showSafeGreen, true);
});

test("CLEAR：evaluation 与 state 矛盾（非法 pair）→ fail closed 不绿", () => {
  for (const evaluation of ["UNKNOWN", "NOT_EVALUATED", "ERROR"]) {
    const view = hardRiskDisplay({
      hard_risk_state: "CLEAR",
      hard_risk_evaluation: evaluation,
    });
    assert.equal(view.showSafeGreen, false, `CLEAR + ${evaluation} 不得显示安全`);
    assert.notEqual(view.tone, "safe");
  }
});

// ---------------------------------------------------------------------------
// 4. UNKNOWN not green
// ---------------------------------------------------------------------------

test("UNKNOWN：不显示安全绿色", () => {
  const view = hardRiskDisplay({ hard_risk_state: "UNKNOWN" });
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.tone, "unknown");
  assert.equal(view.statusLabel, "Hard Risk 状态未知");
});

// ---------------------------------------------------------------------------
// 5. NOT_EVALUATED not green
// ---------------------------------------------------------------------------

test("NOT_EVALUATED：不显示安全绿色", () => {
  const view = hardRiskDisplay({ hard_risk_state: "NOT_EVALUATED" });
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.statusLabel, "尚未完成 Hard Risk 评估");
});

// ---------------------------------------------------------------------------
// 6. ERROR not green
// ---------------------------------------------------------------------------

test("ERROR：评估失败明确呈现，不得 silently green", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "ERROR",
  });
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.tone, "unknown");
  assert.equal(view.statusLabel, "Hard Risk 评估失败");
  assert.equal(view.evaluationLabel, "ERROR");
});

test("ERROR：任何 state 下 evaluation=ERROR 都优先失败语义", () => {
  for (const state of ["CLEAR", "CONFIRMED", "UNKNOWN", "NOT_EVALUATED"]) {
    const view = hardRiskDisplay({
      hard_risk_state: state,
      hard_risk_evaluation: "ERROR",
    });
    assert.equal(view.showSafeGreen, false, `${state} + ERROR 不得显示安全`);
    assert.equal(view.statusLabel, "Hard Risk 评估失败");
  }
});

// ---------------------------------------------------------------------------
// 7. reason codes visible
// ---------------------------------------------------------------------------

test("reason codes：原样透传，不解释不推断", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    reason_codes: ["HARD_RISK_CONFIRMED", "REVIEW_BY_REACHED"],
  });
  assert.deepEqual(view.reasonCodes, ["HARD_RISK_CONFIRMED", "REVIEW_BY_REACHED"]);
});

test("reason codes：缺失 → 空数组（不伪造）", () => {
  const view = hardRiskDisplay({ hard_risk_state: "UNKNOWN" });
  assert.deepEqual(view.reasonCodes, []);
});

// ---------------------------------------------------------------------------
// 8. provenance visible where available
// ---------------------------------------------------------------------------

test("authority refs：顶层透传", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    authority_refs: ["hard-risk:lake-snapshot-1"],
  });
  assert.deepEqual(view.authorityRefs, ["hard-risk:lake-snapshot-1"]);
});

test("authority refs：顶层缺失时 fallback explainability", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    explainability: { authority_refs: ["hard-risk:di1-authority"] },
  });
  assert.deepEqual(view.authorityRefs, ["hard-risk:di1-authority"]);
});

test("authority refs：完全缺失 → 空数组", () => {
  const view = hardRiskDisplay({ hard_risk_state: "CONFIRMED" });
  assert.deepEqual(view.authorityRefs, []);
});

// ---------------------------------------------------------------------------
// 9. sibling Campaign state isolated
// ---------------------------------------------------------------------------

test("sibling Campaign：同一 security 不同策略的 hard risk 互不污染", () => {
  const swing = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:swing"],
  });
  const short = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:short"],
  });
  assert.equal(swing.tone, "danger");
  assert.equal(swing.showSafeGreen, false);
  assert.equal(short.tone, "safe");
  assert.equal(short.showSafeGreen, true);
  assert.deepEqual(swing.authorityRefs, ["hard-risk:swing"]);
  assert.deepEqual(short.authorityRefs, ["hard-risk:short"]);
});

// ---------------------------------------------------------------------------
// 10. refresh / render based on backend payload
// ---------------------------------------------------------------------------

test("payload-driven：同一输入稳定，输入变化输出变化（refresh 语义）", () => {
  const first = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
  });
  const second = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
  });
  assert.deepEqual(second, first, "相同 payload 必须产生相同视图");

  const refreshed = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
  });
  assert.notEqual(refreshed.statusLabel, first.statusLabel);
  assert.equal(refreshed.showSafeGreen, true);
});

// ---------------------------------------------------------------------------
// 11. missing field fail closed
// ---------------------------------------------------------------------------

test("missing：hard_risk_state 缺失 / null → fail closed 不绿", () => {
  for (const state of [undefined, null]) {
    const view = hardRiskDisplay({ hard_risk_state: state });
    assert.equal(view.showSafeGreen, false);
    assert.notEqual(view.tone, "safe");
    assert.equal(view.statusLabel, "Hard Risk 状态未知");
  }
});

test("非法枚举：未知 state / evaluation 字符串 → fail closed 不绿", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "MAYBE_RISK",
    hard_risk_evaluation: "SOMETIMES",
  });
  assert.equal(view.showSafeGreen, false);
  assert.notEqual(view.tone, "safe");
  assert.equal(view.statusLabel, "Hard Risk 状态未知");
});

// ---------------------------------------------------------------------------
// 常量冻结
// ---------------------------------------------------------------------------

test("状态常量与 shared contract 一致", () => {
  assert.deepEqual(HARD_RISK_STATES, ["CLEAR", "CONFIRMED", "UNKNOWN", "NOT_EVALUATED"]);
  assert.deepEqual(HARD_RISK_EVALUATIONS, ["EVALUATED", "UNKNOWN", "NOT_EVALUATED", "ERROR"]);
});
